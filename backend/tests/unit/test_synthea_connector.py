"""Synthea connector without Docker: flag building is pure, and generate() is exercised
with the process runner replaced by one that fabricates Synthea-shaped output."""

import json
import shutil
from pathlib import Path

import pytest

import app.generator  # noqa: F401
from app.generator.connectors.static_fixtures import BACKEND_DIR
from app.generator.connectors.synthea import connector as synthea_connector
from app.generator.connectors.synthea import flags, places as places_index
from app.generator.connectors.synthea.connector import SyntheaConnector
from app.generator.connectors.synthea.runner import ProcessResult
from app.generator.errors import (
    ConfigError,
    GenerationFailedError,
    InvalidSpecError,
    UnsatisfiableCohortError,
)
from app.generator.runtime import GeneratorRuntime
from app.generator.spec import CohortSpec, GenerationRequest

FIXTURES = BACKEND_DIR / "fixtures" / "synthea_r4"
TEST_CONFIG = BACKEND_DIR / "tests" / "connectors_test.yaml"


def args_for(cohort: CohortSpec, **kw):
    base = dict(
        reference_date="20260101",
        end_date="20260101",
        default_state="Massachusetts",
        years_of_history=10,
        properties={},
        work="/work",
        has_keep_module=False,
        modules_path=None,
        jar="/j.jar",
        jvm_args=["-Xmx2g"],
    )
    return flags.build_synthea_args(cohort, **{**base, **kw})


# ── flags ─────────────────────────────────────────────────────────────────
def test_basic_args():
    args = args_for(CohortSpec(count=5, seed=42))
    assert args[:3] == ["-Xmx2g", "-jar", "/j.jar"]
    assert args[3:13] == ["-p", "5", "-s", "42", "-cs", "42", "-r", "20260101", "-e", "20260101"]
    assert "--exporter.baseDirectory=/work/output" in args
    assert "--generate.only_alive_patients=true" in args
    assert "--exporter.years_of_history=10" in args
    assert args[-1] == "Massachusetts"  # state is the trailing positional


def test_filters_map_to_flags():
    args = args_for(
        CohortSpec(
            count=2,
            seed=1,
            gender="F",
            age_range=(40, 65),
            state="Texas",
            city="Austin",
            years_of_history=3,
            only_alive=False,
        ),
        has_keep_module=True,
        modules_path="/modules",
    )
    joined = " ".join(args)
    assert "-g F" in joined and "-a 40-65" in joined
    assert "-k /work/keep.json" in joined and "-d /modules" in joined
    assert "--exporter.years_of_history=3" in args
    assert not any("only_alive" in a for a in args)  # explicit false: don't pass the flag
    assert args[-2:] == ["Texas", "Austin"]


def test_properties_rendered_and_validated():
    args = args_for(
        CohortSpec(seed=1),
        properties={"exporter.fhir.use_us_core_ig": True, "generate.thread_pool_size": 2},
    )
    assert "--exporter.fhir.use_us_core_ig=true" in args
    assert "--generate.thread_pool_size=2" in args
    with pytest.raises(InvalidSpecError):
        flags.validate_properties({"exporter.baseDirectory": "/etc"})  # connector-managed
    with pytest.raises(InvalidSpecError):
        flags.validate_properties({"x; rm -rf /": 1})
    with pytest.raises(ConfigError):
        SyntheaConnector({"unknown_option": 1})
    with pytest.raises(InvalidSpecError):
        SyntheaConnector({"properties": {"exporter.baseDirectory": "x"}})


def test_end_date_defaults_to_reference_date_and_is_omitted_when_unpinned():
    assert "-e" not in args_for(CohortSpec(seed=1), end_date=None)


async def test_connector_pins_end_date_to_reference_date(monkeypatch, tmp_path):
    captured: list = []
    fake_synthea(monkeypatch, patients=1, capture=captured)
    conn = SyntheaConnector({"reference_date": "20260101"})
    raw = await conn.generate(CohortSpec(count=1, seed=1), tmp_path / "e")
    cmd = captured[0]
    assert cmd[cmd.index("-e") + 1] == "20260101" and raw.meta["end_date"] == "20260101"
    captured.clear()
    await SyntheaConnector({"reference_date": "20260101", "end_date": "20251231"}).generate(
        CohortSpec(count=1, seed=1), tmp_path / "e2"
    )
    assert captured[0][captured[0].index("-e") + 1] == "20251231"


def test_keep_module_combines_conditions_and_procedures_with_and():
    module = flags.build_keep_module(["44054006"], ["232717009"])
    cond = module["states"]["Initial"]["conditional_transition"][0]["condition"]
    assert cond["condition_type"] == "And" and len(cond["conditions"]) == 2
    assert [g["condition_type"] for g in cond["conditions"]] == ["Or", "Or"]
    only_proc = flags.build_keep_module([], ["232717009"])
    assert only_proc["states"]["Initial"]["conditional_transition"][0]["condition"]["condition_type"] == "Or"


def test_keep_module_matches_synthea_convention():
    module = flags.build_keep_module(["44054006", "SNOMED-CT:22298006"])
    states = module["states"]
    assert states["Keep"]["type"] == "Terminal"  # reaching a state named "Keep" keeps the patient
    first = states["Initial"]["conditional_transition"][0]
    assert first["transition"] == "Keep"
    codes = [c["codes"][0]["code"] for c in first["condition"]["conditions"]]
    assert codes == ["44054006", "22298006"] and first["condition"]["condition_type"] == "Or"
    with pytest.raises(InvalidSpecError):
        flags.build_keep_module(["not-a-code"])


# ── connector.generate with a fake process ───────────────────────────────
def fake_synthea(monkeypatch, *, returncode=0, patients=2, tail=None, capture=None):
    async def fake_run(cmd, *, timeout, on_timeout=None):
        if "inspect" in cmd:  # healthcheck: `docker image inspect <image>`
            return ProcessResult(returncode=0, tail=[])
        if capture is not None:
            capture.append(cmd)
        if returncode == 0 and patients:
            mount = next(a for a in cmd if a.startswith("type=bind"))
            work = Path(mount.split("source=")[1].split(",target")[0])
            fhir_dir = work / "output" / "fhir"
            fhir_dir.mkdir(parents=True)
            for i in range(patients):
                shutil.copy(FIXTURES / f"patient_00{(i % 2) + 1}.json", fhir_dir / f"Person{i}_{i:08d}.json")
            for kind in ("hospital", "practitioner"):
                shutil.copy(FIXTURES / f"{kind}Information.json", fhir_dir / f"{kind}Information1791527003723.json")
            (work / "output" / "metadata").mkdir()
            (work / "output" / "metadata" / "run.json").write_text(
                json.dumps({"version": "4.0.0", "javaVersion": "17"})
            )
        return ProcessResult(returncode=returncode, tail=tail or ["Records: total=2"])

    monkeypatch.setattr(synthea_connector.runner, "run_process", fake_run)


async def test_generate_reads_output_and_records_provenance(monkeypatch, tmp_path):
    captured: list = []
    fake_synthea(monkeypatch, patients=3, capture=captured)
    conn = SyntheaConnector({"reference_date": "20260101"})
    raw = await conn.generate(CohortSpec(count=2, seed=9, conditions=["44054006"]), tmp_path / "job1")
    assert len(list(raw.patient_bundles)) == 2  # trimmed to count
    assert set(raw.infra) == {"hospitalInformation", "practitionerInformation"}
    assert raw.meta["synthea_version"] == "4.0.0" and raw.meta["reference_date"] == "20260101"
    keep = json.loads((tmp_path / "job1" / "keep.json").read_text())
    assert keep["states"]["Keep"]["type"] == "Terminal"
    cmd = captured[0]
    assert cmd[:3] == ["docker", "run", "--rm"] and "fhir-gen-synthea:4.0.0" in cmd
    assert "-k" in cmd


async def test_nonzero_exit_and_empty_output_are_failures(monkeypatch, tmp_path):
    fake_synthea(monkeypatch, returncode=1, tail=["boom"])
    with pytest.raises(GenerationFailedError) as exc:
        await SyntheaConnector({}).generate(CohortSpec(seed=1), tmp_path / "a")
    assert exc.value.details == ["boom"]

    # Synthea exits 0 even when it runs out of memory (observed), so empty output must fail too.
    fake_synthea(monkeypatch, returncode=0, patients=0, tail=["java.lang.OutOfMemoryError: Java heap space"])
    with pytest.raises(GenerationFailedError) as exc:
        await SyntheaConnector({}).generate(CohortSpec(seed=1), tmp_path / "b")
    assert "out of memory" in exc.value.message


async def test_shortfall_is_reported_not_silently_returned(monkeypatch, tmp_path):
    # Observed with real Synthea: exit code 0 but fewer patients after "Failed to produce a matching patient".
    fake_synthea(
        monkeypatch,
        patients=1,
        tail=["java.lang.RuntimeException: Failed to produce a matching patient after 1000 attempts."],
    )
    with pytest.raises(UnsatisfiableCohortError) as exc:
        await SyntheaConnector({}).generate(CohortSpec(count=3, seed=5, conditions=["44054006"]), tmp_path / "s")
    assert "1 of 3" in exc.value.message and exc.value.http_status == 422
    assert "Failed to produce" in exc.value.details[0]


async def test_attempts_property_defaults_and_can_be_overridden(monkeypatch, tmp_path):
    captured: list = []
    fake_synthea(monkeypatch, patients=1, capture=captured)
    await SyntheaConnector({}).generate(CohortSpec(count=1, seed=1), tmp_path / "d1")
    assert "--generate.max_attempts_to_keep_patient=10000" in captured[0]
    captured.clear()
    conn = SyntheaConnector({"properties": {"generate.max_attempts_to_keep_patient": 50}})
    await conn.generate(CohortSpec(count=1, seed=1), tmp_path / "d2")
    assert "--generate.max_attempts_to_keep_patient=50" in captured[0]


async def test_full_pipeline_with_fake_synthea(monkeypatch, tmp_path):
    fake_synthea(monkeypatch, patients=2)
    runtime = GeneratorRuntime.from_path(TEST_CONFIG)
    spec = runtime.resolve(
        GenerationRequest(
            connector="synthea",
            cohort={"count": 2, "seed": 1, "specialty": "diabetes"},
            shape=[{"slicer": "full_record", "params": {"include_infrastructure": True}}],
        )
    )
    assert spec.cohort.conditions == ["44054006"]  # specialty expanded to condition codes
    assert spec.warnings == []  # synthea honours every field natively
    result = await runtime.run(spec, workdir=tmp_path / "w", artifact_dir=tmp_path / "o")
    assert result.summary["patients"] == 2
    assert result.provenance["synthea_version"] == "4.0.0"


def test_static_fixtures_warns_about_specialty():
    runtime = GeneratorRuntime.from_path(TEST_CONFIG)
    spec = runtime.resolve(GenerationRequest(cohort={"specialty": "diabetes"}))
    assert any("cohort.specialty" in w for w in spec.warnings)


def test_specialty_default_age_range_applies_but_never_overrides():
    runtime = GeneratorRuntime.from_path(TEST_CONFIG)
    default = runtime.resolve(GenerationRequest(connector="synthea", cohort={"specialty": "diabetes"}))
    assert default.cohort.age_range == (40, 90)
    explicit = runtime.resolve(
        GenerationRequest(connector="synthea", cohort={"specialty": "diabetes", "age_range": [20, 30]})
    )
    assert explicit.cohort.age_range == (20, 30)
    no_specialty = runtime.resolve(GenerationRequest(connector="synthea"))
    assert no_specialty.cohort.age_range is None


async def test_procedure_cohorts_export_full_history_unless_asked_otherwise(monkeypatch, tmp_path):
    captured: list = []
    fake_synthea(monkeypatch, patients=1, capture=captured)
    conn = SyntheaConnector({"reference_date": "20260101", "years_of_history": 10})
    await conn.generate(CohortSpec(count=1, seed=1, procedures=["80146002"]), tmp_path / "a")
    assert "--exporter.years_of_history=0" in captured[0]  # a kept procedure may be decades old
    captured.clear()
    await conn.generate(CohortSpec(count=1, seed=1, procedures=["80146002"], years_of_history=5), tmp_path / "b")
    assert "--exporter.years_of_history=5" in captured[0]  # explicit request wins
    captured.clear()
    await conn.generate(CohortSpec(count=1, seed=1, conditions=["44054006"]), tmp_path / "c")
    assert "--exporter.years_of_history=10" in captured[0]  # condition cohorts keep the configured window


def test_within_all_requires_every_code_for_comorbidity():
    any_mod = flags.build_keep_module(["44054006", "59621000"], within="any")
    all_mod = flags.build_keep_module(["44054006", "59621000"], within="all")
    cond = lambda m: m["states"]["Initial"]["conditional_transition"][0]["condition"]  # noqa: E731
    assert cond(any_mod)["condition_type"] == "Or" and cond(all_mod)["condition_type"] == "And"
    assert [c["codes"][0]["code"] for c in cond(all_mod)["conditions"]] == ["44054006", "59621000"]
    # within applies inside each group; match joins the groups: (diabetes AND hypertension) OR (any of these operations)
    both = flags.build_keep_module(["44054006", "59621000"], ["232717009"], match="any", within="all")["states"]["Initial"]
    top = both["conditional_transition"][0]["condition"]
    assert top["condition_type"] == "Or" and [g["condition_type"] for g in top["conditions"]] == ["And", "And"]


def test_within_is_a_request_field_and_a_specialty_default():
    runtime = GeneratorRuntime.from_path(TEST_CONFIG)
    spec = runtime.resolve(GenerationRequest(connector="synthea", cohort={"conditions": ["44054006", "59621000"], "within": "all"}))
    assert spec.cohort.within == "all" and spec.warnings == []
    assert runtime.resolve(GenerationRequest(connector="synthea", cohort={"conditions": ["44054006"]})).cohort.within == "any"


def test_medications_become_active_medication_conditions_with_rxnorm_default():
    module = flags.build_keep_module([], medications=["860975"])
    cond = module["states"]["Initial"]["conditional_transition"][0]["condition"]
    assert cond["condition_type"] == "Or"
    only = cond["conditions"][0]
    assert only["condition_type"] == "Active Medication"
    assert only["codes"][0]["system"] == "RxNorm" and only["codes"][0]["code"] == "860975"  # bare code => RxNorm, not SNOMED
    both = flags.build_keep_module(["44054006"], medications=["860975"], match="all")
    top = both["states"]["Initial"]["conditional_transition"][0]["condition"]
    assert top["condition_type"] == "And"
    assert [g["conditions"][0]["condition_type"] for g in top["conditions"]] == ["Active Condition", "Active Medication"]


async def test_medication_cohort_triggers_a_keep_module_and_is_native(monkeypatch, tmp_path):
    captured: list = []
    fake_synthea(monkeypatch, patients=1, capture=captured)
    await SyntheaConnector({}).generate(CohortSpec(count=1, seed=1, medications=["860975"]), tmp_path / "m")
    assert "-k" in captured[0]
    runtime = GeneratorRuntime.from_path(TEST_CONFIG)
    spec = runtime.resolve(GenerationRequest(connector="synthea", cohort={"medications": ["860975"]}))
    assert spec.warnings == []
    assert any("cohort.medications" in w for w in runtime.resolve(GenerationRequest(cohort={"medications": ["860975"]})).warnings)  # fixtures ignore it


async def test_a_stalled_run_is_retried_with_a_derived_seed_and_says_so(monkeypatch, tmp_path):
    calls: list = []

    async def fake_run(cmd, *, timeout, on_timeout=None):
        if "inspect" in cmd:
            return ProcessResult(returncode=0, tail=[])
        calls.append(cmd)
        if len(calls) == 1:  # the first attempt stalls (observed with real Synthea on one seed)
            return ProcessResult(returncode=-9, tail=["Waiting for threads to finish..."], timed_out=True)
        mount = next(a for a in cmd if a.startswith("type=bind"))
        work = Path(mount.split("source=")[1].split(",target")[0])
        assert not (work / "output").exists(), "partial output of the stalled attempt must be cleaned up"
        fhir_dir = work / "output" / "fhir"
        fhir_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / "patient_001.json", fhir_dir / "P_1.json")
        return ProcessResult(returncode=0, tail=["Records: total=1"])

    monkeypatch.setattr(synthea_connector.runner, "run_process", fake_run)
    # leave stale output as a stalled run would
    stale = tmp_path / "job" / "output" / "fhir"
    stale.mkdir(parents=True)
    (stale / "partial.json").write_text("{}")

    raw = await SyntheaConnector({"retries_on_timeout": 1}).generate(CohortSpec(count=1, seed=11), tmp_path / "job")
    assert len(calls) == 2
    seeds = [c[c.index("-s") + 1] for c in calls]
    assert seeds == ["11", str(11 + synthea_connector.RETRY_SEED_STEP)]
    assert raw.meta["seed"] == 11 and raw.meta["seed_used"] == 11 + synthea_connector.RETRY_SEED_STEP
    assert raw.meta["retried_after_timeout"] is True


async def test_persistent_stalls_fail_clearly_and_retries_can_be_disabled(monkeypatch, tmp_path):
    calls: list = []

    async def always_stalls(cmd, *, timeout, on_timeout=None):
        calls.append(cmd)
        return ProcessResult(returncode=-9, tail=["Waiting for threads to finish..."], timed_out=True)

    monkeypatch.setattr(synthea_connector.runner, "run_process", always_stalls)
    with pytest.raises(GenerationFailedError) as exc:
        await SyntheaConnector({"retries_on_timeout": 1}).generate(CohortSpec(count=1, seed=1), tmp_path / "a")
    assert len(calls) == 2 and "on each of 2 attempts" in exc.value.message
    calls.clear()
    with pytest.raises(GenerationFailedError):
        await SyntheaConnector({"retries_on_timeout": 0}).generate(CohortSpec(count=1, seed=1), tmp_path / "b")
    assert len(calls) == 1


# ── states and cities ─────────────────────────────────────────────────────
PLACES = {"Massachusetts": ["Boston", "Worcester"], "New York": ["Albany", "Worcester"]}


def test_places_are_read_from_the_demographics_file_in_the_jar(tmp_path):
    import zipfile

    jar = tmp_path / "synthea.jar"
    with zipfile.ZipFile(jar, "w") as zf:
        zf.writestr(
            "geography/demographics.csv",
            "ID,COUNTY,NAME,STNAME\n1,1,Worcester,Massachusetts\n2,1,boston,Massachusetts\n"
            "3,1,Worcester,New York\n4,1,Worcester,Massachusetts\n",  # a repeated row is listed once
        )
    assert places_index.read_places_from_jar(jar) == {
        "Massachusetts": ["boston", "Worcester"],
        "New York": ["Worcester"],
    }


def test_places_resolve_ignoring_case_and_suggest_when_unknown():
    assert places_index.resolve_place(PLACES, "massachusetts", "worcester") == ("Massachusetts", "Worcester")
    assert places_index.resolve_place(PLACES, " new york ", None) == ("New York", None)
    with pytest.raises(InvalidSpecError) as exc:
        places_index.resolve_place(PLACES, "Massachusets", None)
    assert "Did you mean: Massachusetts" in exc.value.details[0]
    with pytest.raises(InvalidSpecError) as exc:
        places_index.resolve_place(PLACES, "Massachusetts", "Albany")  # a city of another state
    assert "in Massachusetts" in exc.value.message


async def test_state_and_city_are_corrected_before_synthea_starts(monkeypatch, tmp_path):
    async def fake_places(self):
        return PLACES

    monkeypatch.setattr(SyntheaConnector, "_place_index", fake_places)
    captured: list = []
    fake_synthea(monkeypatch, patients=1, capture=captured)
    raw = await SyntheaConnector({}).generate(
        CohortSpec(count=1, seed=1, state="massachusetts", city="worcester"), tmp_path / "ok"
    )
    assert captured[0][-2:] == ["Massachusetts", "Worcester"]
    assert raw.meta["state"] == "Massachusetts"

    captured.clear()
    with pytest.raises(InvalidSpecError):
        await SyntheaConnector({}).generate(CohortSpec(count=1, seed=1, city="Albany"), tmp_path / "bad")
    assert captured == [], "an unknown place must fail before any container is started"
