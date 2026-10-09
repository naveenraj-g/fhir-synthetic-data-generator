"""Errors raised by the generator library. Deliberately independent of the
FastAPI layer (see plan/02-architecture.md): the web layer registers one
handler for GeneratorError that renders the standard error envelope."""


class GeneratorError(Exception):
    code = "GENERATOR_ERROR"
    http_status = 500

    def __init__(self, message: str, *, details: list | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class ConfigError(GeneratorError):
    code = "CONFIG_ERROR"
    http_status = 500


class InvalidSpecError(GeneratorError):
    code = "INVALID_SPEC"
    http_status = 422


class ConnectorUnavailableError(GeneratorError):
    code = "CONNECTOR_UNAVAILABLE"
    http_status = 503


class LimitExceededError(GeneratorError):
    code = "LIMIT_EXCEEDED"
    http_status = 422


class GenerationFailedError(GeneratorError):
    code = "GENERATION_FAILED"
    http_status = 500


class UnsatisfiableCohortError(GeneratorError):
    """The connector could not produce as many matching patients as requested."""

    code = "UNSATISFIABLE_COHORT"
    http_status = 422
