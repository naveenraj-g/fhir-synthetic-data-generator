import copy
import json

import pytest

import app.generator  # noqa: F401
from app.generator import fhir
from app.generator.codes import Pattern, compile_patterns, matches_any
from app.generator.connectors.static_fixtures import BACKEND_DIR
from app.generator.errors import InvalidSpecError, UnsatisfiableCohortError
from app.generator.runtime import GeneratorRuntime
from app.generator.slicers import reference_closure as rc
from app.generator.slicers.base import SliceContext
from app.generator.slicers.episodes import (
    ConditionFilterSlicer,
    ConditionScopedSlicer,
    DateWindowSlicer,
    EncounterSlicer,
)
from app.generator.spec import GenerationRequest

FIX = BACKEND_DIR / "fixtures" / "synthea_r4"
REAL = BACKEND_DIR / "tests" / "fixtures"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def p1():
    return load(FIX / "patient_001.json")


@pytest.fixture
def p2():
    return load(FIX / "patient_002.json")


@pytest.fixture
def ctx():
    infra = {k: load(FIX / f"{k}.json") for k in ("hospitalInformation", "practitionerInformation")}
    return SliceContext(infra=infra, meta={})


def types(bundle):
    return [r["resourceType"] for r in fhir.resources(bundle)]


def ids_of(bundle, rtype):
    return {r["id"] for r in fhir.resources(bundle) if r["resourceType"] == rtype}


def encounter_classes(bundle):
    return sorted(r["class"]["code"] for r in fhir.resources(bundle) if r["resourceType"] == "Encounter")


# ── code/text matching ────────────────────────────────────────────────────
def test_pattern_matching():
    concept = {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes mellitus type 2"}],
               "text": "Diabetes mellitus type 2"}  # fmt: skip
    assert Pattern("44054006").matches(concept)
    assert Pattern("SNOMED-CT:44054006").matches(concept)
    assert not Pattern("LOINC:44054006").matches(concept)  # right code, wrong system
    assert Pattern("diabetes").matches(concept) and Pattern("DIABETES MELLITUS").matches(concept)
    assert not Pattern("asthma").matches(concept) and not Pattern("44054006").matches(None)
    assert matches_any(concept, compile_patterns(["asthma", "44054006"]))
    with pytest.raises(InvalidSpecError):
        Pattern("  ")


# ── encounter ─────────────────────────────────────────────────────────────
def test_latest_encounter_is_the_er_visit_and_excludes_everything_else(p1, ctx):
    [episode] = list(EncounterSlicer({}).apply([p1], ctx))
    assert encounter_classes(episode) == ["EMER"]
    t = types(episode)
    assert "Patient" in t and t.count("Observation") == 1  # only the ER heart-rate reading
    assert "Provenance" not in t  # patient-wide: it references every encounter
    assert "SupplyDelivery" not in t and "Claim" not in t


def test_surgery_episode_by_procedure_text_is_self_contained(p1, ctx):
    [episode] = list(EncounterSlicer({"with_procedure": ["appendectomy"]}).apply([p1], ctx))
    assert encounter_classes(episode) == ["IMP"]
    t = types(episode)
    # members of the surgery encounter, via encounter / context.encounter[] / item[].encounter[]
    assert {"Procedure", "MedicationRequest", "DocumentReference", "Claim"} <= set(t)
    assert "Device" in t  # shared resource reached through Procedure.focalDevice
    assert "Practitioner" in t and "Organization" in t  # infrastructure attached
    assert "Provenance" not in t and "SupplyDelivery" not in t
    # the medication's reasonReference points at a Condition from ANOTHER encounter: pulled in...
    cond = next(r for r in fhir.resources(episode) if r["resourceType"] == "Condition")
    # ...but its own link to that other (excluded) encounter is removed, not left dangling
    assert "encounter" not in cond
    assert fhir.dangling_references(episode) == []


def test_related_conditions_can_be_turned_off(p1, ctx):
    [episode] = list(
        EncounterSlicer({"with_procedure": ["appendectomy"], "related_conditions": False}).apply([p1], ctx)
    )
    assert "Condition" not in types(episode)
    # the medication that referred to the excluded Condition lost that reference rather than dangling
    meds = [r for r in fhir.resources(episode) if r["resourceType"] == "MedicationRequest"]
    assert len(meds) == 1 and "reasonReference" not in meds[0]
    assert fhir.dangling_references(episode) == []


def test_input_bundle_is_not_mutated(p1, ctx):
    before = copy.deepcopy(p1)
    list(EncounterSlicer({"with_procedure": ["appendectomy"]}).apply([p1], ctx))
    assert p1 == before


def test_filters_by_class_and_selector(p1, ctx):
    amb = list(EncounterSlicer({"encounter_class": ["amb"], "selector": "all"}).apply([p1], ctx))
    assert [encounter_classes(b) for b in amb] == [["AMB"]]
    everything = list(EncounterSlicer({"selector": "all"}).apply([p1], ctx))
    assert sorted(c for b in everything for c in encounter_classes(b)) == ["AMB", "EMER", "IMP"]
    first = list(EncounterSlicer({"selector": "first"}).apply([p1], ctx))
    assert encounter_classes(first[0]) == ["AMB"]  # earliest by period.start
    two = list(EncounterSlicer({"selector": "latest", "per_patient": 2}).apply([p1], ctx))
    assert [encounter_classes(b) for b in two] == [["IMP"], ["EMER"]]


def test_random_selector_is_deterministic(p1, ctx):
    a = list(EncounterSlicer({"selector": "random", "random_seed": 4}).apply([p1], ctx))
    b = list(EncounterSlicer({"selector": "random", "random_seed": 4}).apply([p1], ctx))
    assert a == b


def test_patients_without_a_match_are_skipped(p1, p2, ctx):
    out = list(EncounterSlicer({"with_procedure": ["232717009"]}).apply([p1, p2], ctx))  # CABG: p2 only
    assert len(out) == 1
    assert {r["name"][0]["family"] for r in fhir.resources(out[0]) if r["resourceType"] == "Patient"} == {"Nguyen"}


def test_encounter_with_condition(p1, ctx):
    out = list(EncounterSlicer({"with_condition": ["hypertension"]}).apply([p1], ctx))
    assert encounter_classes(out[0]) == ["AMB"]


# ── date_window ───────────────────────────────────────────────────────────
def test_date_window_by_dates_keeps_dated_shared_resources_in_range(p1, ctx):
    [b] = list(DateWindowSlicer({"from_date": "2024-09-01", "to_date": "2024-09-30"}).apply([p1], ctx))
    assert encounter_classes(b) == ["IMP"]
    assert "SupplyDelivery" in types(b)  # not bound to an encounter, but dated 2024-09-11
    assert fhir.dangling_references(b) == []
    [b2] = list(DateWindowSlicer({"from_date": "2024-03-01", "to_date": "2024-03-31"}).apply([p1], ctx))
    assert encounter_classes(b2) == ["AMB"] and "SupplyDelivery" not in types(b2)


def test_date_window_last_n_days_is_relative_to_reference_date_not_today(p1, ctx):
    ctx.meta["reference_date"] = "20250201"
    [b] = list(DateWindowSlicer({"last_n_days": 30}).apply([p1], ctx))
    assert encounter_classes(b) == ["EMER"]
    # without a reference date it falls back to the patient's latest encounter (2025-01-20)
    [b2] = list(DateWindowSlicer({"last_n_days": 30}).apply([p1], SliceContext(infra=ctx.infra)))
    assert encounter_classes(b2) == ["EMER"]
    assert list(DateWindowSlicer({"from_date": "1990-01-01", "to_date": "1990-12-31"}).apply([p1], ctx)) == []


def test_date_window_param_validation():
    for bad in ({}, {"last_n_days": 5, "from_date": "2024-01-01"}, {"from_date": "2025-01-01", "to_date": "2024-01-01"}):
        with pytest.raises(InvalidSpecError):
            DateWindowSlicer(bad)


# ── condition_scoped / condition_filter ───────────────────────────────────
def test_condition_scoped_covers_every_encounter_the_condition_touches(p1, p2, ctx):
    out = list(ConditionScopedSlicer({"conditions": ["44054006"]}).apply([p1, p2], ctx))
    assert len(out) == 1  # p2 has no type 2 diabetes
    # recorded at the office visit AND the subject (reasonReference) of the surgery-stay medication
    assert encounter_classes(out[0]) == ["AMB", "IMP"]
    assert fhir.dangling_references(out[0]) == []


def test_condition_filter_keeps_whole_patients(p1, p2, ctx):
    assert list(ConditionFilterSlicer({"conditions": ["asthma"]}).apply([p1, p2], ctx)) == [p2]
    assert list(ConditionFilterSlicer({"conditions": ["no such thing"]}).apply([p1, p2], ctx)) == []
    assert len(list(ConditionFilterSlicer({"conditions": ["44054006"], "active_only": True}).apply([p1], ctx))) == 1


# ── prune ─────────────────────────────────────────────────────────────────
def test_prune_removes_references_and_empty_containers():
    res = {
        "resourceType": "Claim",
        "patient": {"reference": "urn:uuid:keep"},
        "item": [{"sequence": 1, "encounter": [{"reference": "urn:uuid:gone"}]}],
        "supportingInfo": [{"valueReference": {"reference": "urn:uuid:gone"}}],
    }
    out = rc.prune_references(res, {"urn:uuid:gone"})
    assert out == {"resourceType": "Claim", "patient": {"reference": "urn:uuid:keep"}, "item": [{"sequence": 1}]}
    assert "supportingInfo" not in out and res["item"][0]["encounter"]  # original untouched


# ── real Synthea data (trimmed) ───────────────────────────────────────────
@pytest.fixture(scope="module")
def real():
    bundle = load(REAL / "real_patient_trimmed.json")
    infra = {k: load(REAL / f"real_{k}.json") for k in ("hospitalInformation", "practitionerInformation")}
    return bundle, SliceContext(infra=infra, meta={})


def test_real_synthea_episodes_match_an_independent_computation(real):
    bundle, ctx = real
    enc_urls = [e["fullUrl"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Encounter"]
    assert len(enc_urls) == 5
    episodes = list(EncounterSlicer({"selector": "all", "related_conditions": False}).apply([bundle], ctx))
    assert len(episodes) == 5
    for episode, in zip(episodes):
        [enc] = [e for e in episode["entry"] if e["resource"]["resourceType"] == "Encounter"]
        url = enc["fullUrl"]
        others = [u for u in enc_urls if u != url]
        # independent, string-based: entries mentioning this encounter and no other encounter
        expected = {
            e["resource"]["id"]
            for e in bundle["entry"]
            if url in json.dumps(e["resource"]) and not any(o in json.dumps(e["resource"]) for o in others)
        }
        got = {e["resource"]["id"] for e in episode["entry"]}
        assert expected <= got, f"missing members: {expected - got}"
        assert "Provenance" not in types(episode)
        assert fhir.dangling_references(episode) == []
        assert len(episode["entry"]) < len(bundle["entry"])


def test_real_synthea_related_conditions_and_surgery_free_selection(real):
    bundle, ctx = real
    episodes = list(EncounterSlicer({"selector": "all"}).apply([bundle], ctx))
    assert all(fhir.dangling_references(e) == [] for e in episodes)
    # at least one episode pulls in a Condition recorded at a different encounter via reasonReference
    assert any(
        any(r["resourceType"] == "Condition" and "encounter" not in r for r in fhir.resources(e)) for e in episodes
    )


def test_real_synthea_date_window_and_condition_filter(real):
    bundle, ctx = real
    [w] = list(DateWindowSlicer({"from_date": "2000-01-01", "to_date": "2100-01-01"}).apply([bundle], ctx))
    assert len(ids_of(w, "Encounter")) == 5 and fhir.dangling_references(w) == []
    assert len(w["entry"]) <= len(bundle["entry"]) + 10  # + attached infrastructure only


# ── through the runtime ───────────────────────────────────────────────────
@pytest.fixture
def runtime():
    return GeneratorRuntime.from_path(BACKEND_DIR / "tests" / "connectors_test.yaml")


async def test_surgery_episode_through_the_pipeline(runtime, tmp_path):
    spec = runtime.resolve(
        GenerationRequest(
            cohort={"count": 2, "seed": 1},
            shape=[{"slicer": "encounter", "params": {"with_procedure": ["appendectomy"]}}],
            options={"check_references": True},
        )
    )
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    assert result.summary["bundles"] == 1  # fixtures alternate p1 (appendectomy) / p2 (CABG)
    assert result.summary["resources"]["Procedure"] == 1


async def test_empty_shape_result_is_an_error_not_an_empty_success(runtime, tmp_path):
    spec = runtime.resolve(
        GenerationRequest(shape=[{"slicer": "encounter", "params": {"with_procedure": ["no-such-procedure"]}}])
    )
    with pytest.raises(UnsatisfiableCohortError):
        await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")


# ── encounter_type (wellness visits etc.) ─────────────────────────────────
def test_encounter_type_filters_by_the_visits_own_type(p1, ctx):
    [b] = list(EncounterSlicer({"encounter_type": ["symptom"], "selector": "all"}).apply([p1], ctx))
    assert encounter_classes(b) == ["AMB"]  # "Encounter for symptom"
    assert [encounter_classes(x) for x in EncounterSlicer({"encounter_type": ["emergency room"], "selector": "all"}).apply([p1], ctx)] == [["EMER"]]
    assert list(EncounterSlicer({"encounter_type": ["nothing like this"]}).apply([p1], ctx)) == []
    # combines with other filters: the AMB visit is not a surgical admission
    assert list(EncounterSlicer({"encounter_type": ["symptom"], "with_procedure": ["appendectomy"]}).apply([p1], ctx)) == []


# ── shipped templates ─────────────────────────────────────────────────────
def test_every_shipped_template_resolves_and_is_categorised():
    from app.generator.connectors.static_fixtures import BACKEND_DIR

    runtime = GeneratorRuntime.from_path(BACKEND_DIR / "configs" / "synthetic_data_connectors.yaml")
    presets = runtime.config.presets
    cats = {p.category for p in presets.values()}
    assert {"General", "Gastroenterology", "Orthopedics", "Preventive health"} <= cats
    for name, preset in presets.items():
        assert preset.title and preset.description, f"{name} needs a title and a description"
        spec = runtime.resolve(GenerationRequest(preset=name))
        assert spec.warnings == [], f"{name}: {spec.warnings}"
    # the three groups the product was asked for each have several templates
    for cat in ("Gastroenterology", "Orthopedics", "Preventive health"):
        assert sum(1 for p in presets.values() if p.category == cat) >= 5
    # a procedure template really targets its operation, in the cohort AND in the slice it returns
    colo = runtime.resolve(GenerationRequest(preset="gastro-colonoscopy"))
    assert colo.cohort.procedures == ["73761001"]
    assert colo.shape[0].params["with_procedure"] == ["73761001"]
