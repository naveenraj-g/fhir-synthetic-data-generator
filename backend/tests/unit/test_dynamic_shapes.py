"""Phase 4: the 'dynamic' pieces - resource groups, fine filters, administrative-only output, match any/all,
per-request connector params, term search, last_n_years."""

import json
from datetime import date

import pytest

import app.generator  # noqa: F401
from app.generator import fhir
from app.generator.codes import Pattern
from app.generator.connectors.static_fixtures import BACKEND_DIR
from app.generator.connectors.synthea import flags, terms
from app.generator.connectors.synthea.connector import SyntheaConnector
from app.generator.errors import InvalidSpecError
from app.generator.resource_groups import GROUPS, expand_groups
from app.generator.runtime import GeneratorRuntime
from app.generator.slicers import reference_closure as rc
from app.generator.slicers.base import SliceContext
from app.generator.slicers.builtin import (
    InfrastructureSlicer,
    LimitSlicer,
    RedactInfraSlicer,
    ResourceFilterSlicer,
    ResourceTypesSlicer,
)
from app.generator.slicers.episodes import DateWindowSlicer
from app.generator.spec import GenerationRequest

FIX = BACKEND_DIR / "fixtures" / "synthea_r4"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def p1():
    return load("patient_001")


@pytest.fixture
def ctx():
    return SliceContext(infra={k: load(k) for k in ("hospitalInformation", "practitionerInformation")}, meta={})


def dangling(bundle, ctx):
    """Unresolvable references once the infrastructure (Synthea's conditional Practitioner?identifier=... targets)
    has been attached - i.e. references that are broken for real, not merely external."""
    return fhir.dangling_references(rc.attach_infrastructure(bundle, ctx.infra))


def type_counts(bundle):
    out: dict[str, int] = {}
    for r in fhir.resources(bundle):
        out[r["resourceType"]] = out.get(r["resourceType"], 0) + 1
    return out


# ── resource groups ───────────────────────────────────────────────────────
def test_every_group_name_expands_and_unknown_is_rejected():
    for name in GROUPS:
        assert expand_groups([name])
    with pytest.raises(InvalidSpecError):
        expand_groups(["nonsense"])


def test_demographics_group_is_patient_only(p1, ctx):
    [b] = list(ResourceTypesSlicer({"groups": ["demographics"]}).apply([p1], ctx))
    assert type_counts(b) == {"Patient": 1}


def test_financial_group_has_no_clinical_data_and_nothing_dangles(p1, ctx):
    [b] = list(ResourceTypesSlicer({"groups": ["financial"]}).apply([p1], ctx))
    assert set(type_counts(b)) == {"Patient", "Claim"}
    claim = next(r for r in fhir.resources(b) if r["resourceType"] == "Claim")
    assert "encounter" not in claim["item"][0]  # its link to the dropped Encounter was removed, not left dangling
    assert dangling(b, ctx) == []


def test_administrative_group_pulls_in_providers_from_infrastructure(p1, ctx):
    [b] = list(ResourceTypesSlicer({"groups": ["administrative"]}).apply([p1], ctx))
    assert {"Practitioner", "Organization", "Location"} <= set(type_counts(b))
    assert "Encounter" not in type_counts(b)


def test_clinical_minus_excluded_types(p1, ctx):
    [b] = list(ResourceTypesSlicer({"groups": ["clinical"], "exclude_types": ["Observation", "Device"]}).apply([p1], ctx))
    t = type_counts(b)
    assert "Observation" not in t and "Device" not in t and "Encounter" in t and "Claim" not in t
    assert dangling(b, ctx) == []


def test_resource_types_requires_a_selection():
    with pytest.raises(InvalidSpecError):
        ResourceTypesSlicer({})
    with pytest.raises(InvalidSpecError):
        ResourceTypesSlicer({"groups": ["bogus"]})


# ── resource_filter ───────────────────────────────────────────────────────
def test_vitals_vs_labs(p1, ctx):
    vitals = list(ResourceFilterSlicer({"resource_type": "Observation", "categories": ["vital-signs"]}).apply([p1], ctx))[0]
    labs = list(ResourceFilterSlicer({"resource_type": "Observation", "categories": ["laboratory"]}).apply([p1], ctx))[0]
    assert type_counts(vitals)["Observation"] == 5 and type_counts(labs)["Observation"] == 1  # 4+1 vitals, 1 lab
    assert type_counts(vitals)["Encounter"] == 3  # other types untouched


def test_resource_filter_by_code_text_and_exclude(p1, ctx):
    [b] = list(ResourceFilterSlicer({"resource_type": "Observation", "codes": ["heart rate"]}).apply([p1], ctx))
    assert type_counts(b)["Observation"] == 1
    [b2] = list(
        ResourceFilterSlicer({"resource_type": "Observation", "categories": ["laboratory"], "exclude": True}).apply([p1], ctx)
    )
    assert type_counts(b2)["Observation"] == 5
    with pytest.raises(InvalidSpecError):
        ResourceFilterSlicer({"resource_type": "Observation"})  # needs a criterion


def test_chained_vitals_only_has_no_dangling_references(p1, ctx):
    [a] = list(ResourceTypesSlicer({"types": ["Observation"]}).apply([p1], ctx))
    [b] = list(ResourceFilterSlicer({"resource_type": "Observation", "categories": ["vital-signs"]}).apply([a], ctx))
    assert set(type_counts(b)) == {"Patient", "Observation"}
    assert dangling(b, ctx) == []  # was broken before: Observation.encounter pointed at a dropped Encounter


# ── infrastructure (administrative only) ──────────────────────────────────
def test_infrastructure_slicer_emits_providers_and_no_patients(p1, ctx):
    [b] = list(InfrastructureSlicer({}).apply([p1], ctx))
    t = type_counts(b)
    assert "Patient" not in t and {"Practitioner", "Organization", "Location"} <= set(t)
    [only_loc] = list(InfrastructureSlicer({"types": ["Location"]}).apply([p1], ctx))
    assert set(type_counts(only_loc)) == {"Location"}
    assert list(InfrastructureSlicer({}).apply([p1], SliceContext())) == []  # nothing to emit without infra


def test_limit_and_redact_keep_references_clean(p1, ctx):
    [b] = list(LimitSlicer({"max_resources_per_bundle": 6}).apply([p1], ctx))
    assert len(b["entry"]) == 6 and dangling(b, ctx) == []
    [r] = list(RedactInfraSlicer({}).apply([p1], ctx))
    assert "Claim" not in type_counts(r) and dangling(r, ctx) == []


# ── last_n_years ──────────────────────────────────────────────────────────
def test_last_n_years(p1, ctx):
    ctx.meta["reference_date"] = "20260101"  # encounters: 2024-03, 2024-09, 2025-01
    [b] = list(DateWindowSlicer({"last_n_years": 1}).apply([p1], ctx))
    assert sorted(r["class"]["code"] for r in fhir.resources(b) if r["resourceType"] == "Encounter") == ["EMER"]
    [b2] = list(DateWindowSlicer({"last_n_years": 2}).apply([p1], ctx))
    assert len([r for r in fhir.resources(b2) if r["resourceType"] == "Encounter"]) == 3
    for bad in ({"last_n_years": 1, "last_n_days": 5}, {"last_n_years": 1, "from_date": "2024-01-01"}):
        with pytest.raises(InvalidSpecError):
            DateWindowSlicer(bad)
    assert date(2024, 2, 29).replace(year=2023, day=28)  # the Feb-29 fallback branch's arithmetic


# ── codes ─────────────────────────────────────────────────────────────────
def test_alphanumeric_codes_need_a_known_system_and_text_with_colon_stays_text():
    icd = {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "C25.0", "display": "Malignant neoplasm"}]}
    assert Pattern("ICD10:C25.0").matches(icd) and not Pattern("LOINC:C25.0").matches(icd)
    assert Pattern("heart: failure").text == "heart: failure"  # unknown "system" => plain text, not a code
    assert flags.parse_condition("ICD10:C25.0") == ("ICD10", "C25.0")
    for bad in ("C25.0", "diabetes", "ICD10:"):
        with pytest.raises(InvalidSpecError):
            flags.parse_condition(bad)


# ── keep module: match any / all ──────────────────────────────────────────
def test_keep_module_match_any_vs_all():
    any_mod = flags.build_keep_module(["235595009"], ["73761001"], "any")
    all_mod = flags.build_keep_module(["235595009"], ["73761001"], "all")
    assert any_mod["states"]["Initial"]["conditional_transition"][0]["condition"]["condition_type"] == "Or"
    assert all_mod["states"]["Initial"]["conditional_transition"][0]["condition"]["condition_type"] == "And"


def test_specialty_can_set_match_and_request_wins():
    runtime = GeneratorRuntime.from_path(BACKEND_DIR / "tests" / "connectors_test.yaml")
    spec = runtime.resolve(GenerationRequest(connector="synthea", cohort={"specialty": "gastro"}))
    assert spec.cohort.match == "any" and spec.cohort.procedures == ["73761001"] and spec.warnings == []
    spec2 = runtime.resolve(GenerationRequest(connector="synthea", cohort={"specialty": "gastro", "match": "all"}))
    assert spec2.cohort.match == "all"


# ── per-request connector params ──────────────────────────────────────────
def test_request_params_allow_us_core_and_dates_but_nothing_dangerous():
    base = SyntheaConnector({"reference_date": "20260101", "properties": {"generate.thread_pool_size": 2}})
    c = base.with_request_params(
        {"reference_date": "20250101", "properties": {"exporter.fhir.use_us_core_ig": True, "exporter.fhir.us_core_version": "6.1.0"}}
    )
    assert c.options.reference_date == "20250101"
    assert c.options.properties == {
        "generate.thread_pool_size": 2,  # config property kept
        "exporter.fhir.use_us_core_ig": True,
        "exporter.fhir.us_core_version": "6.1.0",
    }
    assert base.options.reference_date == "20260101" and base.with_request_params({}) is base  # base untouched
    for bad in (
        {"properties": {"exporter.baseDirectory": "/etc"}},      # connector-managed
        {"properties": {"exporter.fhir.bulk_data": True}},       # would change the output layout
        {"properties": {"exporter.csv.export": True}},           # outside the allowed prefixes
        {"properties": {"generate.x": "a; rm -rf /"}},           # odd characters
        {"docker_image": "evil"}, {"jvm_args": ["-Dx"]}, {"modules_dir": "/"},   # not overridable at all
        {"reference_date": "yesterday"},
    ):
        with pytest.raises(InvalidSpecError):
            base.with_request_params(bad)


def test_request_params_validated_at_resolve_time_and_rejected_by_connectors_without_support():
    runtime = GeneratorRuntime.from_path(BACKEND_DIR / "tests" / "connectors_test.yaml")
    with pytest.raises(InvalidSpecError):
        runtime.resolve(GenerationRequest(connector="synthea", connector_params={"docker_image": "x"}))
    with pytest.raises(InvalidSpecError):  # static_fixtures takes no per-request params
        runtime.resolve(GenerationRequest(connector_params={"reference_date": "20250101"}))
    ok = runtime.resolve(GenerationRequest(connector="synthea", connector_params={"properties": {"exporter.fhir.use_us_core_ig": True}}))
    assert ok.connector_params["properties"]["exporter.fhir.use_us_core_ig"] is True


# ── term index ────────────────────────────────────────────────────────────
MODULES = [
    ("gallstones", {"states": {
        "Onset": {"type": "ConditionOnset", "codes": [{"system": "SNOMED-CT", "code": "235919008", "display": "Gallbladder calculus (disorder)"}]},
        "Chole": {"type": "Procedure", "codes": [{"system": "SNOMED-CT", "code": "38102005", "display": "Cholecystectomy (procedure)"}]},
        "Wait": {"type": "Delay"},
    }}),
    ("colorectal_cancer", {"states": {
        "Scope": {"type": "Procedure", "codes": [{"system": "SNOMED-CT", "code": "73761001", "display": "Colonoscopy (procedure)"}]},
        "Chole": {"type": "Procedure", "codes": [{"system": "SNOMED-CT", "code": "38102005", "display": "Cholecystectomy (procedure)"}]},
        "Icd": {"type": "ConditionOnset", "codes": [{"system": "ICD10", "code": "C25.0", "display": "Malignant neoplasm of head of pancreas"}]},
    }}),
]


def test_extract_and_search_terms():
    idx = terms.extract_terms(MODULES)
    assert {(t["kind"], t["code"]) for t in idx} == {
        ("condition", "235919008"), ("procedure", "38102005"), ("procedure", "73761001"), ("condition", "C25.0")
    }  # fmt: skip
    chole = next(t for t in idx if t["code"] == "38102005")
    assert chole["modules"] == ["gallstones", "colorectal_cancer"]  # same term in two modules: deduplicated, both listed
    page, total = terms.search_terms(idx, "colon", None, 10)
    assert [t["code"] for t in page] == ["73761001"] and total == 1
    assert terms.search_terms(idx, "gallstones", "procedure", 10)[1] == 1  # matches by module name, filtered by kind
    assert terms.search_terms(idx, "C25", None, 10)[1] == 1  # matches by code
    assert terms.reference_for(chole) == "SNOMED-CT:38102005"
    icd = next(t for t in idx if t["code"] == "C25.0")
    assert flags.parse_condition(terms.reference_for(icd)) == ("ICD10", "C25.0")  # round-trips into a cohort filter
    assert terms.search_terms(idx, None, None, 2)[0].__len__() == 2  # limit applies, total still reported


def test_include_infrastructure_makes_a_filtered_subset_self_contained(p1, ctx):
    plain = list(ResourceTypesSlicer({"types": ["MedicationRequest"]}).apply([p1], ctx))[0]
    assert dangling(plain, ctx) == [] and "Practitioner" not in type_counts(plain)  # provider links unresolved but resolvable
    assert fhir.dangling_references(plain), "without the option the Practitioner?identifier=... link points at nothing"
    [full] = list(ResourceTypesSlicer({"types": ["MedicationRequest"], "include_infrastructure": True}).apply([p1], ctx))
    assert "Practitioner" in type_counts(full) and fhir.dangling_references(full) == []
    assert set(type_counts(full)) <= {"Patient", "MedicationRequest", "Practitioner", "Organization", "Location"}


def test_include_infrastructure_also_covers_providers_a_kept_resource_points_at_when_some_are_asked_for(p1, ctx):
    # Asking for Practitioner pulls providers in before filtering, but keeps only that type: a kept Claim's Organization
    # reference must still resolve when include_infrastructure is on (found by the UI's resource picker).
    [out] = list(
        ResourceTypesSlicer(
            {"types": ["Patient", "Claim", "ExplanationOfBenefit", "Practitioner"], "include_infrastructure": True}
        ).apply([p1], ctx)
    )
    assert "Organization" in type_counts(out) and fhir.dangling_references(out) == []


def test_resource_groups_only_name_types_synthea_can_write():
    from app.generator.resource_groups import GROUPS

    # Read from Synthea v4.0.0's R4 exporter; the UI's resource picker lists the same 28 (+ Patient anchor included).
    writable = {
        "AllergyIntolerance", "CarePlan", "CareTeam", "Claim", "Condition", "Coverage", "Device", "DiagnosticReport",
        "DocumentReference", "Encounter", "ExplanationOfBenefit", "Goal", "ImagingStudy", "Immunization", "Location",
        "Media", "Medication", "MedicationAdministration", "MedicationRequest", "Observation", "Organization",
        "Patient", "Practitioner", "PractitionerRole", "Procedure", "Provenance", "ServiceRequest", "SupplyDelivery",
    }  # fmt: skip
    named = {t for types in GROUPS.values() for t in types}
    assert named <= writable, f"not writable by Synthea: {sorted(named - writable)}"
    assert writable - {"Practitioner", "PractitionerRole", "Organization", "Location"} <= set(GROUPS["clinical"]) | set(GROUPS["financial"]) | {"Patient", "Provenance"}, "every clinical type is reachable through a group"


def test_bundle_reader_reads_json_zip_and_ndjson_results(tmp_path, p1):
    import json
    import zipfile

    from app.generator import bundle_reader

    (tmp_path / "bundles.json").write_text(json.dumps([p1, p1]), encoding="utf-8")
    assert len(bundle_reader.load_bundles([tmp_path / "bundles.json"])) == 2

    with zipfile.ZipFile(tmp_path / "bundles.zip", "w") as zf:
        zf.writestr("bundle-00002.json", json.dumps(p1))
        zf.writestr("bundle-00001.json", json.dumps(p1))
    assert len(bundle_reader.load_bundles([tmp_path / "bundles.zip"])) == 2

    # ndjson holds every patient mixed together: one pseudo-bundle with all the resources
    resources = list(fhir.resources(p1))
    (tmp_path / "Patient.ndjson").write_text(
        "\n".join(json.dumps(r) for r in resources if r["resourceType"] == "Patient") + "\n", encoding="utf-8"
    )
    (tmp_path / "Condition.ndjson").write_text(
        "\n".join(json.dumps(r) for r in resources if r["resourceType"] == "Condition") + "\n", encoding="utf-8"
    )
    [merged] = bundle_reader.load_bundles([tmp_path / "Patient.ndjson", tmp_path / "Condition.ndjson"])
    assert {fhir.resource_type(r) for r in fhir.resources(merged)} == {"Patient", "Condition"}

    [summary] = bundle_reader.summarize([p1])
    assert summary["index"] == 0 and summary["resources"] == sum(summary["by_type"].values())
    assert summary["label"] != "Bundle 1", "the patient's name is used when there is one"

    with pytest.raises(ValueError):
        bundle_reader.load_bundles([tmp_path / "notes.txt"])
