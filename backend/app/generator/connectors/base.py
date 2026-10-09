from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from app.generator.errors import ConfigError, InvalidSpecError
from app.generator.spec import CohortSpec


class ConnectorCapabilities(BaseModel):
    """Which CohortSpec fields the connector honours natively. Anything else the
    caller sets is either enforced by a slicer or reported as a warning."""

    native_filters: set[str]
    fhir_versions: set[str] = {"R4"}
    deterministic: bool = True


@dataclass
class RawOutput:
    patient_bundles: Iterable[dict]
    infra: dict[str, dict] = field(default_factory=dict)  # hospital/practitioner bundles by name
    meta: dict[str, Any] = field(default_factory=dict)  # provenance


@dataclass
class HealthStatus:
    ok: bool
    detail: str = ""


class ConnectorOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Connector(ABC):
    name: ClassVar[str]
    Options: ClassVar[type[ConnectorOptions]] = ConnectorOptions
    # What a single REQUEST may override (a deliberately small subset of Options). None = nothing.
    RequestParams: ClassVar[type[BaseModel] | None] = None

    def __init__(self, options: dict[str, Any]):
        # `options` is the plain dict from the config file; the connector owns its validation.
        try:
            self.options = self.Options(**options)
        except ValidationError as exc:
            raise ConfigError(
                f"Invalid options for connector '{self.name}'",
                details=[f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()],
            ) from None

    def with_request_params(self, params: dict[str, Any]) -> "Connector":
        """A connector configured for one request: config options + the overrides this connector allows.
        Unknown or forbidden keys are rejected (callers must never reach paths, images or JVM flags)."""
        if not params:
            return self
        if self.RequestParams is None:
            raise InvalidSpecError(f"Connector '{self.name}' does not accept per-request connector_params")
        try:
            allowed = self.RequestParams(**params).model_dump(exclude_unset=True)
        except ValidationError as exc:
            raise InvalidSpecError(
                f"Invalid connector_params for '{self.name}'",
                details=[{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()],
            ) from None
        return type(self)(self._merge_request_params(self.options.model_dump(), allowed))

    def _merge_request_params(self, options: dict[str, Any], allowed: dict[str, Any]) -> dict[str, Any]:
        return {**options, **allowed}

    async def terms(self, q: str | None, kind: str | None, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Searchable clinical terms (conditions, procedures, ...) this connector can target. Optional."""
        raise InvalidSpecError(f"Connector '{self.name}' does not provide a term index")

    async def places(self, state: str | None) -> list[str]:
        """Valid state names, or the valid city names of `state`. Optional."""
        raise InvalidSpecError(f"Connector '{self.name}' does not provide a list of places")

    @abstractmethod
    def capabilities(self) -> ConnectorCapabilities: ...

    @abstractmethod
    async def generate(self, cohort: CohortSpec, workdir: Path) -> RawOutput: ...

    async def healthcheck(self) -> HealthStatus:
        return HealthStatus(ok=True)
