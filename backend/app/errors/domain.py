from app.errors.base import ApplicationError


class NotFoundError(ApplicationError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(
            name="NotFoundError", message=message, status_code=404, code="NOT_FOUND"
        )


class GoneError(ApplicationError):
    """The resource existed but has been deliberately removed (e.g. expired artifacts)."""

    def __init__(self, message: str, code: str = "GONE"):
        super().__init__(name="GoneError", message=message, status_code=410, code=code)


class BusinessRuleViolationError(ApplicationError):
    def __init__(self, message: str):
        super().__init__(
            name="BusinessRuleViolationError",
            message=message,
            status_code=422,
            code="BUSINESS_RULE_VIOLATION",
        )


class ResourceConflictError(ApplicationError):
    def __init__(self, message: str):
        super().__init__(
            name="ResourceConflictError",
            message=message,
            status_code=409,
            code="RESOURCE_CONFLICT",
        )
