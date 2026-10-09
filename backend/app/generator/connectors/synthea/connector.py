"""Synthea connector: runs the Synthea jar (in Docker by default, or from a local JDK) and
hands back its FHIR output. See plan/05-synthea-connector.md."""

import asyncio
import json
import os
import re
import shutil
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.generator.connectors.base import (
    Connector,
    ConnectorCapabilities,
    ConnectorOptions,
    HealthStatus,
    RawOutput,
)
from app.generator.connectors.static_fixtures import BACKEND_DIR
from app.generator.connectors.synthea import flags, output, places as places_index, runner, terms as terms_index
from app.generator.errors import (
    ConnectorUnavailableError,
    GenerationFailedError,
    InvalidSpecError,
    UnsatisfiableCohortError,
)
from app.generator.registry import connectors
from app.generator.spec import CohortSpec

DOCKER_JAR = "/opt/synthea/synthea.jar"

# Added to the seed for each retry after a timeout: deterministic, so a request still reproduces.
RETRY_SEED_STEP = 7919

# Applied under the user's `properties`. With a keep module (specialty/conditions) Synthea gives up on a
# patient slot after this many attempts and silently returns fewer patients; its default of 1000 is too low
# for less common conditions. Raising it trades run time for completeness.
DEFAULT_PROPERTIES: dict[str, Any] = {"generate.max_attempts_to_keep_patient": 10000}


class SyntheaOptions(ConnectorOptions):
    mode: Literal["docker", "local"] = "docker"

    # docker mode
    docker_bin: str = "docker"
    docker_image: str = "fhir-gen-synthea:4.0.0"  # build: `just synthea-build`

    # local mode
    java_bin: str = "java"
    jar_path: str = "vendor/synthea/synthea-with-dependencies.jar"

    jvm_args: list[str] = Field(default_factory=lambda: ["-Xmx2g"])
    timeout_seconds: int = Field(1800, ge=10, description="Per attempt")
    retries_on_timeout: int = Field(
        1, ge=0, le=3,
        description="Synthea occasionally stalls on one patient (seen: a seed that never finishes while its neighbours take 25 s). "
        "After a timeout the run is retried this many times with a derived seed, recorded in the job provenance",
    )  # fmt: skip
    modules_dir: str | None = Field(None, description="Custom Synthea modules folder (-d); config-only")
    reference_date: str | None = Field(
        None,
        pattern=r"^\d{8}$",
        description="YYYYMMDD (-r): ages are computed as of this date. Pin it for reproducibility",
    )
    end_date: str | None = Field(
        None,
        pattern=r"^\d{8}$",
        description="YYYYMMDD (-e): where the simulation stops. Defaults to reference_date. Synthea otherwise "
        "simulates up to TODAY, which silently makes the same seed give different data on different days",
    )
    default_state: str = "Massachusetts"
    years_of_history: int | None = 10
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Extra --key=value Synthea properties (not the connector-managed ones)"
    )
    cache_dir: str = Field("data/cache", description="Where the searchable term index is cached")


class SyntheaRequestParams(BaseModel):
    """What a single API request may override. Deliberately tiny: dates and a safe subset of FHIR export /
    generation properties (e.g. exporter.fhir.use_us_core_ig=true for US Core profiles)."""

    model_config = ConfigDict(extra="forbid")

    reference_date: str | None = Field(None, pattern=r"^\d{8}$", description="YYYYMMDD; ages are computed as of this date")
    end_date: str | None = Field(None, pattern=r"^\d{8}$", description="YYYYMMDD; where the simulation stops")
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("properties")
    @classmethod
    def _safe_properties(cls, value: dict[str, Any]) -> dict[str, Any]:
        flags.validate_request_properties(value)
        return value


_INDEX_CACHE: dict[str, Any] = {}  # "<index name>-<image or jar key>" -> the parsed index


def _abs(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else BACKEND_DIR / p


@connectors.register("synthea")
class SyntheaConnector(Connector):
    Options = SyntheaOptions
    RequestParams = SyntheaRequestParams
    options: SyntheaOptions

    def __init__(self, options: dict[str, Any]):
        super().__init__(options)
        flags.validate_properties(self.options.properties)

    def _merge_request_params(self, options: dict[str, Any], allowed: dict[str, Any]) -> dict[str, Any]:
        merged = {**options, **{k: v for k, v in allowed.items() if k != "properties"}}
        merged["properties"] = {**options.get("properties", {}), **allowed.get("properties", {})}
        return merged

    # ── searchable terms ─────────────────────────────────────────────────
    async def terms(self, q: str | None, kind: str | None, limit: int) -> tuple[list[dict[str, Any]], int]:
        if kind is not None and kind not in terms_index.KINDS:
            raise InvalidSpecError(f"Unknown kind '{kind}'. Available: {terms_index.KINDS}")
        index = await self._term_index()
        page, total = terms_index.search_terms(index, q, kind, limit)
        return [{**t, "reference": terms_index.reference_for(t)} for t in page], total

    async def _term_index(self) -> list[dict[str, Any]]:
        """Terms from the modules inside the jar; extracted once per image/jar and cached on disk."""
        return await self._index_from_jar(
            "terms", lambda jar: terms_index.extract_terms(terms_index.read_modules_from_jar(jar))
        )

    # ── states and cities ────────────────────────────────────────────────
    async def places(self, state: str | None) -> list[str]:
        """The valid state names, or (given a state, in any capitalisation) that state's valid city names."""
        places = await self._place_index()
        if state is None:
            return list(places)
        return places[places_index.resolve_place(places, state, None)[0]]

    async def _place_index(self) -> dict[str, list[str]]:
        return await self._index_from_jar("places", places_index.read_places_from_jar)

    async def _index_from_jar(self, name: str, build: Callable[[Path], Any]) -> Any:
        """`build(jar)` for the pinned Synthea jar, computed once per image/jar and cached in memory and on disk
        (`name` is the cache-file prefix). In docker mode the jar is first copied out of the image."""
        o = self.options
        if o.mode == "docker":
            res = await runner.run_process(
                [o.docker_bin, "image", "inspect", o.docker_image, "--format", "{{.Id}}"], timeout=30
            )
            if res.returncode != 0:
                raise ConnectorUnavailableError(
                    f"Docker image '{o.docker_image}' not found; build it with `just synthea-build`"
                )
            key = res.tail[-1].strip() if res.tail else o.docker_image
        else:
            jar = _abs(o.jar_path)
            if not jar.is_file():
                raise ConnectorUnavailableError(f"Synthea jar not found at {jar}")
            key = f"{jar.name}-{int(jar.stat().st_mtime)}"
        key = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:80]
        memory_key = f"{name}-{key}"
        if memory_key in _INDEX_CACHE:
            return _INDEX_CACHE[memory_key]
        cache_file = _abs(o.cache_dir) / f"synthea-{name}-{key}.json"
        if cache_file.is_file():
            _INDEX_CACHE[memory_key] = json.loads(cache_file.read_text(encoding="utf-8"))
            return _INDEX_CACHE[memory_key]

        tmp = _abs(o.cache_dir) / f"tmp-{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            if o.mode == "docker":
                jar_path = tmp / "synthea.jar"
                name = f"fhirgen-terms-{uuid.uuid4().hex[:6]}"
                for cmd in (
                    [o.docker_bin, "create", "--name", name, o.docker_image],
                    [o.docker_bin, "cp", f"{name}:{DOCKER_JAR}", str(jar_path)],
                ):
                    res = await runner.run_process(cmd, timeout=300)
                    if res.returncode != 0:
                        await runner.run_process([o.docker_bin, "rm", "-f", name], timeout=30)
                        raise GenerationFailedError("Could not read the Synthea jar from the image", details=res.tail[-5:])
                await runner.run_process([o.docker_bin, "rm", "-f", name], timeout=30)
            else:
                jar_path = _abs(o.jar_path)
            index = await asyncio.to_thread(build, jar_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(index), encoding="utf-8")
        _INDEX_CACHE[memory_key] = index
        return index

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            native_filters={
                "count", "seed", "gender", "age_range", "state", "city",
                "years_of_history", "only_alive", "specialty", "conditions", "procedures", "medications", "match", "within",
            },  # fmt: skip
            fhir_versions={"R4"},
            deterministic=True,
        )

    # ── health ───────────────────────────────────────────────────────────
    async def healthcheck(self) -> HealthStatus:
        o = self.options
        if o.mode == "docker":
            try:
                res = await runner.run_process(
                    [o.docker_bin, "image", "inspect", o.docker_image, "--format", "{{.Id}}"], timeout=30
                )
            except FileNotFoundError:
                return HealthStatus(False, f"'{o.docker_bin}' not found on PATH; install Docker or use mode: local")
            except Exception as exc:  # noqa: BLE001
                return HealthStatus(False, f"Could not run docker: {exc}")
            if res.returncode != 0:
                detail = " ".join(res.tail)
                if "daemon" in detail.lower() or "connect" in detail.lower():
                    return HealthStatus(False, f"Docker daemon is not reachable: {detail[:200]}")
                return HealthStatus(
                    False,
                    f"Docker image '{o.docker_image}' not found. Build it with `just synthea-build` "
                    "(docker build -t fhir-gen-synthea:4.0.0 docker/synthea)",
                )
            return HealthStatus(True, f"docker image {o.docker_image} present")

        jar = _abs(o.jar_path)
        if not jar.is_file():
            return HealthStatus(False, f"Synthea jar not found at {jar}")
        try:
            res = await runner.run_process([o.java_bin, "-version"], timeout=30)
        except FileNotFoundError:
            return HealthStatus(False, f"'{o.java_bin}' not found; install a JDK 17+ or use mode: docker")
        return HealthStatus(res.returncode == 0, f"java ok, jar {jar.name}" if res.returncode == 0 else "java failed")

    # ── generation ───────────────────────────────────────────────────────
    async def generate(self, cohort: CohortSpec, workdir: Path) -> RawOutput:
        o = self.options
        workdir = workdir.resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        docker = o.mode == "docker"

        if cohort.state or cohort.city:
            # Synthea matches names exactly and dies late with a stack trace on a miss: fix the capitalisation
            # ("worcester" -> "Worcester") or fail now with suggestions.
            state, city = places_index.resolve_place(
                await self._place_index(), cohort.state or o.default_state, cohort.city
            )
            cohort = cohort.model_copy(update={"state": state, "city": city})

        has_keep =bool(cohort.conditions or cohort.procedures or cohort.medications)
        if has_keep:
            (workdir / flags.KEEP_MODULE_FILE).write_text(
                json.dumps(flags.build_keep_module(
                    cohort.conditions, cohort.procedures, cohort.match, cohort.within, cohort.medications
                ), indent=2), encoding="utf-8"
            )

        modules_host = _abs(o.modules_dir) if o.modules_dir else None
        if modules_host is not None and not modules_host.is_dir():
            raise ConnectorUnavailableError(f"modules_dir does not exist: {modules_host}")

        reference_date = o.reference_date or date.today().strftime("%Y%m%d")
        end_date = o.end_date or o.reference_date  # None => Synthea default (today); see SyntheaOptions.end_date
        base_seed = cohort.seed if cohort.seed is not None else 0
        attempts = 1 + o.retries_on_timeout
        for attempt in range(attempts):
            seed_used = base_seed + attempt * RETRY_SEED_STEP
            run_cohort = cohort if attempt == 0 else cohort.model_copy(update={"seed": seed_used})
            if attempt:  # a stalled run leaves partial output behind
                shutil.rmtree(workdir / "output", ignore_errors=True)
            java_args = flags.build_synthea_args(
                run_cohort,
                reference_date=reference_date,
                end_date=end_date,
                default_state=o.default_state,
                # A keep module judges the patient's WHOLE life, but only the last N years are exported: a patient
                # kept for an appendectomy 25 years ago would have no appendectomy in the record (observed). So
                # procedure-targeted cohorts export full history (0) unless the request sets it explicitly.
                years_of_history=0 if cohort.procedures else o.years_of_history,
                properties={**DEFAULT_PROPERTIES, **o.properties},
                work=flags.DOCKER_WORK if docker else workdir.as_posix(),
                has_keep_module=has_keep,
                modules_path=(
                    None if modules_host is None else (flags.DOCKER_MODULES if docker else modules_host.as_posix())
                ),
                jar=DOCKER_JAR if docker else _abs(o.jar_path).as_posix(),
                jvm_args=o.jvm_args,
            )

            on_timeout = None
            if docker:
                name = f"fhirgen-{workdir.name}-{uuid.uuid4().hex[:6]}"
                user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None
                cmd = runner.docker_run_command(
                    docker_bin=o.docker_bin,
                    image=o.docker_image,
                    container_name=name,
                    workdir=workdir,
                    modules_dir=modules_host,
                    user=user,
                    java_args=java_args,
                )
                on_timeout = [o.docker_bin, "kill", name]
            else:
                cmd = [o.java_bin, *java_args]

            try:
                result = await runner.run_process(cmd, timeout=o.timeout_seconds, on_timeout=on_timeout)
            except FileNotFoundError as exc:
                raise ConnectorUnavailableError(f"Cannot execute '{cmd[0]}': {exc}") from exc

            tail = [line for line in result.tail if line.strip()][-25:]
            if result.timed_out and attempt < attempts - 1:
                continue  # stalled: try again with the next derived seed
            if result.timed_out:
                raise GenerationFailedError(
                    f"Synthea timed out after {o.timeout_seconds}s"
                    + (f" on each of {attempts} attempts" if attempts > 1 else ""),
                    details=tail,
                )
            break
        if result.returncode != 0:
            hint = ""
            if docker and result.returncode == 125:
                hint = f" (is the image '{o.docker_image}' built and the Docker daemon running?)"
            raise GenerationFailedError(
                f"Synthea exited with code {result.returncode}{hint}", details=tail
            )

        out_dir = workdir / "output"
        files = output.patient_files(out_dir)
        if not files:
            oom = any("OutOfMemoryError" in line for line in result.tail)
            raise GenerationFailedError(
                "Synthea produced no patient records"
                + (" (out of memory: raise -Xmx in jvm_args)" if oom else ""),
                details=tail,
            )

        if len(files) < cohort.count:
            problem = next((line for line in result.tail if "Failed to produce" in line), None)
            raise UnsatisfiableCohortError(
                f"Synthea produced {len(files)} of {cohort.count} requested patients"
                + (" (gave up finding matches for the requested conditions/demographics)" if problem else ""),
                details=([problem[:300]] if problem else tail)
                + ["Relax age_range/conditions, or raise generate.max_attempts_to_keep_patient in the connector properties"],
            )

        # `count` means exported patients: only_alive (default) already makes Synthea produce
        # exactly `count`; with only_alive=false deceased patients ride along on top.
        limit = None if cohort.only_alive is False else cohort.count
        metadata = output.read_metadata(out_dir)
        return RawOutput(
            patient_bundles=output.iter_patient_bundles(out_dir, limit),
            infra=output.read_infra(out_dir),
            meta={
                "connector": "synthea",
                "mode": o.mode,
                "image": o.docker_image if docker else None,
                # As reported by the jar itself (a git-describe string, e.g. the v4.0.0 release says
                # "v3.4.0-18-g..."), so it is recorded verbatim, not assumed to equal the release tag.
                "synthea_version": str(metadata.get("version") or "").strip() or None,
                "java_version": metadata.get("javaVersion"),
                "seed": cohort.seed,
                "seed_used": seed_used,  # differs from `seed` only when a stalled run was retried
                "retried_after_timeout": attempt > 0,
                "reference_date": reference_date,
                "end_date": end_date,
                "state": cohort.state or o.default_state,
                "keep_conditions": cohort.conditions or None,
                "keep_procedures": cohort.procedures or None,
                "keep_medications": cohort.medications or None,
                "records_exported_by_synthea": len(files),
                "synthea_args": [a for a in java_args if a.startswith(("-p", "-s", "-g", "-a", "--"))],
            },
        )
