from dependency_injector.wiring import Provide, inject
from fastapi import Depends

from app.di.container import Container
from app.services.catalog_service import CatalogService
from app.services.generation_service import GenerationService


@inject
def get_generation_service(
    service: GenerationService = Depends(Provide[Container.generation.generation_service]),
) -> GenerationService:
    return service


@inject
def get_catalog_service(
    service: CatalogService = Depends(Provide[Container.generation.catalog_service]),
) -> CatalogService:
    return service
