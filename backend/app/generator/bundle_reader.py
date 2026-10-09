"""Reads the bundles back out of a finished job's stored files, for viewing (the flow graph).

Handles the three file shapes the sinks write:
  * `json`   - bundles.json: a JSON list of bundles
  * `zip`    - bundles.zip: one bundle-NNNNN.json per bundle
  * `ndjson` - <ResourceType>.ndjson: all patients mixed together, so there is no per-patient bundle; the
               resources are presented as one bundle of type `collection`.
Framework-free: it takes file paths and raises ValueError with a message meant for the user."""

import json
import zipfile
from pathlib import Path
from typing import Any

from app.generator import fhir

# A single stored file larger than this is not parsed for viewing (the download still works).
MAX_READ_BYTES = 64 * 1024 * 1024
# A zip is checked by what it holds once unpacked (the zip sink pretty-prints, so it expands a lot).
MAX_ZIP_UNPACKED_BYTES = 128 * 1024 * 1024


def _kind(files: list[Path]) -> str:
    names = [f.name.lower() for f in files]
    if any(n.endswith(".json") for n in names):
        return "json"
    if any(n.endswith(".zip") for n in names):
        return "zip"
    if any(n.endswith(".ndjson") for n in names):
        return "ndjson"
    raise ValueError("This job has no files that can be shown as a flow (JSON, ZIP or NDJSON bundles).")


def _check_size(path: Path) -> None:
    if path.stat().st_size > MAX_READ_BYTES:
        raise ValueError(
            f"{path.name} is {path.stat().st_size // (1024 * 1024)} MB, too large to draw. Download it instead, "
            "or generate fewer patients."
        )


def load_bundles(files: list[Path]) -> list[dict[str, Any]]:
    """Every bundle in the job's files, in order."""
    kind = _kind(files)
    if kind == "json":
        path = next(f for f in files if f.name.lower().endswith(".json"))
        _check_size(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    if kind == "zip":
        path = next(f for f in files if f.name.lower().endswith(".zip"))
        _check_size(path)
        with zipfile.ZipFile(path) as zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_ZIP_UNPACKED_BYTES:
                raise ValueError(
                    f"{path.name} holds more than {MAX_ZIP_UNPACKED_BYTES // (1024 * 1024)} MB of JSON, too large to draw. "
                    "Download it instead, or generate fewer patients."
                )
            members = sorted(n for n in zf.namelist() if n.lower().endswith(".json"))
            return [json.loads(zf.read(n)) for n in members]
    resources: list[dict] = []
    for path in sorted(f for f in files if f.name.lower().endswith(".ndjson")):
        _check_size(path)
        with open(path, encoding="utf-8") as fh:
            resources.extend(json.loads(line) for line in fh if line.strip())
    return [fhir.make_bundle([{"resource": r} for r in resources], "collection")]


def _patient_label(bundle: dict) -> str | None:
    for res in fhir.resources(bundle):
        if fhir.resource_type(res) == "Patient":
            name = (res.get("name") or [{}])[0]
            parts = [*(name.get("given") or []), name.get("family") or ""]
            return " ".join(p for p in parts if p) or None
    return None


def summarize(bundles: list[dict]) -> list[dict[str, Any]]:
    """One line per bundle: a label (the patient's name) and how many resources of each type it holds."""
    out = []
    for i, bundle in enumerate(bundles):
        by_type: dict[str, int] = {}
        for res in fhir.resources(bundle):
            rt = fhir.resource_type(res)
            by_type[rt] = by_type.get(rt, 0) + 1
        out.append(
            {
                "index": i,
                "label": _patient_label(bundle) or f"Bundle {i + 1}",
                "resources": sum(by_type.values()),
                "by_type": dict(sorted(by_type.items())),
            }
        )
    return out
