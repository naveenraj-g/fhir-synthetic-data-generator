class ApplicationError(Exception):
    """Base of every application-raised error. Carries enough structure
    for app/errors/handlers.py to render a consistent JSON error envelope
    regardless of which subclass actually fired:

        {"error": {"code": str, "message": str, "details": [...]}}
    """

    def __init__(
        self,
        *,
        name: str,
        message: str,
        status_code: int,
        code: str,
        metadata: dict | None = None,
    ):
        super().__init__(message)
        self.name = name
        self.message = message
        self.status_code = status_code
        self.code = code
        self.metadata = metadata or {}
