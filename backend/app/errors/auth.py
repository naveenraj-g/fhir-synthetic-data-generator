from app.errors.base import ApplicationError


class AuthenticationError(ApplicationError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(
            name="AuthenticationError", message=message, status_code=401, code="UNAUTHENTICATED"
        )


class PermissionDeniedError(ApplicationError):
    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            name="PermissionDeniedError", message=message, status_code=403, code="FORBIDDEN"
        )
