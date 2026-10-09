from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class AppConfig(BaseModel):
    """App metadata + interactive-docs exposure."""

    title: str = "FHIR Synthetic Data Generator"
    version: str = "0.1.0"

    # Gates /docs, /redoc, /docs/scalar. /openapi.json itself is never
    # gated — keep it reachable regardless of whether the human-facing UI
    # is turned off (e.g. for tooling that reads the spec directly).
    docs_enabled: bool = True


class CorsConfig(BaseModel):
    """No CORSMiddleware is registered at all while `enabled` is false (the
    default). Never use `allow_origins: ["*"]` together with
    `allow_credentials: true` — browsers reject that combination outright."""

    enabled: bool = False
    allow_origins: list[str] = Field(default_factory=list)
    allow_credentials: bool = False
    allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    allow_headers: list[str] = Field(default_factory=lambda: ["*"])

    @model_validator(mode="after")
    def _reject_wildcard_with_credentials(self) -> "CorsConfig":
        if self.allow_credentials and "*" in self.allow_origins:
            raise ValueError(
                "cors.allow_credentials cannot be true while cors.allow_origins "
                "includes '*' — browsers reject that combination outright. "
                "List explicit origins instead."
            )
        return self


class AuthConfig(BaseModel):
    # Algorithms PyJWT will accept when verifying a token's signature (see
    # app/auth/dependencies.py). Must match whatever your IAM/JWKS endpoint
    # actually signs with. Auth is optional — see app/auth/README notes;
    # routes that don't depend on get_current_user ignore this entirely.
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])


class DatabaseConfig(BaseModel):
    """SQLAlchemy async engine pool sizing. Defaults match SQLAlchemy's own
    (pool_size/max_overflow) except pool_pre_ping, which is turned on so a
    connection the DB or a proxy silently dropped is caught and replaced at
    checkout instead of surfacing as a mid-request error."""

    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True
    pool_recycle: int = 1800


class RedisConfig(BaseModel):
    """Global Redis on/off switch — lives in config.yaml, not cache.yaml,
    deliberately: Redis isn't only used for caching (it can back sessions,
    rate limiting coordination, etc.), so whether it's available at all is
    an infra-level decision, not a caching-feature one.

    `enabled: false` forces every Redis-backed dependent (rate limiting,
    the example cache backend, anything Redis-backed added later) to its
    non-Redis fallback — see Settings._apply_redis_switch() below —
    regardless of what that dependent's own backend field says.
    """

    enabled: bool = True


class RateLimitConfig(BaseModel):
    """Also lives in config.yaml, not cache.yaml: it's Redis-backed, but it
    isn't a cache — it's a shared sliding-window counter enforcing a
    request quota, not something stored to avoid re-fetching it."""

    # "redis" (coordinated across instances) or "memory" (per-process, no
    # cross-instance coordination). Only consulted when the global
    # `redis.enabled` switch above is true — forced to "memory" otherwise.
    backend: Literal["redis", "memory"] = "redis"
    read_limit: int = 100
    write_limit: int = 20
    window_seconds: int = 60


class ExampleCacheConfig(BaseModel):
    """Stand-in for "the thing your app actually caches" — demonstrates
    the two-level backend-selection pattern. Replace/rename this with your
    own real cache config (e.g. a lookup table, computed aggregates, an
    external API response) as your app grows; this is deliberately the
    *only* entry in cache.yaml in this starter kit, so the split is
    visible without being overbuilt.

    "redis" (shared across instances) or "memory" (per-process). Forced to
    "memory" whenever the global `redis.enabled` switch is false, same as
    rate_limit.backend."""

    backend: Literal["redis", "memory"] = "redis"


class PaginationConfig(BaseModel):
    """Defaults for the shared pagination dependency (app/core/pagination.py)."""

    default_limit: int = 50
    max_limit: int = 200


class RoutesConfig(BaseModel):
    # Which resource routers get mounted, by module name under
    # app/routers/. Not listed = not mounted. See
    # app/routers/__init__.py's discover_routers() and app/main.py's
    # mount_routers() — toggle a resource on/off with a one-line config
    # edit + restart, no code change.
    enabled: list[str] = Field(default_factory=lambda: ["generations", "catalog"])


class LogConfig(BaseModel):
    """Observability config — consumed by app.core.logging.setup_logging(),
    app.middleware.access_log, and app.core.database's query listeners."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "console"] = "json"

    # Matched case-insensitively — `format: JSON` / `level: debug` both
    # work, since these are the two settings people hand-edit most and a
    # pydantic literal_error at import time over casing is a miserable
    # first experience.
    @field_validator("level", "format", mode="before")
    @classmethod
    def _normalise_case(cls, v):
        if isinstance(v, str):
            return v.upper() if v.upper() in _LOG_LEVELS else v.lower()
        return v

    # Logs full request payloads at DEBUG via log_payload(). Off by
    # default — turn on only for local debugging, never in production,
    # especially if your payloads ever carry sensitive data.
    debug_payloads: bool = False

    slow_query_ms: int = 500
    sql_echo: bool = False
    uvicorn_access: bool = False

    redact: list[str] = Field(
        default_factory=lambda: ["authorization", "token", "password", "secret"]
    )


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    # Defaults to a local SQLite file so `uv sync && just dev` works with no setup;
    # set a postgresql+asyncpg:// URL for real deployments.
    DATABASE_URL: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'data' / 'app.db').as_posix()}"

    # Generator config + where job artifacts/scratch space live (relative paths
    # resolve against backend/, not the CWD).
    CONNECTORS_CONFIG_PATH: str = "configs/synthetic_data_connectors.yaml"
    ARTIFACTS_DIR: str = "data/artifacts"
    WORK_DIR: str = "data/tmp"
    # Optional — only required when redis.enabled is true (the default).
    REDIS_URL: str | None = None

    # JWT/JWKS verification — only required if you actually wire
    # app.auth.dependencies.get_current_user onto a route. See
    # app/auth/README notes.
    JWKS_URL: str | None = None
    JWT_ISSUER: str | None = None

    app: AppConfig = Field(default_factory=AppConfig)
    cors: CorsConfig = Field(default_factory=CorsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    example_cache: ExampleCacheConfig = Field(default_factory=ExampleCacheConfig)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    routes: RoutesConfig = Field(default_factory=RoutesConfig)
    logging: LogConfig = Field(default_factory=LogConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else BACKEND_DIR / path

    @model_validator(mode="after")
    def _apply_redis_switch(self) -> "Settings":
        """When Redis is globally disabled, force every dependent's backend
        to its non-Redis fallback here — once — so nothing downstream
        needs to know the global switch exists; it just reads its own
        already-resolved backend field."""
        if not self.redis.enabled:
            self.rate_limit.backend = "memory"
            self.example_cache.backend = "memory"
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Precedence, highest first: real env var > `.env` >
        `configs/config.yaml` + `configs/cache.yaml` > field defaults.
        `.env` stays reserved for true per-environment secrets (DB/Redis/
        JWKS URLs); everything else is checked-in application behavior
        that lives in those two YAML files instead. They're two peer
        sources at the same precedence tier, not a fallback chain between
        them: config.yaml carries general app-behavior settings (including
        the global `redis` switch and `rate_limit`, neither of which is a
        cache), cache.yaml carries only genuine caching settings
        (`example_cache`). Their top-level keys never overlap, so load
        order between the two doesn't matter.

        A future secrets-manager source (AWS Secrets Manager, SSM, etc.)
        would slot into this same tuple the same way — no changes needed
        anywhere that reads `settings.*`.
        """
        # yaml_file_encoding is explicit because the source otherwise opens
        # the file with the platform default (cp1252 on Windows), which
        # fails on any non-ASCII byte in the committed config.
        yaml_settings = YamlConfigSettingsSource(
            settings_cls,
            yaml_file="configs/config.yaml",
            yaml_file_encoding="utf-8",
        )
        cache_yaml_settings = YamlConfigSettingsSource(
            settings_cls,
            yaml_file="configs/cache.yaml",
            yaml_file_encoding="utf-8",
        )
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            yaml_settings,
            cache_yaml_settings,
            file_secret_settings,
        )


settings = Settings()
