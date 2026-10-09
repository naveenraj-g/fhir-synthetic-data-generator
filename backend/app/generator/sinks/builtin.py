"""Phase-1 sinks: inline, zip, ndjson."""

import asyncio
import json
import zipfile
from collections.abc import Iterable
from pathlib import Path

from app.generator import fhir
from app.generator.errors import LimitExceededError
from app.generator.registry import sinks
from app.generator.sinks.base import ArtifactFile, DeliveryContext, DeliveryResult, Sink


def _file(path: Path, content_type: str) -> ArtifactFile:
    return ArtifactFile(
        filename=path.name, path=path, content_type=content_type, size=path.stat().st_size
    )


@sinks.register("inline")
class InlineSink(Sink):
    description = "Return the bundles in the HTTP response body (small cohorts only)."
    returns_inline = True

    async def deliver(self, bundles: Iterable[dict], ctx: DeliveryContext) -> DeliveryResult:
        collected: list[dict] = []
        size = 0
        for bundle in bundles:
            size += len(json.dumps(bundle, separators=(",", ":")))
            if size > ctx.inline_max_bytes:
                raise LimitExceededError(
                    f"Inline result exceeds {ctx.inline_max_bytes} bytes; "
                    "use a file sink such as 'zip' or 'ndjson'"
                )
            collected.append(bundle)
        return DeliveryResult(inline=collected)


@sinks.register("json")
class JsonSink(Sink):
    description = (
        "One JSON file holding a list of the FHIR bundles, kept for download (and shown in the UI). "
        "Unlike `inline`, the HTTP request does not wait for the run, so long Synthea runs are safe."
    )

    async def deliver(self, bundles: Iterable[dict], ctx: DeliveryContext) -> DeliveryResult:
        def write() -> Path:
            ctx.artifact_dir.mkdir(parents=True, exist_ok=True)
            path = ctx.artifact_dir / "bundles.json"
            with open(path, "w", encoding="utf-8", newline="\n") as fh:  # streamed: one bundle at a time
                fh.write("[")
                for i, bundle in enumerate(bundles):
                    fh.write(",\n" if i else "\n")
                    json.dump(bundle, fh, separators=(",", ":"))
                fh.write("\n]\n")
            return path

        path = await asyncio.to_thread(write)
        return DeliveryResult(artifacts=[_file(path, "application/json")])


@sinks.register("zip")
class ZipSink(Sink):
    description = "One JSON file per bundle, zipped into a downloadable artifact."

    async def deliver(self, bundles: Iterable[dict], ctx: DeliveryContext) -> DeliveryResult:
        def write() -> Path:
            ctx.artifact_dir.mkdir(parents=True, exist_ok=True)
            path = ctx.artifact_dir / "bundles.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, bundle in enumerate(bundles, start=1):
                    zf.writestr(f"bundle-{i:05d}.json", json.dumps(bundle, indent=2))
            return path

        path = await asyncio.to_thread(write)
        return DeliveryResult(artifacts=[_file(path, "application/zip")])


@sinks.register("ndjson")
class NdjsonSink(Sink):
    description = (
        "FHIR Bulk-Data style: one <ResourceType>.ndjson file per type, one resource per line."
    )

    async def deliver(self, bundles: Iterable[dict], ctx: DeliveryContext) -> DeliveryResult:
        def write() -> list[Path]:
            ctx.artifact_dir.mkdir(parents=True, exist_ok=True)
            handles: dict = {}
            try:
                for bundle in bundles:
                    for res in fhir.resources(bundle):
                        rt = fhir.resource_type(res)
                        if rt not in handles:
                            handles[rt] = open(
                                ctx.artifact_dir / f"{rt}.ndjson", "w", encoding="utf-8", newline="\n"
                            )
                        handles[rt].write(json.dumps(res, separators=(",", ":")) + "\n")
            finally:
                for handle in handles.values():
                    handle.close()
            return [ctx.artifact_dir / f"{rt}.ndjson" for rt in sorted(handles)]

        paths = await asyncio.to_thread(write)
        return DeliveryResult(artifacts=[_file(p, "application/fhir+ndjson") for p in paths])
