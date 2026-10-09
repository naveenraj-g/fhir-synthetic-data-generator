from fastapi import Query
from pydantic import BaseModel

from app.core.config import settings


class ListParams(BaseModel):
    """Shared pagination dependency for list endpoints — one place to
    change defaults/limits instead of declaring limit/offset inline on
    every route."""

    limit: int = settings.pagination.default_limit
    offset: int = 0


def list_params(
    limit: int = Query(settings.pagination.default_limit, ge=1, le=settings.pagination.max_limit),
    offset: int = Query(0, ge=0),
) -> ListParams:
    return ListParams(limit=limit, offset=offset)
