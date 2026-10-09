from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.generator.spec import ResolvedSpec


class ArtifactResponse(BaseModel):
    id: str
    filename: str
    size: int
    content_type: str
    download_url: str


class BundleSummary(BaseModel):
    index: int
    label: str  # the patient's name, or "Bundle N"
    resources: int
    by_type: dict[str, int]


class BundleIndexResponse(BaseModel):
    count: int
    items: list[BundleSummary]


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: Literal["queued", "running", "succeeded", "failed", "expired"]
    connector: str | None = None
    preset: str | None = None
    request: dict[str, Any]
    resolved_spec: dict[str, Any]
    provenance: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    artifacts: list[ArtifactResponse] = []
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None


class GenerationResultResponse(JobResponse):
    """Returned by POST /generations. `data` carries the bundles for inline sinks."""

    data: list[dict[str, Any]] | None = None


class PaginatedJobResponse(BaseModel):
    total: int
    limit: int
    offset: int
    data: list[JobResponse]


class PreviewResponse(BaseModel):
    resolved_spec: ResolvedSpec
    mode: Literal["sync", "async"]
    warnings: list[str]


class ComponentInfo(BaseModel):
    name: str
    description: str = ""
    params_schema: dict[str, Any] | None = None


class ConnectorInfo(BaseModel):
    name: str
    type: str
    enabled: bool
    native_filters: list[str] | None = None
    fhir_versions: list[str] | None = None
    deterministic: bool | None = None


class ConnectorHealthResponse(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class TermInfo(BaseModel):
    kind: str
    system: str
    code: str
    display: str
    modules: list[str]
    reference: str  # paste into cohort.conditions / cohort.procedures


class TermSearchResponse(BaseModel):
    total: int
    returned: int
    items: list[TermInfo]


class PlacesResponse(BaseModel):
    state: str | None = None  # None: `items` are state names; otherwise the city names of that state
    items: list[str]


class PresetInfo(BaseModel):
    name: str
    title: str | None = None
    category: str | None = None
    description: str = ""
    connector: str | None = None
    cohort: dict[str, Any] = {}
    shape: list[dict[str, Any]] | None = None
    sink: dict[str, Any] | None = None
