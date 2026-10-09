from fastapi import Depends

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.errors.auth import PermissionDeniedError


def require_permission(resource: str, action: str):
    """Flat `resource:action` RBAC scope check against the verified JWT's
    `permissions` claim. Usage:

        actor: AuthUser = Depends(require_permission("item", "delete"))
    """

    async def _dep(user: dict = Depends(get_current_user)) -> AuthUser:
        scope = f"{resource}:{action}"
        if scope not in user.get("permissions", []):
            raise PermissionDeniedError(f"Missing permission: {scope}")
        return AuthUser(
            sub=user["sub"], org_id=user.get("org_id"), permissions=user.get("permissions", [])
        )

    return _dep
