"""Paths/prefixes excluded from rate limiting and other per-request
middleware concerns — health checks and docs shouldn't count against a
caller's quota."""

EXCLUDED_PATHS = {"/health", "/health/ready", "/openapi.json"}
EXCLUDED_PREFIXES = ("/docs", "/redoc")
