"""Real Synthea in Docker. Run with `just test-e2e` (needs Docker + `just synthea-build`)."""

import pytest

import app.generator  # noqa: F401
from app.generator import fhir
from app.generator.connectors.static_fixtures import BACKEND_DIR
from app.generator.connectors.synthea.connector import SyntheaConnector
from app.generator.runtime import GeneratorRuntime
from app.generator.spec import CohortSpec, GenerationRequest

pytestmark = pytest.mark.slow
OPTIONS = {"reference_date": "20260101", "years_of_history": 5, "jvm_args": ["-Xmx1g"]}


async def _connector() -> SyntheaConnector:
    conn = SyntheaConnector(OPTIONS)
    health = await conn.healthcheck()
    if not health.ok:
        pytest.skip(health.detail)
    return conn


async def test_generates_exact_count_and_is_reproducible(tmp_path):
    connector = await _connector()
    cohort = CohortSpec(count=2, seed=42)
    a = await connector.generate(cohort, tmp_path / "a")
    b = await connector.generate(cohort, tmp_path / "b")
    bundles_a, bundles_b = list(a.patient_bundles), list(b.patient_bundles)
    assert len(bundles_a) == 2
    assert bundles_a == bundles_b  # same seed + pinned reference date => identical output
    assert a.meta["synthea_version"]  # reported by the jar; recorded verbatim
    assert a.meta["image"] == "fhir-gen-synthea:4.0.0"
    assert set(a.infra) == {"hospitalInformation", "practitionerInformation"}


async def test_specialty_condition_is_enforced_by_keep_module(tmp_path):
    connector = await _connector()
    cohort = CohortSpec(count=2, seed=7, gender="F", age_range=(40, 80), conditions=["44054006"])
    raw = await connector.generate(cohort, tmp_path / "k")
    bundles = list(raw.patient_bundles)
    assert len(bundles) == 2
    for bundle in bundles:
        codes = {
            r["code"]["coding"][0]["code"] for r in fhir.resources(bundle) if r["resourceType"] == "Condition"
        }
        patient = next(r for r in fhir.resources(bundle) if r["resourceType"] == "Patient")
        assert "44054006" in codes
        assert patient["gender"] == "female"


async def test_full_pipeline_self_contained_references(tmp_path):
    await _connector()  # skips if Docker/image missing
    runtime = GeneratorRuntime.from_path(BACKEND_DIR / "configs" / "synthetic_data_connectors.yaml")
    spec = runtime.resolve(
        GenerationRequest(
            cohort={"count": 1, "seed": 3, "years_of_history": 2},
            shape=[{"slicer": "full_record", "params": {"include_infrastructure": True}}],
        )
    )
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    assert result.summary["patients"] == 1 and result.summary["resources"]["Encounter"] >= 1
    assert result.provenance["mode"] == "docker"


# ── Phase 3: shapes on real Synthea output ─────────────────────────────────
def _runtime() -> GeneratorRuntime:
    return GeneratorRuntime.from_path(BACKEND_DIR / "configs" / "synthetic_data_connectors.yaml")


async def test_end_date_is_pinned_so_nothing_happens_after_the_reference_date(tmp_path):
    connector = await _connector()
    raw = await connector.generate(CohortSpec(count=1, seed=101, age_range=(30, 70)), tmp_path / "p")
    bundle = next(iter(raw.patient_bundles))
    latest = max(
        r["period"]["start"][:10] for r in fhir.resources(bundle) if r["resourceType"] == "Encounter"
    )
    assert latest <= "2026-01-01", f"simulation ran past the pinned end date: {latest}"
    assert raw.meta["end_date"] == "20260101"


async def test_single_surgery_episode_preset_on_real_data(tmp_path):
    await _connector()
    runtime = _runtime()
    spec = runtime.resolve(
        GenerationRequest(preset="single-surgery-episode", cohort={"seed": 3}, options={"check_references": True})
    )
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    [bundle] = result.inline
    res = list(fhir.resources(bundle))
    procs = [r for r in res if r["resourceType"] == "Procedure"]
    assert any(p["code"]["coding"][0]["code"] == "80146002" for p in procs), "the appendectomy is in the episode"
    assert len([r for r in res if r["resourceType"] == "Encounter"]) == 1
    assert len([r for r in res if r["resourceType"] == "Patient"]) == 1
    assert "Practitioner" in {r["resourceType"] for r in res}  # conditional references resolved from infra
    # strict: every reference in a REAL bundle resolves (check_references would have failed the run otherwise)
    assert fhir.dangling_references(bundle) == []
    assert result.provenance["keep_procedures"] == ["80146002"]


async def test_diabetes_journey_on_real_data(tmp_path):
    await _connector()
    runtime = _runtime()
    runtime.config.limits.inline_max_bytes = 100_000_000  # real diabetic records exceed the 5 MB default cap
    spec = runtime.resolve(
        GenerationRequest(preset="diabetes-journey", cohort={"count": 2, "seed": 7}, sink={"name": "inline"},
                          options={"check_references": True})
    )  # fmt: skip
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    assert len(result.inline) == 2
    for bundle in result.inline:
        enc = [r for r in fhir.resources(bundle) if r["resourceType"] == "Encounter"]
        assert enc, "the condition touched at least one encounter"
        assert any(
            c["code"]["coding"][0]["code"] == "44054006" for c in fhir.resources(bundle) if c["resourceType"] == "Condition"
        )
        assert fhir.dangling_references(bundle) == []


# ── Phase 4: dynamic shapes on real output ────────────────────────────────
GI_CONDITIONS = {"235595009", "235919008", "65275009", "363406005", "68496003"}
GI_PROCEDURES = {"73761001", "38102005", "45595009", "80146002", "43075005"}


def _codes(bundle, rtype):
    return {c["code"]["coding"][0]["code"] for c in fhir.resources(bundle) if c["resourceType"] == rtype}


async def test_term_index_from_the_real_jar(tmp_path):
    connector = SyntheaConnector({**OPTIONS, "cache_dir": str(tmp_path / "cache")})
    health = await connector.healthcheck()
    if not health.ok:
        pytest.skip(health.detail)
    items, total = await connector.terms("colonoscopy", "procedure", 10)
    assert any(t["reference"] == "SNOMED-CT:73761001" for t in items) and total >= 1
    items, _ = await connector.terms("excision of appendix", None, 5)
    assert items[0]["reference"] == "SNOMED-CT:80146002"
    assert (await connector.terms(None, "condition", 1))[1] > 1000  # thousands of terms indexed
    assert list((tmp_path / "cache").glob("synthea-terms-*.json")), "index cached on disk"
    again = SyntheaConnector({**OPTIONS, "cache_dir": str(tmp_path / "cache")})
    assert (await again.terms("colonoscopy", None, 3))[1] >= 1  # served from the cache file


async def test_us_core_profiles_can_be_requested_per_request(tmp_path):
    runtime = _runtime()
    spec = runtime.resolve(
        GenerationRequest(
            cohort={"count": 1, "seed": 4, "years_of_history": 1},
            connector_params={"properties": {"exporter.fhir.use_us_core_ig": True}},
            shape=[{"slicer": "resource_types", "params": {"types": ["Patient"]}}],
        )
    )
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    patient = next(r for r in fhir.resources(result.inline[0]) if r["resourceType"] == "Patient")
    profiles = patient.get("meta", {}).get("profile", [])
    assert any("us/core" in p.lower() or "us-core" in p.lower() for p in profiles), profiles


async def test_gastroenterology_specialty_matches_conditions_or_operations(tmp_path):
    await _connector()
    runtime = _runtime()
    runtime.config.limits.inline_max_bytes = 500_000_000
    spec = runtime.resolve(
        GenerationRequest(
            cohort={"specialty": "gastroenterology", "count": 3, "seed": 11},
            shape=[{"slicer": "limit", "params": {"max_bundles": 3}}],
        )
    )
    assert spec.cohort.match == "any"
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    assert len(result.inline) == 3
    for bundle in result.inline:
        has_condition = bool(_codes(bundle, "Condition") & GI_CONDITIONS)
        had_operation = bool(_codes(bundle, "Procedure") & GI_PROCEDURES)
        assert has_condition or had_operation, "each patient has a GI condition OR a GI operation"


async def test_gastroenterology_operation_episodes_preset(tmp_path):
    await _connector()
    runtime = _runtime()
    runtime.config.limits.inline_max_bytes = 500_000_000
    spec = runtime.resolve(
        GenerationRequest(
            preset="gastroenterology-operations",
            cohort={"count": 2, "seed": 11},
            sink={"name": "inline"},
            options={"check_references": True},
        )
    )
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    assert result.inline, "at least one operation episode"
    for bundle in result.inline:
        assert _codes(bundle, "Procedure") & GI_PROCEDURES, "each bundle is a stay containing a GI operation"
        assert len([r for r in fhir.resources(bundle) if r["resourceType"] == "Encounter"]) == 1


async def test_vitals_administrative_and_five_year_presets(tmp_path):
    await _connector()
    runtime = _runtime()
    runtime.config.limits.inline_max_bytes = 500_000_000

    async def run(preset, **cohort):
        spec = runtime.resolve(GenerationRequest(preset=preset, cohort={"seed": 21, **cohort}, sink={"name": "inline"}))
        return await runtime.run(spec, workdir=tmp_path / preset, artifact_dir=tmp_path / f"{preset}-out")

    vitals = await run("vitals-only", count=1)
    obs = [r for r in fhir.resources(vitals.inline[0]) if r["resourceType"] == "Observation"]
    assert obs and all(
        any(c["code"] == "vital-signs" for cc in o["category"] for c in cc["coding"]) for o in obs
    ), "only vital signs - no labs, no surveys"
    assert set(vitals.summary["resources"]) == {"Patient", "Observation"}

    admin = await run("administrative-data", count=1)
    types = set(admin.summary["resources"])
    assert "Patient" not in types and {"Organization", "Location", "Practitioner"} <= types

    five = await run("last-5-years", count=1)
    dates = [r["period"]["start"][:10] for r in fhir.resources(five.inline[0]) if r["resourceType"] == "Encounter"]
    assert dates and all("2021-01-01" <= d <= "2026-01-01" for d in dates), dates


# ── comorbidity (within=all) and medication targeting ─────────────────────
def _med_codes(bundle):
    return {
        m["medicationCodeableConcept"]["coding"][0]["code"]
        for m in fhir.resources(bundle)
        if m["resourceType"] == "MedicationRequest" and "medicationCodeableConcept" in m
    }


async def test_comorbidity_within_all_requires_every_condition(tmp_path):
    connector = await _connector()
    cohort = CohortSpec(
        count=2, seed=5, age_range=(45, 85), conditions=["44054006", "59621000"], within="all"
    )  # type 2 diabetes AND essential hypertension
    raw = await connector.generate(cohort, tmp_path / "c")
    bundles = list(raw.patient_bundles)
    assert len(bundles) == 2
    for bundle in bundles:
        codes = {c["code"]["coding"][0]["code"] for c in fhir.resources(bundle) if c["resourceType"] == "Condition"}
        assert {"44054006", "59621000"} <= codes, f"missing one of the two conditions: {codes}"


async def test_medication_cohort_patients_are_on_the_drug(tmp_path):
    connector = await _connector()
    cohort = CohortSpec(count=2, seed=5, age_range=(40, 90), medications=["860975"])  # metformin ER 500 mg
    raw = await connector.generate(cohort, tmp_path / "m")
    bundles = list(raw.patient_bundles)
    assert len(bundles) == 2
    for bundle in bundles:
        assert "860975" in _med_codes(bundle), "the patient was prescribed the medication"
    assert raw.meta["keep_medications"] == ["860975"]
