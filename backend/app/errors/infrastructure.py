from app.errors.base import ApplicationError


class DatabaseError(ApplicationError):
    def __init__(self, message: str = "Database error"):
        super().__init__(
            name="DatabaseError", message=message, status_code=500, code="DATABASE_ERROR"
        )
