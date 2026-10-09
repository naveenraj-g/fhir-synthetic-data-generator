import json

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response

from app.core.logging import get_logger
from app.core.pagination import ListParams, list_params
from app.di.dependencies.generation import get_generation_service
from app.generator.spec import GenerationRequest
from app.schemas.generation import (
    BundleIndexResponse,
    GenerationResultResponse,
    JobResponse,
    PaginatedJobResponse,
    PreviewResponse,
)
from app.services.generation_service import GenerationService

router = APIRouter(prefix="/generations", tags=["Generations"])
logger = get_logger(__name__)

_NOT_FOUND = {404: {"description": "Generation or artifact not found"}}


@router.post(
    "/",
    operation_id="create_generation",
    summary="Generate synthetic FHIR data",
    description="Submit a spec (a preset, a full spec, or a preset plus overrides). With the "
    "`inline` sink the bundles come back in `data` (200); with any file sink a job is queued "
    "(202) — poll `GET /generations/{id}` and download from its `artifacts`.",
    response_model=GenerationResultResponse,
    responses={202: {"model": GenerationResultResponse, "description": "Job queued"}},
)
async def create_generation(
    payload: GenerationRequest,
    service: GenerationService = Depends(get_generation_service),
):
    response, completed_inline = await service.submit(payload)
    logger.info(
        "Generation submitted",
        extra={"event": "route.create_generation", "job_id": response.id, "inline": completed_inline},
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if completed_inline else status.HTTP_202_ACCEPTED,
        content=jsonable_encoder(response),
    )


@router.post(
    "/preview",
    operation_id="preview_generation",
    summary="Validate and resolve a spec without running it",
    response_model=PreviewResponse,
)
async def preview_generation(
    payload: GenerationRequest,
    service: GenerationService = Depends(get_generation_service),
):
    return await service.preview(payload)


@router.get(
    "/",
    operation_id="list_generations",
    summary="List generation jobs",
    response_model=PaginatedJobResponse,
)
async def list_generations(
    status_filter: str | None = Query(
        None, alias="status", pattern="^(queued|running|succeeded|failed|expired)$"
    ),
    params: ListParams = Depends(list_params),
    service: GenerationService = Depends(get_generation_service),
):
    jobs, total = await service.list_jobs(
        status=status_filter, limit=params.limit, offset=params.offset
    )
    return PaginatedJobResponse(
        total=total,
        limit=params.limit,
        offset=params.offset,
        data=[service.to_response(j) for j in jobs],
    )


@router.get(
    "/{job_id}",
    operation_id="get_generation",
    summary="Get a generation job (status, provenance, artifacts)",
    response_model=JobResponse,
    responses=_NOT_FOUND,
)
async def get_generation(
    job_id: str, service: GenerationService = Depends(get_generation_service)
):
    return service.to_response(await service.get_job(job_id))


@router.get(
    "/{job_id}/artifacts/{artifact_id}",
    operation_id="download_generation_artifact",
    summary="Download one artifact produced by a generation",
    responses={200: {"content": {"application/octet-stream": {}}}, **_NOT_FOUND},
)
async def download_artifact(
    job_id: str,
    artifact_id: str,
    service: GenerationService = Depends(get_generation_service),
):
    path, artifact = await service.get_artifact_path(job_id, artifact_id)
    return FileResponse(path, media_type=artifact["content_type"], filename=artifact["filename"])


@router.get(
    "/{job_id}/bundles",
    operation_id="list_generation_bundles",
    summary="The bundles of a finished generation (one line each: patient and resource counts)",
    description="Reads the stored files (JSON, ZIP or NDJSON) so a viewer can draw the data. 410 once the files expire.",
    response_model=BundleIndexResponse,
    responses=_NOT_FOUND,
)
async def list_bundles(job_id: str, service: GenerationService = Depends(get_generation_service)):
    return await service.bundle_index(job_id)


@router.get(
    "/{job_id}/bundles/{index}",
    operation_id="get_generation_bundle",
    summary="One FHIR bundle of a finished generation, whole",
    responses=_NOT_FOUND,
)
async def get_bundle(job_id: str, index: int, service: GenerationService = Depends(get_generation_service)):
    bundle = await service.get_bundle(job_id, index)
    # Serialised directly: a big record is tens of MB, and returning the dict would make FastAPI walk and re-encode all of it.
    return Response(content=json.dumps(bundle, separators=(",", ":")), media_type="application/json")


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_generation",
    summary="Delete a generation job and its artifacts",
    responses=_NOT_FOUND,
)
async def delete_generation(
    job_id: str, service: GenerationService = Depends(get_generation_service)
):
    await service.delete_job(job_id)
    return None
