from app.errors.base import ApplicationError


class InputValidationError(ApplicationError):
    """Raised for an application-level validation failure beyond plain
    Pydantic schema validation (FastAPI's own RequestValidationError is
    handled separately in handlers.py). `errors` is a list of
    `{"field": str, "message": str}` dicts."""

    def __init__(self, errors: list[dict]):
        super().__init__(
            name="InputValidationError",
            message="Input validation failed",
            status_code=400,
            code="INPUT_VALIDATION_ERROR",
            metadata={"errors": errors},
        )
        self.errors = errors
