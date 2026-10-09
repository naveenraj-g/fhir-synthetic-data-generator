"""Reads what Synthea wrote: output/fhir/*.json (one transaction Bundle per patient, plus
hospitalInformation*/practitionerInformation* infrastructure bundles) and output/metadata/*.json."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_INFRA_PREFIXES = ("hospitalInformation", "practitionerInformation")


def _fhir_dir(output_dir: Path) -> Path:
    return output_dir / "fhir"


def patient_files(output_dir: Path) -> list[Path]:
    """Sorted for determinism. Synthea file names embed the patient's name + UUID, both seeded."""
    return sorted(p for p in _fhir_dir(output_dir).glob("*.json") if not p.name.startswith(_INFRA_PREFIXES))


def read_infra(output_dir: Path) -> dict[str, dict]:
    infra: dict[str, dict] = {}
    for p in sorted(_fhir_dir(output_dir).glob("*.json")):
        if p.name.startswith(_INFRA_PREFIXES):
            # Strip the timestamp suffix so the key is stable between runs.
            key = "hospitalInformation" if p.name.startswith("hospitalInformation") else "practitionerInformation"
            infra[key] = json.loads(p.read_text(encoding="utf-8"))
    return infra


def read_metadata(output_dir: Path) -> dict[str, Any]:
    files = sorted((output_dir / "metadata").glob("*.json"))
    return json.loads(files[0].read_text(encoding="utf-8")) if files else {}


def is_deceased(bundle: dict) -> bool:
    for entry in bundle.get("entry", []):
        res = entry.get("resource") or {}
        if res.get("resourceType") == "Patient":
            return "deceasedDateTime" in res or res.get("deceasedBoolean") is True
    return False


def iter_patient_bundles(output_dir: Path, limit: int | None) -> Iterator[dict]:
    """Lazily yields bundles (they can be several MB each), at most `limit` of them."""
    for i, path in enumerate(patient_files(output_dir)):
        if limit is not None and i >= limit:
            return
        yield json.loads(path.read_text(encoding="utf-8"))
