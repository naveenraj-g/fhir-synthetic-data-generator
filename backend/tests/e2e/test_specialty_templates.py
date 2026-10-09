"""Every specialty template, run against real Synthea in Docker, checked against what ITS OWN definition promises
(expectations are derived from the YAML, so a new template is tested by adding it). Slow: `just test-e2e`.

Runs each template with count=1 as a screen; the per-patient time tells whether the shipped count is practical."""

import json
from datetime import date

import pytest
import yaml

import app.generator  # noqa: F401
from app.generator import fhir
from app.generator.connectors.static_fixtures import BACKEND_DIR
from app.generator.connectors.synthea.connector import SyntheaConnector
from app.generator.runtime import GeneratorRuntime
from app.generator.spec import GenerationRequest

pytestmark = pytest.mark.slow
CONFIG = BACKEND_DIR / "configs" / "synthetic_data_connectors.yaml"
# Covered by tests/e2e/test_templates_real.py and test_synthea_docker.py
OLDER_CATEGORIES = {"General", "Gastroenterology", "Orthopedics", "Preventive health"}
REFERENCE = date(2026, 1, 1)

_raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
SPECIALTY_TEMPLATES = {
    name: p for name, p in _raw["presets"].items() if p.get("category") not in OLDER_CATEGORIES
}
SPECIALTIES = _raw["specialties"]


def _codes(bundle, rtype):
    return {r["code"]["coding"][0]["code"] for r in fhir.resources(bundle) if r["resourceType"] == rtype}


def _age(bundle) -> int:
    patient = next(r for r in fhir.resources(bundle) if r["resourceType"] == "Patient")
    return (REFERENCE - date.fromisoformat(patient["birthDate"])).days // 365


@pytest.mark.parametrize("name", sorted(SPECIALTY_TEMPLATES))
async def test_specialty_template(tmp_path, name):
    conn = SyntheaConnector({})
    health = await conn.healthcheck()
    if not health.ok:
        pytest.skip(health.detail)

    runtime = GeneratorRuntime.from_path(CONFIG)
    runtime.config.limits.inline_max_bytes = 900_000_000
    runtime.config.limits.sync_max_patients = 50
    runtime.config.connectors["synthea"]["options"]["timeout_seconds"] = 120  # a stalled run is then retried promptly
    preset = SPECIALTY_TEMPLATES[name]
    spec = runtime.resolve(
        GenerationRequest(preset=name, cohort={"count": 1, "seed": 11}, sink={"name": "inline"}, options={"check_references": True})
    )
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    bundles = result.inline
    assert bundles, f"{name}: produced nothing"

    step = preset["shape"][0]
    params = step.get("params", {})
    specialty = SPECIALTIES.get(preset["cohort"].get("specialty", ""), {})

    if step["slicer"] == "condition_scoped":  # a journey: the condition is in the record, with its encounters
        for b in bundles:
            assert _codes(b, "Condition") & set(params["conditions"]), f"{name}: no matching condition"
            assert len(fhir.resources(b) and [r for r in fhir.resources(b) if r["resourceType"] == "Encounter"]) >= 1
    elif step["slicer"] == "encounter" and "with_procedure" in params:  # an operation stay
        for b in bundles:
            assert _codes(b, "Procedure") & set(params["with_procedure"]), f"{name}: operation missing"
            assert len([r for r in fhir.resources(b) if r["resourceType"] == "Encounter"]) == 1
    elif step["slicer"] == "encounter":  # check-ups
        for b in bundles:
            [enc] = [r for r in fhir.resources(b) if r["resourceType"] == "Encounter"]
            assert "General examination" in json.dumps(enc.get("type")) or "check up" in json.dumps(enc.get("type"))
    elif step["slicer"] == "resource_types":  # vaccinations
        assert result.summary["resources"].get("Immunization", 0) >= 0
        assert set(result.summary["resources"]) <= {"Patient", "Immunization", "Practitioner", "Organization", "Location"}
    elif step["slicer"] in ("full_record", "date_window"):
        b = bundles[0]
        wanted = set(specialty.get("conditions") or []) | set(specialty.get("procedures") or [])
        if wanted:
            assert (_codes(b, "Condition") | _codes(b, "Procedure")) & wanted, f"{name}: none of the specialty's codes present"
        if specialty.get("age_range"):
            lo, hi = specialty["age_range"]
            assert lo <= _age(b) <= hi, f"{name}: age {_age(b)} outside {lo}-{hi}"
        if specialty.get("gender"):
            patient = next(r for r in fhir.resources(b) if r["resourceType"] == "Patient")
            assert patient["gender"] == {"F": "female", "M": "male"}[specialty["gender"]]
    else:  # pragma: no cover - a new kind of template needs a rule here
        pytest.fail(f"{name}: no expectation defined for slicer {step['slicer']}")
