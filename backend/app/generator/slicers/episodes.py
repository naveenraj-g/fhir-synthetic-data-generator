"""Phase-3 slicers: encounter, date_window, condition_scoped, condition_filter.
All build on slicers/reference_closure.py (episode extraction with no dangling references)."""

import random
from collections.abc import Iterable, Iterator
from datetime import date, timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.generator import fhir
from app.generator.codes import compile_patterns, matches_any
from app.generator.registry import slicers
from app.generator.slicers import reference_closure as rc
from app.generator.slicers.base import SliceContext, Slicer, SlicerParams


def _finish(bundle: dict, ctx: SliceContext, include_infrastructure: bool) -> dict:
    return rc.attach_infrastructure(bundle, ctx.infra) if include_infrastructure else bundle


def _patterns(texts: list[str] | None):
    return compile_patterns(texts) if texts else None


# ── encounter ────────────────────────────────────────────────────────────
class EncounterParams(SlicerParams):
    selector: Literal["first", "latest", "random", "all"] = Field(
        "latest", description="Which of the matching encounters to take"
    )
    per_patient: int = Field(1, ge=1, description="How many episodes to emit per patient (one bundle each)")
    encounter_class: list[str] | None = Field(
        None, description="Encounter.class codes, any of: AMB (outpatient), IMP (inpatient), EMER (emergency)"
    )
    encounter_type: list[str] | None = Field(
        None,
        description="Only encounters of these kinds (ANY): the visit's own type, by text or code, e.g. "
        "'General examination of patient' or 'check up' for wellness visits",
    )
    with_procedure: list[str] | None = Field(
        None, description="Only encounters in which ANY of these procedures was performed (code or text)"
    )
    with_condition: list[str] | None = Field(
        None, description="Only encounters in which ANY of these conditions was recorded (code or text)"
    )
    related_conditions: bool = Field(
        True, description="Also include Conditions the episode refers to (e.g. as the reason for a medication)"
    )
    include_infrastructure: bool = Field(
        True, description="Append the practitioners/organizations/locations the episode references"
    )
    random_seed: int = 0


@slicers.register("encounter")
class EncounterSlicer(Slicer):
    description = (
        "One bundle per selected encounter: the encounter plus everything that belongs to it "
        "(procedures, observations, medications, claims...) and the Patient, with no dangling references."
    )
    Params = EncounterParams
    params: EncounterParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        p = self.params
        classes = {c.upper() for c in p.encounter_class or []}
        procedures, conditions = _patterns(p.with_procedure), _patterns(p.with_condition)
        types = _patterns(p.encounter_type)
        for bundle in bundles:
            index = rc.build_index(bundle)
            candidates = []
            for enc in index.encounter_idxs:
                if classes and (index.resource(enc).get("class") or {}).get("code", "").upper() not in classes:
                    continue
                if types and not any(matches_any(t, types) for t in index.resource(enc).get("type") or []):
                    continue
                members = [index.resource(i) for i, b in enumerate(index.bindings) if b == {enc}]
                if procedures and not any(
                    r["resourceType"] == "Procedure" and matches_any(r.get("code"), procedures) for r in members
                ):
                    continue
                if conditions and not any(
                    r["resourceType"] == "Condition" and matches_any(r.get("code"), conditions) for r in members
                ):
                    continue
                candidates.append(enc)

            ordered = rc.sort_encounters(index, candidates)
            if p.selector == "first":
                picked = ordered[: p.per_patient]
            elif p.selector == "latest":
                picked = ordered[-p.per_patient :]
            elif p.selector == "random":
                pid = next((r.get("id", "") for r in fhir.resources(bundle) if r["resourceType"] == "Patient"), "")
                rng = random.Random(f"{p.random_seed}:{pid}")
                picked = rc.sort_encounters(index, rng.sample(ordered, min(p.per_patient, len(ordered))))
            else:
                picked = ordered
            for enc in picked:
                episode = rc.extract(bundle, index, {enc}, related_conditions=p.related_conditions)
                yield _finish(episode, ctx, p.include_infrastructure)


# ── date_window ──────────────────────────────────────────────────────────
class DateWindowParams(SlicerParams):
    from_date: date | None = Field(None, description="Inclusive start, YYYY-MM-DD")
    to_date: date | None = Field(None, description="Inclusive end, YYYY-MM-DD")
    last_n_days: int | None = Field(
        None,
        ge=1,
        description="The N days up to the run's reference date (or, if the connector has none, up to the "
        "patient's latest encounter). Relative to data, never to today, so results stay reproducible.",
    )
    last_n_years: int | None = Field(
        None, ge=1, description="Like last_n_days but in calendar years (e.g. 5 = the past five years)"
    )
    include_infrastructure: bool = True

    @model_validator(mode="after")
    def _need_a_bound(self) -> "DateWindowParams":
        relative = [x for x in (self.last_n_days, self.last_n_years) if x is not None]
        if not relative and self.from_date is None and self.to_date is None:
            raise ValueError("give from_date and/or to_date, or last_n_days / last_n_years")
        if relative and (self.from_date or self.to_date):
            raise ValueError("use either last_n_days/last_n_years or from_date/to_date, not both")
        if len(relative) > 1:
            raise ValueError("use either last_n_days or last_n_years, not both")
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        return self


def _reference_date(ctx: SliceContext) -> date | None:
    raw = str(ctx.meta.get("reference_date") or "")
    if len(raw) == 8 and raw.isdigit():
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
    return None


@slicers.register("date_window")
class DateWindowSlicer(Slicer):
    description = (
        "Keep the encounters whose start date lies in a window, with everything belonging to them; "
        "undated-by-encounter resources are kept or dropped by their own clinical date."
    )
    Params = DateWindowParams
    params: DateWindowParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        p = self.params
        for bundle in bundles:
            index = rc.build_index(bundle)
            enc_dates = {e: rc.resource_date(index.resource(e)) for e in index.encounter_idxs}
            lo, hi = p.from_date, p.to_date
            if p.last_n_days is not None or p.last_n_years is not None:
                end = _reference_date(ctx)
                if end is None:
                    dated = [d for d in enc_dates.values() if d]
                    if not dated:
                        continue
                    end = date.fromisoformat(max(dated))
                hi = end
                if p.last_n_years is not None:
                    try:
                        lo = end.replace(year=end.year - p.last_n_years)
                    except ValueError:  # Feb 29 -> Feb 28
                        lo = end.replace(year=end.year - p.last_n_years, day=28)
                else:
                    lo = end - timedelta(days=p.last_n_days)
            lo_s, hi_s = lo.isoformat() if lo else "0000-01-01", hi.isoformat() if hi else "9999-12-31"

            chosen = {e for e, d in enc_dates.items() if d and lo_s <= d <= hi_s}
            if not chosen:
                continue

            def shared_in_window(res: dict) -> bool:
                d = rc.resource_date(res)
                return d is not None and lo_s <= d <= hi_s

            episode = rc.extract(bundle, index, chosen, keep_shared=shared_in_window)
            yield _finish(episode, ctx, p.include_infrastructure)


# ── condition_scoped ─────────────────────────────────────────────────────
class ConditionScopedParams(SlicerParams):
    conditions: list[str] = Field(min_length=1, description="Condition codes or text; ANY matches")
    include_infrastructure: bool = True


@slicers.register("condition_scoped")
class ConditionScopedSlicer(Slicer):
    description = (
        "The story of a condition: every encounter in which the condition was recorded or was the "
        "subject of a referring resource (e.g. its medication), with everything belonging to those "
        "encounters. One bundle per patient who has the condition."
    )
    Params = ConditionScopedParams
    params: ConditionScopedParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        patterns = compile_patterns(self.params.conditions)
        for bundle in bundles:
            index = rc.build_index(bundle)
            matching = {
                i
                for i, t in enumerate(index.rtypes)
                if t == "Condition" and matches_any(index.resource(i).get("code"), patterns)
            }
            if not matching:
                continue
            chosen: set[int] = set()
            for i, bound in enumerate(index.bindings):
                if len(bound) != 1:
                    continue  # shared or patient-wide resources say nothing about one episode
                if i in matching or matching.intersection(index.refs[i]):
                    chosen |= bound
            if not chosen:
                continue
            episode = rc.extract(bundle, index, chosen)
            yield _finish(episode, ctx, self.params.include_infrastructure)


# ── condition_filter ─────────────────────────────────────────────────────
class ConditionFilterParams(SlicerParams):
    conditions: list[str] = Field(min_length=1, description="Condition codes or text; ANY matches")
    active_only: bool = Field(False, description="Require clinicalStatus = active")


@slicers.register("condition_filter")
class ConditionFilterSlicer(Slicer):
    description = (
        "Keep only the patients (whole bundles) that have ANY of the conditions. Verification step for "
        "connectors that cannot filter natively."
    )
    Params = ConditionFilterParams
    params: ConditionFilterParams

    def apply(self, bundles: Iterable[dict], ctx: SliceContext) -> Iterator[dict]:
        patterns = compile_patterns(self.params.conditions)
        for bundle in bundles:
            for res in fhir.resources(bundle):
                if res["resourceType"] != "Condition" or not matches_any(res.get("code"), patterns):
                    continue
                if self.params.active_only:
                    status = [c.get("code") for c in (res.get("clinicalStatus") or {}).get("coding", [])]
                    if "active" not in status:
                        continue
                yield bundle
                break
