"""Structured logging: one JSON object per line, with `trace_methods` — a
class decorator that makes every public async method on a service/
repository class announce itself (INFO) and, at DEBUG, log its call args
plus a completion line with duration_ms and the result type, with zero
logging code in the method body itself.

Two levels in practice:
- INFO (default/production): the call chain and nothing more — one line
  per method call, naming it, plus whatever business-event lines you add
  by hand in route handlers.
- DEBUG: the same chain plus call_args, duration_ms, result types, and
  (if logging.sql_echo is on) every SQL statement.
"""

import functools
import inspect
import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.request_context import actor_org_id_var, actor_user_id_var, request_id_var

# Keys that collide with logging.LogRecord's own attributes raise
# `KeyError: Attempt to overwrite 'x' in LogRecord` from
# logging.makeRecord() if passed through `extra={...}`. This is why the
# trace decorator below emits `call_args`, not `args`.
_RESERVED_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # Not self.formatTime(record, "...%f"): it goes through time.strftime, which has no %f (microseconds) -
            # an error on Windows, a literal "%f" on Linux. ISO-8601 UTC with milliseconds works everywhere.
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        actor_user_id = actor_user_id_var.get()
        if actor_user_id:
            payload["actor_user_id"] = actor_user_id
        actor_org_id = actor_org_id_var.get()
        if actor_org_id:
            payload["actor_org_id"] = actor_org_id

        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_") or key in payload:
                continue
            if key in ("msg", "args"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("[%(levelname)s] %(name)s: %(message)s")


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.logging.level)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if settings.logging.format == "json" else ConsoleFormatter()
    )
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").propagate = settings.logging.uvicorn_access


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_payload(logger: logging.Logger, event: str, payload) -> None:
    """Logs a request payload at DEBUG — no-ops unless both
    logging.debug_payloads is on AND the logger is DEBUG-enabled, so it's
    free in production. Masks any key in logging.redact (case-insensitive,
    at any nesting depth) even when it is on.
    """
    if not settings.logging.debug_payloads or not logger.isEnabledFor(logging.DEBUG):
        return
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload
    logger.debug(event, extra={"event": event, "payload": _redact(data)})


def _redact(data):
    redact_keys = {k.lower() for k in settings.logging.redact}
    if isinstance(data, dict):
        return {
            k: ("***" if k.lower() in redact_keys else _redact(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact(v) for v in data]
    return data


def trace_methods(cls):
    """Class decorator: wraps every public async method (not starting with
    `_`) across the whole MRO with call-announcement + timing logging.

    Reads parameter names from `fn.__code__.co_varnames`, NOT
    `inspect.signature()`/`get_type_hints()` — under PEP 649 (Python 3.14),
    annotations evaluate lazily, and a method literally named `list` with
    a `list[...]`-annotated parameter resolves `list` to the method itself
    inside its own class body, raising
    `TypeError: 'function' object is not subscriptable`. Reading
    `co_varnames` sidesteps evaluating annotations at all.
    """
    component = cls.__name__
    logger = get_logger(f"{cls.__module__}.{cls.__name__}")

    for attr_name in list(vars(cls)) + [
        a for base in cls.__mro__[1:] for a in vars(base) if not a.startswith("_")
    ]:
        if attr_name.startswith("_"):
            continue
        fn = cls.__dict__.get(attr_name) or getattr(cls, attr_name, None)
        if not (inspect.isfunction(fn) or inspect.iscoroutinefunction(fn)):
            continue
        if not inspect.iscoroutinefunction(fn):
            continue

        @functools.wraps(fn)
        async def wrapper(self, *args, __fn=fn, __name=attr_name, **kwargs):
            if not logger.isEnabledFor(logging.INFO):
                return await __fn(self, *args, **kwargs)

            debug = logger.isEnabledFor(logging.DEBUG)
            extra = {"event": f"{component}.{__name}", "component": component, "method": __name}
            if debug:
                varnames = __fn.__code__.co_varnames[: __fn.__code__.co_argcount]
                call_args = dict(zip(varnames[1:], args))
                call_args.update(kwargs)
                extra["call_args"] = {k: v for k, v in call_args.items()}

            logger.info(f"{component}.{__name}", extra=extra)
            t0 = time.perf_counter()
            result = await __fn(self, *args, **kwargs)
            if debug:
                logger.debug(
                    f"{component}.{__name} ok",
                    extra={
                        "event": f"{component}.{__name}.ok",
                        "component": component,
                        "method": __name,
                        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                        "result_type": type(result).__name__,
                    },
                )
            return result

        setattr(cls, attr_name, wrapper)

    return cls
