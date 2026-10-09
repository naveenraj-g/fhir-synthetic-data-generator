"""Basic slicers: full_record, resource_types, resource_filter, infrastructure, limit, redact_infra.
Episode-based ones (encounter, date_window, condition_*) live in episodes.py.

Every slicer that drops resources goes through reference_closure.filter_entries, which also removes the references
that pointed at what was dropped, so output never has dangling local references."""

from collections.abc import Iterable, Iterator
from itertools import islice

from pydantic import Field, model_validator

from app.generator import fhir
from app.generator.codes import compile_patterns, matches_any
from app.generator.registry import slicers
from app.generator.resource_groups import GROUPS, INFRASTRUCTURE_TYPES, expand_groups
from app.generator.slicers.base import SliceContext, Slicer, SlicerParams
from app.generator.slicers.reference_closure import attach_infrastructure, filter_entries


# ── full_record ──────────────────────────────────────────────────────────
class FullRecordParams(SlicerParams):
    include_infrastructure: bool = Field(
        False,
        description="Append the practitioner/organization/location resources each patient's "
        "conditional references (Type?identifier=...) point at, so the bundle is self-contained",
    )


@slicers.register("full_record")
class FullRecordSlicer(Slicer):
    description = "Entire patient record as emitted by the connector (optionally self-contained)."
    Params = FullRecordParams
    params: FullRecordParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        if not self.params.include_infrastructure:
            yield from bundles
            return
        for bundle in bundles:
            yield attach_infrastructure(bundle, ctx.infra)


# ── resource_types ───────────────────────────────────────────────────────
class ResourceTypesParams(SlicerParams):
    types: list[str] = Field(default_factory=list, description="FHIR resource types to keep, e.g. ['Observation']")
    groups: list[str] = Field(
        default_factory=list,
        description=f"Named categories of resource types: {', '.join(sorted(GROUPS))}",
    )
    exclude_types: list[str] = Field(default_factory=list, description="Types to remove from the selection")
    keep_patient: bool = Field(True, description="Keep the Patient resource so references do not dangle")
    include_infrastructure: bool = Field(
        False,
        description="Also attach the practitioners/organizations/locations the kept resources refer to, so the "
        "result is self-contained (Synthea refers to providers by identifier, not by id)",
    )

    @model_validator(mode="after")
    def _need_a_selection(self) -> "ResourceTypesParams":
        if not self.types and not self.groups:
            raise ValueError("give at least one of 'types' or 'groups'")
        expand_groups(self.groups)  # raises InvalidSpecError for unknown group names
        return self


@slicers.register("resource_types")
class ResourceTypesSlicer(Slicer):
    description = (
        "Keep only the chosen resource types and/or named groups (clinical, financial, administrative, ...). "
        "Asking for administrative types (Practitioner, Organization, Location) pulls them in from the "
        "connector's infrastructure data automatically."
    )
    Params = ResourceTypesParams
    params: ResourceTypesParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        p = self.params
        wanted = (set(p.types) | expand_groups(p.groups)) - set(p.exclude_types)
        keep = wanted | ({"Patient"} if p.keep_patient else set())
        needs_infra = bool(wanted & INFRASTRUCTURE_TYPES)
        for bundle in bundles:
            if needs_infra:
                bundle = attach_infrastructure(bundle, ctx.infra)
            # A bundle holding nothing but the Patient anchor contributes nothing: skip it.
            if not any(fhir.resource_type(r) in wanted for r in fhir.resources(bundle)):
                continue
            kept = filter_entries(bundle, lambda r: fhir.resource_type(r) in keep)
            if p.include_infrastructure:
                # After filtering: only providers the survivors need. Also when provider types were asked for, because
                # that pre-filter attach keeps just the types asked for (e.g. Practitioner) and a kept Claim may still
                # point at an Organization.
                kept = attach_infrastructure(kept, ctx.infra)
            yield kept


# ── resource_filter ──────────────────────────────────────────────────────
def _category_codes(resource: dict) -> set[str]:
    cats = resource.get("category")
    if isinstance(cats, dict):
        cats = [cats]
    return {c.get("code", "") for cc in (cats or []) for c in cc.get("coding", [])}


class ResourceFilterParams(SlicerParams):
    resource_type: str = Field(
        description="The type this filter applies to, e.g. 'Observation'. Other types are untouched"
    )
    categories: list[str] | None = Field(
        None,
        description="Match resource.category codes, e.g. Observation: vital-signs, laboratory, survey, "
        "social-history, imaging, exam; Condition: encounter-diagnosis, problem-list-item",
    )
    codes: list[str] | None = Field(
        None, description="Match resource.code by code ('LOINC:8867-4') or text ('heart rate')"
    )
    status: list[str] | None = Field(None, description="Match resource.status, e.g. ['final']")
    exclude: bool = Field(False, description="Invert: DROP the resources that match instead of keeping them")

    @model_validator(mode="after")
    def _need_a_criterion(self) -> "ResourceFilterParams":
        if not (self.categories or self.codes or self.status):
            raise ValueError("give at least one of categories, codes, status")
        return self


@slicers.register("resource_filter")
class ResourceFilterSlicer(Slicer):
    description = (
        "Fine filter on one resource type by category, code/text or status - e.g. vital signs only, or "
        "everything except laboratory results. All given criteria must match."
    )
    Params = ResourceFilterParams
    params: ResourceFilterParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        p = self.params
        patterns = compile_patterns(p.codes) if p.codes else None

        def matches(res: dict) -> bool:
            if p.categories and not (set(p.categories) & _category_codes(res)):
                return False
            if patterns and not matches_any(res.get("code"), patterns):
                return False
            return not (p.status and res.get("status") not in p.status)

        def keep(res: dict) -> bool:
            if fhir.resource_type(res) != p.resource_type:
                return True
            return not matches(res) if p.exclude else matches(res)

        for bundle in bundles:
            yield filter_entries(bundle, keep)


# ── infrastructure ───────────────────────────────────────────────────────
class InfrastructureParams(SlicerParams):
    types: list[str] | None = Field(
        None, description="Limit to these types (Practitioner, Organization, Location); default all"
    )


@slicers.register("infrastructure")
class InfrastructureSlicer(Slicer):
    description = (
        "ADMINISTRATIVE data only: the providers, organizations and locations the connector produced - no patient "
        "records. Emits one bundle. (Use a small cohort.count; patients are still generated and then discarded.)"
    )
    Params = InfrastructureParams
    params: InfrastructureParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        wanted = set(self.params.types) if self.params.types else None
        seen: set[str] = set()
        entries: list[dict] = []
        for name in sorted(ctx.infra):
            for entry in fhir.entries(ctx.infra[name]):
                res = entry.get("resource") or {}
                if wanted is not None and fhir.resource_type(res) not in wanted:
                    continue
                key = entry.get("fullUrl") or f"{fhir.resource_type(res)}/{res.get('id')}"
                if key not in seen:
                    seen.add(key)
                    entries.append(entry)
        if entries:
            yield fhir.make_bundle(entries, "collection")


# ── limit / redact_infra ─────────────────────────────────────────────────
class LimitParams(SlicerParams):
    max_bundles: int | None = Field(None, ge=1)
    max_resources_per_bundle: int | None = Field(None, ge=1)


@slicers.register("limit")
class LimitSlicer(Slicer):
    description = "Truncate output: cap the number of bundles and/or resources per bundle."
    Params = LimitParams
    params: LimitParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        cap = self.params.max_resources_per_bundle
        for bundle in islice(bundles, self.params.max_bundles):
            if cap is None:
                yield bundle
                continue
            first = {id(e["resource"]) for e in fhir.entries(bundle)[:cap] if e.get("resource")}
            yield filter_entries(bundle, lambda r, first=first: id(r) in first)


class RedactInfraParams(SlicerParams):
    drop_types: list[str] = Field(
        default_factory=lambda: ["Claim", "ClaimResponse", "ExplanationOfBenefit"],
        description="Resource types to drop (billing/administrative noise by default)",
    )


@slicers.register("redact_infra")
class RedactInfraSlicer(Slicer):
    description = "Drop billing resources (Claim, ExplanationOfBenefit...) - or any types you list."
    Params = RedactInfraParams
    params: RedactInfraParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        drop = set(self.params.drop_types)
        for bundle in bundles:
            yield filter_entries(bundle, lambda r: fhir.resource_type(r) not in drop)
