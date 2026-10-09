from dataclasses import dataclass


@dataclass
class AuthUser:
    """Verified-JWT identity, resolved once by get_current_user and handed
    to route dependencies — never re-decode the token downstream."""

    sub: str
    org_id: str | None
    permissions: list[str]
