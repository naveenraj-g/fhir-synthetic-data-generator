import io
import zipfile

from app.di.container import container


async def _wait(client, job_id):
    await container.generation.runner().wait_all()
    return (await client.get(f"/api/v1/generations/{job_id}")).json()


async def test_inline_preset_returns_data(client):
    resp = await client.post("/api/v1/generations/", json={"preset": "full-patient", "cohort": {"seed": 5}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["summary"]["patients"] == 1
    assert body["data"][0]["resourceType"] == "Bundle"
    assert body["provenance"]["seed"] == 5
    # the job is persisted and retrievable
    got = await client.get(f"/api/v1/generations/{body['id']}")
    assert got.status_code == 200 and got.json()["status"] == "succeeded"


async def test_zip_sink_runs_async_and_downloads(client):
    resp = await client.post(
        "/api/v1/generations/", json={"cohort": {"count": 3, "seed": 1}, "sink": {"name": "zip"}}
    )
    assert resp.status_code == 202
    job = await _wait(client, resp.json()["id"])
    assert job["status"] == "succeeded"
    artifact = job["artifacts"][0]
    dl = await client.get(artifact["download_url"])
    assert dl.status_code == 200
    assert len(zipfile.ZipFile(io.BytesIO(dl.content)).namelist()) == 3


async def test_preset_run_shortcut(client):
    resp = await client.post("/api/v1/presets/vitals-only/run", json={"cohort": {"count": 2}})
    assert resp.status_code == 202
    job = await _wait(client, resp.json()["id"])
    assert {a["filename"] for a in job["artifacts"]} == {"Observation.ndjson", "Patient.ndjson"}


async def test_preview_does_not_create_a_job(client):
    resp = await client.post("/api/v1/generations/preview", json={"preset": "vitals-only"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "async"
    assert (await client.get("/api/v1/generations/")).json()["total"] == 0


async def test_invalid_spec_uses_error_envelope(client):
    resp = await client.post("/api/v1/generations/", json={"preset": "nope"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_SPEC"

    resp = await client.post("/api/v1/generations/", json={"cohort": {"count": 99}})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "LIMIT_EXCEEDED"

    resp = await client.post("/api/v1/generations/", json={"bogus": 1})
    assert resp.status_code == 422  # extra="forbid"


async def test_list_filter_and_delete(client):
    await client.post("/api/v1/generations/", json={"preset": "full-patient"})
    queued = await client.post("/api/v1/generations/", json={"cohort": {"count": 2}, "sink": {"name": "zip"}})
    await container.generation.runner().wait_all()
    listing = (await client.get("/api/v1/generations/", params={"status": "succeeded"})).json()
    assert listing["total"] == 2

    job_id = queued.json()["id"]
    assert (await client.delete(f"/api/v1/generations/{job_id}")).status_code == 204
    assert (await client.get(f"/api/v1/generations/{job_id}")).status_code == 404
    assert (await client.delete(f"/api/v1/generations/{job_id}")).status_code == 404


async def test_orphaned_jobs_are_failed_on_recovery(client):
    service = container.generation.generation_service()
    job = await service.repository.create(
        id="orphan-1", status="running", request={}, resolved_spec={}, artifacts=[]
    )
    assert await service.recover_orphans() == 1
    got = (await client.get(f"/api/v1/generations/{job.id}")).json()
    assert got["status"] == "failed" and got["error"]["code"] == "SERVER_RESTART"


async def test_catalog_endpoints(client):
    connectors = (await client.get("/api/v1/connectors")).json()
    assert {c["name"] for c in connectors} == {"static_fixtures", "synthea"}
    assert (await client.get("/api/v1/connectors/static_fixtures/health")).json()["ok"] is True
    slicers = {s["name"] for s in (await client.get("/api/v1/slicers")).json()}
    assert {"full_record", "resource_types", "limit", "redact_infra"} <= slicers
    assert {s["name"] for s in (await client.get("/api/v1/sinks")).json()} == {"inline", "zip", "ndjson", "json"}
    assert (await client.get("/api/v1/presets/full-patient")).status_code == 200
    assert (await client.get("/api/v1/presets/nope")).status_code == 422
    assert (await client.get("/health/ready")).status_code in (200, 503)


# ── Phase 4 ───────────────────────────────────────────────────────────────
async def test_expired_artifacts_are_deleted_but_metadata_is_kept(client):
    from datetime import UTC, datetime, timedelta

    from app.core.config import settings

    # One at a time: the in-memory test DB is a single shared connection, so concurrent jobs would interleave writes.
    fresh = (await client.post("/api/v1/generations/", json={"cohort": {"count": 2}, "sink": {"name": "zip"}})).json()
    await container.generation.runner().wait_all()
    old = (await client.post("/api/v1/generations/", json={"cohort": {"count": 2}, "sink": {"name": "zip"}})).json()
    await container.generation.runner().wait_all()

    service = container.generation.generation_service()
    old_dir = settings.resolve_path(settings.ARTIFACTS_DIR) / old["id"]
    fresh_dir = settings.resolve_path(settings.ARTIFACTS_DIR) / fresh["id"]
    assert (old_dir / "bundles.zip").is_file() and (fresh_dir / "bundles.zip").is_file()

    # only the job whose expiry has passed is touched
    await service.repository.update(old["id"], expires_at=datetime.now(UTC) - timedelta(minutes=1))
    assert await service.cleanup_expired() == 1
    assert await service.cleanup_expired() == 0  # idempotent

    assert not old_dir.exists() and (fresh_dir / "bundles.zip").is_file()
    job = (await client.get(f"/api/v1/generations/{old['id']}")).json()
    assert job["status"] == "expired" and job["artifacts"] == []
    assert job["summary"]["patients"] == 2 and job["provenance"]["seed"] is not None  # metadata survives
    assert (await client.get(f"/api/v1/generations/{fresh['id']}")).json()["status"] == "succeeded"

    old_url = f"/api/v1/generations/{old['id']}/artifacts/anything"
    gone = await client.get(old_url)
    assert gone.status_code == 410 and gone.json()["error"]["code"] == "ARTIFACT_EXPIRED"
    assert (await client.get("/api/v1/generations/", params={"status": "expired"})).json()["total"] == 1


async def test_term_search_endpoint_and_resource_groups(client, monkeypatch):
    from app.generator.connectors.synthea import terms
    from app.generator.connectors.synthea.connector import SyntheaConnector

    index = terms.extract_terms([("gallstones", {"states": {"S": {"type": "Procedure", "codes": [
        {"system": "SNOMED-CT", "code": "38102005", "display": "Cholecystectomy (procedure)"}]}}})])

    async def fake_index(self):
        return index

    monkeypatch.setattr(SyntheaConnector, "_term_index", fake_index)
    body = (await client.get("/api/v1/connectors/synthea/terms", params={"q": "cholecyst", "kind": "procedure"})).json()
    assert body["total"] == 1 and body["items"][0]["reference"] == "SNOMED-CT:38102005"
    assert (await client.get("/api/v1/connectors/synthea/terms", params={"kind": "nonsense"})).status_code == 422
    # a connector without an index says so
    assert (await client.get("/api/v1/connectors/static_fixtures/terms")).status_code == 422

    groups = (await client.get("/api/v1/resource-groups")).json()
    assert "Claim" in groups["financial"] and "Practitioner" in groups["administrative"] and groups["demographics"][0] == "Patient"


async def test_administrative_and_demographic_only_shapes_through_the_api(client):
    admin = await client.post(
        "/api/v1/generations/", json={"cohort": {"count": 1}, "shape": [{"slicer": "infrastructure"}], "sink": {"name": "inline"}}
    )
    assert admin.status_code == 200
    types = {e["resource"]["resourceType"] for e in admin.json()["data"][0]["entry"]}
    assert "Patient" not in types and {"Organization", "Practitioner"} <= types

    demo = await client.post(
        "/api/v1/generations/",
        json={"cohort": {"count": 2}, "shape": [{"slicer": "resource_types", "params": {"groups": ["demographics"]}}]},
    )
    assert demo.status_code == 200 and demo.json()["summary"]["resources"] == {"Patient": 2}


async def test_connector_params_roundtrip_and_are_rejected_when_unsafe(client):
    ok = await client.post(
        "/api/v1/generations/preview",
        json={"connector": "synthea", "connector_params": {"properties": {"exporter.fhir.use_us_core_ig": True}}},
    )
    assert ok.status_code == 200
    assert ok.json()["resolved_spec"]["connector_params"]["properties"]["exporter.fhir.use_us_core_ig"] is True
    bad = await client.post(
        "/api/v1/generations/preview", json={"connector": "synthea", "connector_params": {"docker_image": "evil"}}
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_SPEC"


async def test_json_delivery_runs_in_the_background_and_the_result_stays_downloadable(client):
    """The fix for "the instant result is no longer available": the result is a file kept for 72 h, so it survives a
    dropped connection, a reload, or opening the job later."""
    resp = await client.post("/api/v1/generations/", json={"cohort": {"count": 2, "seed": 3}, "sink": {"name": "json"}})
    assert resp.status_code == 202  # the request does not wait for the run
    job = await _wait(client, resp.json()["id"])
    assert job["status"] == "succeeded" and job["artifacts"][0]["filename"] == "bundles.json"
    dl = await client.get(job["artifacts"][0]["download_url"])
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("application/json")
    bundles = dl.json()
    assert isinstance(bundles, list) and len(bundles) == 2 and bundles[0]["resourceType"] == "Bundle"
    again = await client.get(f"/api/v1/generations/{job['id']}")  # still there on a later visit
    assert again.json()["artifacts"][0]["size"] == len(dl.content)


async def test_stored_results_can_be_read_back_as_bundles_for_the_flow_view(client):
    for sink in ("json", "zip"):
        resp = await client.post("/api/v1/generations/", json={"cohort": {"count": 2, "seed": 3}, "sink": {"name": sink}})
        job = await _wait(client, resp.json()["id"])
        index = await client.get(f"/api/v1/generations/{job['id']}/bundles")
        assert index.status_code == 200, sink
        body = index.json()
        assert body["count"] == 2 and body["items"][0]["resources"] > 0 and body["items"][0]["by_type"]["Patient"] == 1
        one = await client.get(f"/api/v1/generations/{job['id']}/bundles/1")
        assert one.status_code == 200 and one.json()["resourceType"] == "Bundle"
        assert (await client.get(f"/api/v1/generations/{job['id']}/bundles/2")).status_code == 404
        stages = job["provenance"]["stages"]
        assert stages[0]["resources"] >= stages[-1]["resources"] > 0
    assert (await client.get("/api/v1/generations/nope/bundles")).status_code == 404


async def test_a_cancelled_inline_request_marks_the_job_failed_not_running(client, monkeypatch):
    """If the client disconnects mid-run (a proxy timeout), the job must not stay "running" until a restart
    mislabels it SERVER_RESTART."""
    import asyncio

    from app.generator.spec import GenerationRequest

    service = container.generation.generation_service()
    spec = service.runtime.resolve(GenerationRequest())
    job = await service.repository.create(
        id="cancel-me", status="queued", request={}, resolved_spec=spec.model_dump(mode="json"), artifacts=[]
    )

    async def never_finishes(*_a, **_k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(service.runtime, "run", never_finishes)  # restored automatically after the test
    task = asyncio.create_task(service._execute(job.id, spec))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    got = (await client.get(f"/api/v1/generations/{job.id}")).json()
    assert got["status"] == "failed" and got["error"]["code"] == "REQUEST_CANCELLED"
    assert got["finished_at"] is not None
