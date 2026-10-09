import json
import zipfile

import pytest

import app.generator  # noqa: F401  (registers built-ins)
from app.generator import fhir
from app.generator.config_loader import load_config
from app.generator.errors import ConfigError, InvalidSpecError, LimitExceededError
from app.generator.runtime import GeneratorRuntime
from app.generator.spec import GenerationRequest
from app.generator.connectors.static_fixtures import BACKEND_DIR

CONFIG = BACKEND_DIR / "tests" / "connectors_test.yaml"


@pytest.fixture
def runtime():
    return GeneratorRuntime.from_path(CONFIG)


async def run(runtime, tmp_path, **req):
    spec = runtime.resolve(GenerationRequest(**req))
    return spec, await runtime.run(spec, workdir=tmp_path / "work", artifact_dir=tmp_path / "out")


# ── config loader ─────────────────────────────────────────────────────────
def test_config_reports_all_problems(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text(
        "defaults: {connector: nope}\n"
        "connectors:\n  a: {type: static_fixtures, options: {x: '${MISSING_VAR}'}}\n"
        "presets:\n  p: {shape: [{slicer: ghost}], sink: {name: ghost}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_config(bad, env={}, known_slicers={"full_record"})
    text = " | ".join(exc.value.details)
    assert "defaults.connector" in text
    assert "MISSING_VAR" in text and "connectors.a.options.x" in text
    assert "unknown slicer 'ghost'" in text and "unknown sink 'ghost'" in text


def test_config_skips_disabled_entries(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "defaults: {connector: a}\n"
        "connectors:\n  a: {type: static_fixtures}\n"
        "sinks:\n  s: {type: fhir_server, enabled: false, options: {url: '${NOT_SET}'}}\n",
        encoding="utf-8",
    )
    assert load_config(cfg, env={}).default_connector == "a"


def test_env_default_syntax(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "defaults: {connector: a}\nconnectors:\n  a: {type: t, options: {v: '${X:-fallback}'}}\n",
        encoding="utf-8",
    )
    assert load_config(cfg, env={}).connector_options("a") == {"v": "fallback"}


# ── resolution ────────────────────────────────────────────────────────────
def test_preset_with_override_and_random_seed_recorded(runtime):
    spec = runtime.resolve(GenerationRequest(preset="full-patient", cohort={"count": 2}))
    assert spec.cohort.count == 2
    assert isinstance(spec.cohort.seed, int)


def test_unknown_preset_slicer_sink(runtime):
    with pytest.raises(InvalidSpecError):
        runtime.resolve(GenerationRequest(preset="nope"))
    with pytest.raises(InvalidSpecError):
        runtime.resolve(GenerationRequest(shape=[{"slicer": "nope"}]))
    with pytest.raises(InvalidSpecError):
        runtime.resolve(GenerationRequest(sink={"name": "nope"}))


def test_bad_slicer_params_rejected(runtime):
    with pytest.raises(InvalidSpecError):
        runtime.resolve(GenerationRequest(shape=[{"slicer": "resource_types", "params": {"types": []}}]))


def test_limits(runtime):
    with pytest.raises(LimitExceededError):  # inline sink, too many patients
        runtime.resolve(GenerationRequest(cohort={"count": 50}))
    with pytest.raises(LimitExceededError):
        runtime.resolve(GenerationRequest(cohort={"count": 10**6}, sink={"name": "zip"}))


def test_warnings_for_unsupported_filters(runtime):
    spec = runtime.resolve(GenerationRequest(cohort={"gender": "F", "count": 1}))
    assert any("cohort.gender" in w for w in spec.warnings)


# ── pipeline ──────────────────────────────────────────────────────────────
async def test_full_record_inline_is_tagged_synthetic(runtime, tmp_path):
    spec, result = await run(runtime, tmp_path, preset="full-patient", cohort={"seed": 1})
    assert result.summary["patients"] == 1
    bundle = result.inline[0]
    assert all(
        any(t["code"] == "HTEST" for t in r["meta"]["tag"]) for r in fhir.resources(bundle)
    )


async def test_same_seed_is_deterministic_and_different_seed_differs(runtime, tmp_path):
    _, a = await run(runtime, tmp_path, preset="full-patient", cohort={"seed": 7, "count": 2})
    _, b = await run(runtime, tmp_path, preset="full-patient", cohort={"seed": 7, "count": 2})
    _, c = await run(runtime, tmp_path, preset="full-patient", cohort={"seed": 8, "count": 2})
    assert a.inline == b.inline
    assert a.inline != c.inline
    ids = [r["id"] for bundle in a.inline for r in fhir.resources(bundle) if r["resourceType"] == "Patient"]
    assert len(set(ids)) == 2  # cycled fixtures still produce distinct patients


async def test_references_stay_consistent_after_id_remap(runtime, tmp_path):
    _, r = await run(
        runtime, tmp_path, shape=[{"slicer": "full_record", "params": {"include_infrastructure": True}}],
        cohort={"seed": 3, "count": 2}, options={"check_references": True},
    )
    assert r.summary["resources"]["Practitioner"] >= 1  # infra merged in
    for bundle in r.inline:
        assert fhir.dangling_references(bundle) == []


async def test_dangling_references_detected_without_infra(runtime, tmp_path):
    spec = runtime.resolve(
        GenerationRequest(options={"check_references": True}, cohort={"seed": 1})
    )
    from app.generator.errors import GenerationFailedError

    with pytest.raises(GenerationFailedError):
        await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")


async def test_resource_types_slicer(runtime, tmp_path):
    _, r = await run(
        runtime, tmp_path, cohort={"count": 2},
        shape=[{"slicer": "resource_types", "params": {"types": ["Observation"]}}],
    )
    assert set(r.summary["resources"]) == {"Patient", "Observation"}


async def test_redact_and_limit_compose(runtime, tmp_path):
    _, r = await run(
        runtime, tmp_path, cohort={"count": 2},
        shape=[{"slicer": "redact_infra"}, {"slicer": "limit", "params": {"max_bundles": 1}}],
    )
    assert r.summary["bundles"] == 1
    assert "Claim" not in r.summary["resources"]


async def test_ndjson_sink_writes_one_file_per_type(runtime, tmp_path):
    _, r = await run(runtime, tmp_path, cohort={"count": 2}, sink={"name": "ndjson"})
    names = {a.filename for a in r.artifacts}
    assert {"Patient.ndjson", "Observation.ndjson"} <= names
    patients = (tmp_path / "out" / "Patient.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(patients) == 2 and json.loads(patients[0])["resourceType"] == "Patient"


async def test_zip_sink(runtime, tmp_path):
    _, r = await run(runtime, tmp_path, cohort={"count": 3}, sink={"name": "zip"})
    with zipfile.ZipFile(r.artifacts[0].path) as zf:
        assert len(zf.namelist()) == 3


def test_contained_fragment_and_external_references_are_not_dangling():
    bundle = fhir.make_bundle(
        [
            {"fullUrl": "urn:uuid:a", "resource": {"resourceType": "Patient", "id": "a"}},
            {
                "fullUrl": "urn:uuid:b",
                "resource": {
                    "resourceType": "Claim",
                    "id": "b",
                    "patient": {"reference": "urn:uuid:a"},
                    "insurance": [{"coverage": {"reference": "#coverage"}}],
                    "provider": {"reference": "https://example.org/fhir/Organization/1"},
                    "enterer": {"reference": "Practitioner/missing"},
                },
            },
        ]
    )
    assert fhir.dangling_references(bundle) == ["Practitioner/missing"]


async def test_provenance_records_what_each_stage_let_through(runtime, tmp_path):
    _, result = await run(
        runtime, tmp_path, shape=[{"slicer": "resource_types", "params": {"types": ["Condition"]}}]
    )
    stages = result.provenance["stages"]
    assert [s["stage"] for s in stages] == ["static_fixtures", "resource_types"]
    assert stages[0]["resources"] > stages[1]["resources"] > 0, "the slicer kept fewer resources than the connector made"
    assert set(stages[1]["by_type"]) <= {"Patient", "Condition"}
