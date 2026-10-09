from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.errors.base import ApplicationError
from app.generator.errors import GeneratorError

logger = get_logger(__name__)


def _envelope(code: str, message: str, details: list | None = None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    logger.info(
        "Application error",
        extra={
            "event": "error.application",
            "method": request.method,
            "path": request.url.path,
            "error_name": exc.name,
            "error_code": exc.code,
            "status_code": exc.status_code,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, exc.metadata.get("errors")),
    )


async def generator_error_handler(request: Request, exc: GeneratorError) -> JSONResponse:
    logger.info(
        "Generator error",
        extra={
            "event": "error.generator",
            "method": request.method,
            "path": request.url.path,
            "error_code": exc.code,
            "status_code": exc.http_status,
        },
    )
    return JSONResponse(
        status_code=exc.http_status, content=_envelope(exc.code, exc.message, exc.details)
    )


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()
    ]
    logger.info(
        "Request schema validation failed",
        extra={
            "event": "error.schema_validation",
            "method": request.method,
            "path": request.url.path,
            "errors": details,
        },
    )
    return JSONResponse(
        status_code=422,
        content=_envelope("REQUEST_VALIDATION_ERROR", "Request validation failed", details),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope("HTTP_ERROR", str(exc.detail)),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception",
        extra={"event": "error.unhandled", "method": request.method, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content=_envelope("INTERNAL_ERROR", "An unexpected error occurred"),
    )
