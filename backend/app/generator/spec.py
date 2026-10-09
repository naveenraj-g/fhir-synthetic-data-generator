"""Request/spec models. A GenerationRequest is what a caller submits (everything
optional, may name a preset); resolving it against config yields a ResolvedSpec
(everything concrete). See plan/03-scenarios-and-slicing.md."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CohortSpec(BaseModel):
    """Who gets generated."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(1, ge=1, description="Number of patients to export")
    seed: int | None = Field(None, description="Reproducibility seed; random if omitted (and recorded)")
    gender: Literal["M", "F"] | None = None
    age_range: tuple[int, int] | None = Field(None, description="[min, max] age in years")
    state: str | None = None
    city: str | None = None
    specialty: str | None = Field(None, description="Name of a specialty defined in the connectors config")
    conditions: list[str] = Field(
        default_factory=list, description="Codes of conditions; the patient must have ANY of them"
    )
    procedures: list[str] = Field(
        default_factory=list,
        description="Codes of procedures; the patient must have had ANY of them (combined with conditions by AND)",
    )
    match: Literal["all", "any"] = Field(
        "all",
        description="How conditions and procedures combine: 'all' = the patient needs a matching condition AND a "
        "matching procedure; 'any' = either one is enough (e.g. a specialty: has the disease OR had the operation)",
    )
    medications: list[str] = Field(
        default_factory=list,
        description="RxNorm codes of medications the patient is CURRENTLY taking at the end of the simulated period "
        "(combined with conditions/procedures by `match`). Find codes with the term search",
    )
    within: Literal["any", "all"] = Field(
        "any",
        description="How the codes inside conditions (and inside procedures) combine: 'any' = at least one of them; "
        "'all' = every one of them (comorbidity, e.g. diabetes AND hypertension)",
    )
    years_of_history: int | None = Field(None, ge=0)
    only_alive: bool | None = None

    @model_validator(mode="after")
    def _check_age_range(self) -> "CohortSpec":
        if self.age_range and self.age_range[0] > self.age_range[1]:
            raise ValueError("age_range must be [min, max] with min <= max")
        return self


class CohortOverrides(CohortSpec):
    """Same fields as CohortSpec, but nothing is defaulted so 'not supplied' can be
    told apart from 'supplied as the default' when merging over a preset."""

    count: int | None = Field(None, ge=1)  # type: ignore[assignment]
    conditions: list[str] | None = None  # type: ignore[assignment]
    procedures: list[str] | None = None  # type: ignore[assignment]
    medications: list[str] | None = None  # type: ignore[assignment]
    match: Literal["all", "any"] | None = None  # type: ignore[assignment]
    within: Literal["any", "all"] | None = None  # type: ignore[assignment]


class ShapeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slicer: str
    params: dict[str, Any] = Field(default_factory=dict)


class SinkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class GenerationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_references: bool = Field(
        False, description="Fail the job if the output contains references that do not resolve"
    )


class GenerationRequest(BaseModel):
    """What the API accepts. Every field is optional: give a preset, or a full spec, or a preset + overrides."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "preset": "full-patient",
                "cohort": {"count": 2, "seed": 42},
            }
        },
    )

    preset: str | None = None
    connector: str | None = None
    cohort: CohortOverrides | None = None
    shape: list[ShapeStep] | None = None
    sink: SinkSpec | None = None
    options: GenerationOptions | None = None
    connector_params: dict[str, Any] | None = Field(
        None,
        description="Per-request overrides the connector explicitly allows (Synthea: reference_date, end_date, and "
        "a safe subset of properties such as exporter.fhir.use_us_core_ig). Anything else is rejected.",
    )


class ResolvedSpec(BaseModel):
    """Fully concrete: nothing left to look up in config except component options."""

    connector: str
    cohort: CohortSpec
    shape: list[ShapeStep]
    sink: SinkSpec
    options: GenerationOptions = Field(default_factory=GenerationOptions)
    connector_params: dict[str, Any] = Field(default_factory=dict)
    preset: str | None = None
    warnings: list[str] = Field(default_factory=list)
