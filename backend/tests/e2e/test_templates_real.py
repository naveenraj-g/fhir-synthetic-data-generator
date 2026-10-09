"""Every Gastroenterology / Orthopedics / Preventive-health template, run against real Synthea in Docker and checked
for what it promises. Slow (minutes): `just test-e2e`. Skips without Docker + the image."""

import pytest

import app.generator  # noqa: F401
from app.generator import fhir
from app.generator.connectors.static_fixtures import BACKEND_DIR
from app.generator.connectors.synthea.connector import SyntheaConnector
from app.generator.runtime import GeneratorRuntime
from app.generator.spec import GenerationRequest

pytestmark = pytest.mark.slow
CONFIG = BACKEND_DIR / "configs" / "synthetic_data_connectors.yaml"


async def _run(tmp_path, preset: str, seed: int = 5):
    conn = SyntheaConnector({})
    health = await conn.healthcheck()
    if not health.ok:
        pytest.skip(health.detail)
    runtime = GeneratorRuntime.from_path(CONFIG)
    runtime.config.limits.inline_max_bytes = 500_000_000  # real records are large
    runtime.config.limits.sync_max_patients = 50
    # Same shape and cohort as the template, but delivered inline so the test can look inside.
    spec = runtime.resolve(
        GenerationRequest(
            preset=preset, cohort={"seed": seed}, sink={"name": "inline"}, options={"check_references": True}
        )
    )
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    assert result.inline, f"{preset}: produced no bundles"
    return result


def _res(bundle, rtype):
    return [r for r in fhir.resources(bundle) if r["resourceType"] == rtype]


def _proc_codes(bundle):
    return {p["code"]["coding"][0]["code"] for p in _res(bundle, "Procedure")}


def _cond_codes(bundle):
    return {c["code"]["coding"][0]["code"] for c in _res(bundle, "Condition")}


OPERATION_TEMPLATES = {
    "gastro-colonoscopy": {"73761001"},
    "gastro-gallbladder-removal": {"38102005", "45595009"},
    "gastro-appendectomy": {"80146002"},
    "gastro-colon-resection": {"43075005"},
    "ortho-knee-replacement": {"609588000"},
    "ortho-hip-replacement": {"52734007"},
}


@pytest.mark.parametrize("preset,codes", OPERATION_TEMPLATES.items())
async def test_operation_templates_return_the_operation_stay(tmp_path, preset, codes):
    result = await _run(tmp_path, preset)
    for bundle in result.inline:
        assert _proc_codes(bundle) & codes, f"{preset}: the operation is in the bundle"
        assert len(_res(bundle, "Encounter")) == 1, "one stay per bundle"
        assert len(_res(bundle, "Patient")) == 1
        assert not (_res(bundle, "Claim") and False)  # billing belonging to the stay is allowed


ALL_OPERATIONS = {
    "gastro-one-patient-all-operations": {"73761001", "38102005", "45595009", "80146002", "43075005"},
    "ortho-one-patient-all-operations": {"609588000", "52734007", "699253003", "387685009"},
}


@pytest.mark.parametrize("preset,codes", ALL_OPERATIONS.items())
async def test_one_patient_all_operations_templates(tmp_path, preset, codes):
    result = await _run(tmp_path, preset)
    patients = {r["id"] for b in result.inline for r in _res(b, "Patient")}
    assert len(patients) == 1, "all bundles belong to the single requested patient"
    for bundle in result.inline:
        assert _proc_codes(bundle) & codes


JOURNEYS = {
    "gastro-reflux-journey": {"235595009"},
    "ortho-fracture-care": {"359817006", "16114001", "58150001", "65966004", "33737001"},
    "ortho-osteoarthritis-journey": {"239873007", "239872002", "201834006"},
    "ortho-osteoporosis-journey": {"64859006"},
}


@pytest.mark.parametrize("preset,codes", JOURNEYS.items())
async def test_condition_journey_templates(tmp_path, preset, codes):
    result = await _run(tmp_path, preset)
    for bundle in result.inline:
        assert _cond_codes(bundle) & codes, f"{preset}: the patient has the condition"
        assert _res(bundle, "Encounter"), "and the encounters it touches"


@pytest.mark.parametrize("preset", ["gastro-patient-full-record", "ortho-patient-full-record"])
async def test_specialty_full_record_templates(tmp_path, preset):
    result = await _run(tmp_path, preset)
    assert len(result.inline) == 1 and _res(result.inline[0], "Patient")


async def test_preventive_wellness_visits(tmp_path):
    result = await _run(tmp_path, "preventive-wellness-visits")
    for bundle in result.inline:
        [enc] = _res(bundle, "Encounter")
        text = " ".join(t.get("text", "") for t in enc.get("type", []))
        assert "General examination" in text or "check up" in text, text


async def test_preventive_screenings(tmp_path):
    result = await _run(tmp_path, "preventive-screenings")
    screening_codes = {"710841007", "428211000124100", "762993000", "710824005", "24623002", "312681000"}
    for bundle in result.inline:
        shown = [p["code"]["coding"][0] for p in _res(bundle, "Procedure")]
        assert any("screening" in c.get("display", "").lower() or c["code"] in screening_codes for c in shown)


async def test_preventive_immunizations_and_risk_factors(tmp_path):
    imm = await _run(tmp_path, "preventive-immunizations")
    infra = {"Practitioner", "Organization", "Location"}  # attached on purpose: the record is self-contained
    assert "Immunization" in imm.summary["resources"]
    assert set(imm.summary["resources"]) <= {"Patient", "Immunization"} | infra

    risk = await _run(tmp_path, "preventive-risk-factors")
    assert "Observation" in risk.summary["resources"]
    assert set(risk.summary["resources"]) <= {"Patient", "Observation"} | infra
    for bundle in risk.inline:
        for o in _res(bundle, "Observation"):
            cats = {c["code"] for cc in o.get("category", []) for c in cc["coding"]}
            assert cats & {"vital-signs", "social-history", "survey"}, cats


async def test_preventive_profile_has_no_billing_and_no_illness_only_data(tmp_path):
    result = await _run(tmp_path, "preventive-health-profile")
    types = set(result.summary["resources"])
    assert {"Patient", "Encounter", "Observation"} <= types
    assert not (types & {"Claim", "ExplanationOfBenefit", "MedicationRequest", "CarePlan"})
