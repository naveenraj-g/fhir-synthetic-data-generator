from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.di.dependencies.generation import get_catalog_service, get_generation_service
from app.generator.spec import GenerationRequest
from app.schemas.generation import (
    ComponentInfo,
    ConnectorHealthResponse,
    ConnectorInfo,
    GenerationResultResponse,
    PlacesResponse,
    PresetInfo,
    TermSearchResponse,
)
from app.services.catalog_service import CatalogService
from app.services.generation_service import GenerationService

router = APIRouter(tags=["Catalog"])


@router.get("/connectors", operation_id="list_connectors", response_model=list[ConnectorInfo],
            summary="Configured connectors and what each supports natively")
async def list_connectors(catalog: CatalogService = Depends(get_catalog_service)):
    return catalog.connectors()


@router.get("/connectors/{name}/health", operation_id="connector_health",
            response_model=ConnectorHealthResponse, summary="Is the connector usable right now?")
async def connector_health(name: str, catalog: CatalogService = Depends(get_catalog_service)):
    return await catalog.connector_health(name)


@router.get(
    "/connectors/{name}/terms",
    operation_id="search_terms",
    response_model=TermSearchResponse,
    summary="Find the codes to target: search the conditions, procedures, medications... a connector can produce",
    description="Cohorts are targeted by code. Search by words (`q=colonoscopy`, `q=reflux`) and optionally `kind` "
    "(condition, procedure, medication, observation, allergy, immunization, device, diagnostic_report); paste the "
    "`reference` of the hits into `cohort.conditions` / `cohort.procedures`. The first call per Synthea image "
    "takes a few seconds while the index is built, then it is cached.",
)
async def search_terms(
    name: str,
    q: str | None = Query(None, description="Words to look for in the term name, its code, or its Synthea module"),
    kind: str | None = Query(None),
    limit: int = Query(25, ge=1, le=200),
    catalog: CatalogService = Depends(get_catalog_service),
):
    return await catalog.search_terms(name, q, kind, limit)


@router.get(
    "/connectors/{name}/places",
    operation_id="list_places",
    response_model=PlacesResponse,
    summary="The states, or the cities of one state, a connector can generate people in",
    description="Without `state`: the valid state names. With `state` (any capitalisation): that state's valid city "
    "names. `cohort.state` and `cohort.city` must be one of these (capitalisation is corrected automatically).",
)
async def list_places(
    name: str,
    state: str | None = Query(None, description="Return this state's cities instead of the list of states"),
    catalog: CatalogService = Depends(get_catalog_service),
):
    return await catalog.places(name, state)


@router.get("/resource-groups", operation_id="list_resource_groups",
            summary="Named categories of resource types usable in the resource_types slicer (clinical, financial, administrative...)")
async def list_resource_groups(catalog: CatalogService = Depends(get_catalog_service)) -> dict[str, list[str]]:
    return catalog.resource_groups()


@router.get("/slicers", operation_id="list_slicers", response_model=list[ComponentInfo],
            summary="Available slicers with their parameter schemas")
async def list_slicers(catalog: CatalogService = Depends(get_catalog_service)):
    return catalog.slicers()


@router.get("/sinks", operation_id="list_sinks", response_model=list[ComponentInfo],
            summary="Configured sinks with their parameter schemas")
async def list_sinks(catalog: CatalogService = Depends(get_catalog_service)):
    return catalog.sinks()


@router.get("/specialties", operation_id="list_specialties",
            summary="Configured specialties (named module groups)")
async def list_specialties(catalog: CatalogService = Depends(get_catalog_service)) -> dict:
    return catalog.specialties()


@router.get("/presets", operation_id="list_presets", response_model=list[PresetInfo],
            summary="Preset catalogue")
async def list_presets(catalog: CatalogService = Depends(get_catalog_service)):
    return catalog.presets()


@router.get("/presets/{name}", operation_id="get_preset", response_model=PresetInfo,
            summary="One preset")
async def get_preset(name: str, catalog: CatalogService = Depends(get_catalog_service)):
    return catalog.preset(name)


@router.post("/presets/{name}/run", operation_id="run_preset", response_model=GenerationResultResponse,
             summary="Run a preset, optionally with overrides",
             description="Shorthand for POST /generations with `preset` set to the path name.")
async def run_preset(
    name: str,
    overrides: GenerationRequest | None = None,
    service: GenerationService = Depends(get_generation_service),
):
    request = (overrides or GenerationRequest()).model_copy(update={"preset": name})
    response, completed_inline = await service.submit(request)
    return JSONResponse(
        status_code=status.HTTP_200_OK if completed_inline else status.HTTP_202_ACCEPTED,
        content=jsonable_encoder(response),
    )
