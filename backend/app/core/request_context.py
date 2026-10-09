"""Three ContextVars carried through every log line via the JsonFormatter
(app/core/logging.py): request_id, actor_user_id, actor_org_id.

⚠️ ContextVars propagate DOWNWARD only. Starlette's BaseHTTPMiddleware runs
the downstream app in a child anyio task that *copies* the context at
creation. So:

- request_id, set in the outermost middleware, reaches everything below
  it. OK.
- actor_user_id/actor_org_id, set in a route's auth dependency (inside
  that child task), are INVISIBLE to any middleware above it — including
  an access-log middleware that runs outside the route.

That's why bind_actor() below writes to both the ContextVar AND
request.state (backed by the shared `scope` dict, which is the same
object in both directions) — request.state is how a middleware *above*
the route can still see who the caller was. If you add another middleware
that needs request-scoped data set below it, use request.state, not a
ContextVar.
"""

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
actor_user_id_var: ContextVar[str | None] = ContextVar("actor_user_id", default=None)
actor_org_id_var: ContextVar[str | None] = ContextVar("actor_org_id", default=None)


def bind_actor(request, user_id: str | None, org_id: str | None) -> None:
    actor_user_id_var.set(user_id)
    actor_org_id_var.set(org_id)
    request.state.actor_user_id = user_id
    request.state.actor_org_id = org_id


def get_request_actor(request) -> tuple[str | None, str | None]:
    """Read actor identity the way a middleware *above* the route must —
    via request.state, not the ContextVar (see module docstring)."""
    return (
        getattr(request.state, "actor_user_id", None),
        getattr(request.state, "actor_org_id", None),
    )
