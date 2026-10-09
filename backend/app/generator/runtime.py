"""GeneratorRuntime: resolves a GenerationRequest against the config and runs the
pipeline  connector -> slicers -> synthetic stamp -> sink.  Framework-free."""

import copy
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.generator import fhir, registry
from app.generator.config_loader import GeneratorConfig, load_config
from app.generator.connectors.base import Connector
from app.generator.errors import (
    ConnectorUnavailableError,
    GenerationFailedError,
    GeneratorError,
    InvalidSpecError,
    LimitExceededError,
    UnsatisfiableCohortError,
)
from app.generator.fhir import StatsCollector, resources
from app.generator.sinks.base import ArtifactFile, DeliveryContext, Sink
from app.generator.slicers.base import SliceContext, Slicer
from app.generator.spec import (
    CohortSpec,
    GenerationOptions,
    GenerationRequest,
    ResolvedSpec,
    ShapeStep,
    SinkSpec,
)

SYNTHETIC_TAG = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
    "code": "HTEST",
    "display": "test health data",
}


def stamp_synthetic(bundle: dict) -> dict:
    """Tag every resource as test data so it cannot be mistaken for real records downstream."""
    for res in resources(bundle):
        tags = res.setdefault("meta", {}).setdefault("tag", [])
        if not any(t.get("code") == SYNTHETIC_TAG["code"] for t in tags):
            tags.append(dict(SYNTHETIC_TAG))
    return bundle


@dataclass
class PipelineResult:
    summary: dict[str, Any]
    provenance: dict[str, Any]
    artifacts: list[ArtifactFile] = field(default_factory=list)
    inline: list[dict] | None = None


def _merge(base: dict, over: dict) -> dict:
    """Deep-merge dicts; lists and scalars in `over` replace those in `base`."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class GeneratorRuntime:
    def __init__(self, config: GeneratorConfig):
        self.config = config
        self._connectors: dict[str, Connector] = {}

    @classmethod
    def from_path(cls, path: Path, env: dict[str, str] | None = None) -> "GeneratorRuntime":
        config = load_config(
            path,
            env=env,
            known_connector_types=set(registry.connectors.names()),
            known_slicers=set(registry.slicers.names()),
        )
        return cls(config)

    # ── component factories ──────────────────────────────────────────────
    def get_connector(self, name: str) -> Connector:
        if name not in self._connectors:
            entry = self.config.connector_entry(name)
            cls = registry.connectors.get(entry["type"])
            self._connectors[name] = cls(self.config.connector_options(name))
        return self._connectors[name]

    def build_slicer(self, step: ShapeStep) -> Slicer:
        cls = registry.slicers.get(step.slicer)
        params = _merge(self.config.slicer_defaults.get(step.slicer) or {}, step.params)
        return cls(params)

    def build_sink(self, spec: SinkSpec) -> Sink:
        entry = self.config.sinks.get(spec.name)
        if entry is None or entry.get("enabled", True) is False:
            raise InvalidSpecError(
                f"Unknown or disabled sink '{spec.name}'. Configured: {sorted(self.config.sinks)}"
            )
        cls = registry.sinks.get(entry["type"])
        return cls(_merge(entry.get("options") or {}, spec.params))

    # ── resolution ───────────────────────────────────────────────────────
    def resolve(self, request: GenerationRequest) -> ResolvedSpec:
        """Merge precedence (highest first): request > preset > specialty/config defaults."""
        preset = self.config.preset(request.preset) if request.preset else None

        connector_name = request.connector or (preset and preset.connector) or self.config.default_connector
        connector = self.get_connector(connector_name)

        cohort_data: dict[str, Any] = dict(preset.cohort) if preset else {}
        if request.cohort:
            cohort_data.update(request.cohort.model_dump(exclude_unset=True, exclude_none=True))
        if cohort_data.get("specialty"):
            # A specialty is a named set of condition codes; expand it so connectors only ever
            # see `conditions` (patients must have ANY of them). Explicit conditions are added.
            specialty = self.config.specialty(cohort_data["specialty"])
            for key in ("conditions", "procedures", "medications"):
                expanded = list(specialty.get(key) or [])
                cohort_data[key] = expanded + [c for c in (cohort_data.get(key) or []) if c not in expanded]
            # A specialty may carry a default age range (e.g. type 2 diabetes is vanishingly rare in children, so an
            # unbounded search wastes attempts and can fail); the request or preset wins when it sets one.
            if "age_range" not in cohort_data and specialty.get("age_range"):
                cohort_data["age_range"] = specialty["age_range"]
            if "within" not in cohort_data and specialty.get("within"):
                cohort_data["within"] = specialty["within"]
            if "gender" not in cohort_data and specialty.get("gender"):
                cohort_data["gender"] = specialty["gender"]
            # Specialties usually mean "has the disease OR had one of its operations": the specialty decides.
            if "match" not in cohort_data and specialty.get("match"):
                cohort_data["match"] = specialty["match"]
        try:
            cohort = CohortSpec(**cohort_data)
        except ValidationError as exc:
            raise InvalidSpecError(
                "Invalid cohort",
                details=[
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
                ],
            ) from None
        if cohort.seed is None:
            cohort = cohort.model_copy(update={"seed": secrets.randbelow(2**31)})

        shape = request.shape
        if shape is None:
            shape = preset.shape if preset and preset.shape is not None else [ShapeStep(slicer="full_record")]
        sink = request.sink or (preset and preset.sink) or SinkSpec(name="inline")

        spec = ResolvedSpec(
            connector=connector_name,
            cohort=cohort,
            shape=list(shape),
            sink=sink,
            options=request.options or GenerationOptions(),
            connector_params=dict(request.connector_params or {}),
            preset=request.preset,
        )

        # Validate every component now so errors surface at submit/preview time, not mid-job.
        for step in spec.shape:
            self.build_slicer(step)
        sink_impl = self.build_sink(spec.sink)

        limits = self.config.limits
        if cohort.count > limits.max_patients_per_job:
            raise LimitExceededError(
                f"cohort.count {cohort.count} exceeds max_patients_per_job={limits.max_patients_per_job}"
            )
        if sink_impl.returns_inline and cohort.count > limits.sync_max_patients:
            raise LimitExceededError(
                f"The inline sink supports at most {limits.sync_max_patients} patients "
                f"(requested {cohort.count}); use a file sink such as 'zip' or 'ndjson'"
            )

        connector.with_request_params(spec.connector_params)  # reject forbidden/invalid overrides now
        spec.warnings = self._warnings(spec, connector)
        return spec

    @staticmethod
    def _warnings(spec: ResolvedSpec, connector: Connector) -> list[str]:
        native = connector.capabilities().native_filters
        supplied = spec.cohort.model_dump(exclude_defaults=True, exclude={"count", "seed"})
        warnings = []
        for name in supplied:
            if name not in native:
                warnings.append(f"cohort.{name} is ignored by connector '{spec.connector}'")
        return warnings

    def sink_is_inline(self, spec: ResolvedSpec) -> bool:
        return self.build_sink(spec.sink).returns_inline

    # ── execution ────────────────────────────────────────────────────────
    async def run(self, spec: ResolvedSpec, *, workdir: Path, artifact_dir: Path) -> PipelineResult:
        started = time.perf_counter()
        connector = self.get_connector(spec.connector).with_request_params(spec.connector_params)
        slicers = [self.build_slicer(step) for step in spec.shape]
        sink = self.build_sink(spec.sink)

        health = await connector.healthcheck()
        if not health.ok:
            raise ConnectorUnavailableError(f"Connector '{spec.connector}' unavailable: {health.detail}")

        workdir.mkdir(parents=True, exist_ok=True)
        try:
            raw = await connector.generate(spec.cohort, workdir)
        except GeneratorError:
            raise
        except Exception as exc:  # connector bug / unexpected failure
            raise GenerationFailedError(f"Connector '{spec.connector}' failed: {exc}") from exc

        ctx = SliceContext(infra=raw.infra, meta=raw.meta)
        # What each stage let through, for the flow view: [("synthea", counter), ("resource_types", counter), ...]
        counters = [(spec.connector, fhir.StageCounter(raw.patient_bundles))]
        stream = counters[0][1]
        for step, slicer in zip(spec.shape, slicers, strict=True):
            counters.append((step.slicer, fhir.StageCounter(slicer.apply(stream, ctx))))
            stream = counters[-1][1]
        stream = (stamp_synthetic(b) for b in stream)
        stats = StatsCollector(stream)
        stats.check_references = spec.options.check_references

        delivery = await sink.deliver(
            stats,
            DeliveryContext(
                artifact_dir=artifact_dir, inline_max_bytes=self.config.limits.inline_max_bytes
            ),
        )

        if stats.bundle_count == 0:
            raise UnsatisfiableCohortError(
                "The requested shape produced no output: none of the generated patients had matching data "
                "(e.g. no encounter satisfied the selector). Relax the slicer params or the cohort."
            )

        if spec.options.check_references and stats.dangling:
            raise GenerationFailedError(
                f"Output contains {len(stats.dangling)} unresolved reference(s)",
                details=sorted(stats.dangling)[:50],
            )

        provenance = {
            **raw.meta,
            "connector_name": spec.connector,
            "fhir_version": self.config.fhir_version,
            "seed": spec.cohort.seed,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "stages": [{"stage": name, **counter.summary()} for name, counter in counters],
        }
        return PipelineResult(
            summary=stats.summary(),
            provenance=provenance,
            artifacts=delivery.artifacts,
            inline=delivery.inline,
        )
