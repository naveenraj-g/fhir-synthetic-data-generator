"""Serves pre-baked, Synthea-shaped bundles. No Java needed — lets the whole
pipeline (API, slicers, sinks) be developed and tested without Synthea, and
proves the connector abstraction has more than one implementation.

Fixtures are cycled to reach `count`; every copy gets fresh, seed-derived
UUIDs so patients are distinct and the result is deterministic per seed."""

import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

from app.generator.connectors.base import (
    Connector,
    ConnectorCapabilities,
    ConnectorOptions,
    HealthStatus,
    RawOutput,
)
from app.generator.errors import ConnectorUnavailableError
from app.generator.registry import connectors
from app.generator.spec import CohortSpec

BACKEND_DIR = Path(__file__).resolve().parents[3]
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_NAMESPACE = uuid.UUID("6f1c2d4e-0b7a-4c1e-9a55-2f3a8e1d7b90")


def remap_ids(text: str, salt: str) -> str:
    """Replace every UUID in a serialized bundle with a deterministic new one (same old id
    -> same new id within a call, so references stay consistent)."""
    mapping: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        old = match.group(0)
        if old not in mapping:
            mapping[old] = str(uuid.uuid5(_NAMESPACE, f"{salt}:{old}"))
        return mapping[old]

    return _UUID_RE.sub(repl, text)


class StaticFixturesOptions(ConnectorOptions):
    directory: str = "fixtures/synthea_r4"


@connectors.register("static_fixtures")
class StaticFixturesConnector(Connector):
    Options = StaticFixturesOptions
    options: StaticFixturesOptions

    @property
    def _dir(self) -> Path:
        path = Path(self.options.directory)
        return path if path.is_absolute() else BACKEND_DIR / path

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(native_filters={"count", "seed"})

    def _patient_files(self) -> list[Path]:
        return sorted(p for p in self._dir.glob("patient_*.json"))

    async def healthcheck(self) -> HealthStatus:
        if not self._patient_files():
            return HealthStatus(False, f"No patient_*.json fixtures in {self._dir}")
        return HealthStatus(True, f"{len(self._patient_files())} fixture bundle(s) in {self._dir}")

    async def generate(self, cohort: CohortSpec, workdir: Path) -> RawOutput:
        files = self._patient_files()
        if not files:
            raise ConnectorUnavailableError(f"No patient_*.json fixtures found in {self._dir}")
        seed = cohort.seed if cohort.seed is not None else 0
        texts = [f.read_text(encoding="utf-8") for f in files]

        def bundles() -> Iterator[dict]:
            for i in range(cohort.count):
                text = texts[i % len(texts)]
                yield json.loads(remap_ids(text, f"{seed}:{i}"))

        infra = {
            f.stem: json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(self._dir.glob("*Information*.json"))
        }
        return RawOutput(
            patient_bundles=bundles(),
            infra=infra,
            meta={
                "connector": "static_fixtures",
                "fixture_files": [f.name for f in files],
                "seed": seed,
            },
        )
