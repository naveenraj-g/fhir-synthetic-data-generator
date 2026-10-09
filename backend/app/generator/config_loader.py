"""Loads configs/synthetic_data_connectors.yaml into plain dicts, expands
${ENV_VAR} references, and validates the *envelope* (not each component's own
options — those are validated by the component that owns them)."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.generator.errors import ConfigError, InvalidSpecError
from app.generator.spec import ShapeStep, SinkSpec

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_max_patients: int = 5
    max_patients_per_job: int = 5000
    inline_max_bytes: int = 5_000_000
    max_concurrent_jobs: int = 2
    artifact_ttl_hours: int = 72
    cleanup_interval_minutes: int = 15


class PresetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, description="Human name; the key is used when omitted")
    category: str | None = Field(None, description="Group shown in the UI, e.g. 'Gastroenterology'")
    description: str = ""
    connector: str | None = None
    cohort: dict[str, Any] = Field(default_factory=dict)
    shape: list[ShapeStep] | None = None
    sink: SinkSpec | None = None


def _expand(node: Any, env: Mapping[str, str], path: str, problems: list[str]) -> Any:
    if isinstance(node, str):

        def repl(match: re.Match) -> str:
            name, default = match.group(1), match.group(2)
            if name in env:
                return env[name]
            if default is not None:
                return default
            problems.append(f"{path}: environment variable '{name}' is not set")
            return match.group(0)

        return _ENV_PATTERN.sub(repl, node)
    if isinstance(node, dict):
        return {k: _expand(v, env, f"{path}.{k}", problems) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand(v, env, f"{path}[{i}]", problems) for i, v in enumerate(node)]
    return node


@dataclass(frozen=True)
class GeneratorConfig:
    raw: dict[str, Any]
    limits: Limits
    default_connector: str
    fhir_version: str
    connectors: dict[str, dict[str, Any]]
    slicer_defaults: dict[str, dict[str, Any]]
    sinks: dict[str, dict[str, Any]]
    specialties: dict[str, dict[str, Any]]
    presets: dict[str, PresetConfig] = field(default_factory=dict)

    def connector_entry(self, name: str) -> dict[str, Any]:
        entry = self.connectors.get(name)
        if entry is None:
            raise InvalidSpecError(f"Unknown connector '{name}'. Configured: {sorted(self.connectors)}")
        if not entry.get("enabled", True):
            raise InvalidSpecError(f"Connector '{name}' is disabled in configuration")
        return entry

    def connector_options(self, name: str) -> dict[str, Any]:
        return dict(self.connector_entry(name).get("options") or {})

    def preset(self, name: str) -> PresetConfig:
        preset = self.presets.get(name)
        if preset is None:
            raise InvalidSpecError(f"Unknown preset '{name}'. Available: {sorted(self.presets)}")
        return preset

    def specialty(self, name: str) -> dict[str, Any]:
        spec = self.specialties.get(name)
        if spec is None:
            raise InvalidSpecError(f"Unknown specialty '{name}'. Available: {sorted(self.specialties)}")
        return spec


def load_config(
    path: Path,
    *,
    env: Mapping[str, str] | None = None,
    known_connector_types: set[str] | None = None,
    known_slicers: set[str] | None = None,
) -> GeneratorConfig:
    """Raises ConfigError listing *all* problems found, not just the first."""
    env = os.environ if env is None else env
    problems: list[str] = []

    try:
        # Explicit UTF-8: the platform default (cp1252 on Windows) chokes on non-ASCII.
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"Generator config not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"Generator config is not valid YAML: {exc}") from None

    if not isinstance(raw, dict):
        raise ConfigError("Generator config must be a YAML mapping at the top level")

    # Entries explicitly disabled are not expanded/validated: they often reference
    # env vars (tokens, URLs) that only exist in the environments that enable them.
    def expand_section(section: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, entry in (raw.get(section) or {}).items():
            if isinstance(entry, dict) and entry.get("enabled", True) is False:
                out[name] = entry
            else:
                out[name] = _expand(entry, env, f"{section}.{name}", problems)
        return out

    connectors = expand_section("connectors")
    sinks = expand_section("sinks")
    slicer_defaults = _expand(raw.get("slicers") or {}, env, "slicers", problems)
    specialties = _expand(raw.get("specialties") or {}, env, "specialties", problems)

    defaults = raw.get("defaults") or {}
    try:
        limits = Limits(**(defaults.get("limits") or {}))
    except ValidationError as exc:
        problems.append(f"defaults.limits: {exc}")
        limits = Limits()

    default_connector = defaults.get("connector", "")
    if default_connector not in connectors:
        problems.append(f"defaults.connector '{default_connector}' is not a configured connector")
    elif connectors[default_connector].get("enabled", True) is False:
        problems.append(f"defaults.connector '{default_connector}' is disabled")

    for name, entry in connectors.items():
        if not isinstance(entry, dict) or "type" not in entry:
            problems.append(f"connectors.{name}: missing 'type'")
        elif (
            entry.get("enabled", True)
            and known_connector_types is not None
            and entry["type"] not in known_connector_types
        ):
            problems.append(
                f"connectors.{name}: unknown type '{entry['type']}' (known: {sorted(known_connector_types)})"
            )

    for name, entry in sinks.items():
        if not isinstance(entry, dict) or "type" not in entry:
            problems.append(f"sinks.{name}: missing 'type'")

    presets: dict[str, PresetConfig] = {}
    for name, entry in (raw.get("presets") or {}).items():
        try:
            preset = PresetConfig(**(entry or {}))
        except ValidationError as exc:
            problems.append(f"presets.{name}: {exc}")
            continue
        if preset.connector and preset.connector not in connectors:
            problems.append(f"presets.{name}: unknown connector '{preset.connector}'")
        if preset.sink and preset.sink.name not in sinks:
            problems.append(f"presets.{name}: unknown sink '{preset.sink.name}'")
        for step in preset.shape or []:
            if known_slicers is not None and step.slicer not in known_slicers:
                problems.append(f"presets.{name}: unknown slicer '{step.slicer}'")
        specialty = preset.cohort.get("specialty")
        if specialty and specialty not in specialties:
            problems.append(f"presets.{name}: unknown specialty '{specialty}'")
        presets[name] = preset

    if problems:
        raise ConfigError(
            f"Invalid generator config ({len(problems)} problem(s))", details=problems
        )

    return GeneratorConfig(
        raw=raw,
        limits=limits,
        default_connector=default_connector,
        fhir_version=str(defaults.get("fhir_version", "R4")),
        connectors=connectors,
        slicer_defaults=slicer_defaults,
        sinks=sinks,
        specialties=specialties,
        presets=presets,
    )
