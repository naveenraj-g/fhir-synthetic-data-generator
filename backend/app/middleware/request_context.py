import uuid

from app.core.request_context import request_id_var


async def request_context_middleware(request, call_next):
    """Outermost-but-one context: establishes request_id before anything
    else logs, so every line for this request can be correlated. Set here
    (not inside a route) so it reaches every middleware below it too —
    see app/core/request_context.py's module docstring for why the
    reverse isn't true for actor identity."""
    request_id = str(uuid.uuid4())
    request_id_var.set(request_id)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
