"""Central role and object-level authorization policy."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    AUDITOR = "AUDITOR"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    CASE_READ = "CASE_READ"
    CASE_CLAIM = "CASE_CLAIM"
    CASE_TRANSITION = "CASE_TRANSITION"
    WORKFLOW_MANAGE = "WORKFLOW_MANAGE"
    WORKFLOW_COMPLETE = "WORKFLOW_COMPLETE"
    ACTIVITY_READ = "ACTIVITY_READ"


class AuthorizationError(PermissionError):
    pass


_GRANTS = {
    Role.ADMIN: frozenset(Permission),
    Role.AUDITOR: frozenset(
        {Permission.CASE_READ, Permission.CASE_CLAIM, Permission.CASE_TRANSITION,
         Permission.WORKFLOW_COMPLETE, Permission.ACTIVITY_READ}
    ),
    Role.REVIEWER: frozenset(
        {Permission.CASE_READ, Permission.CASE_TRANSITION,
         Permission.WORKFLOW_COMPLETE, Permission.ACTIVITY_READ}
    ),
    Role.VIEWER: frozenset({Permission.CASE_READ, Permission.ACTIVITY_READ}),
}


def authorize(
    roles: frozenset[Role],
    permission: Permission,
    *,
    actor_id: str,
    object_owner_id: str | None = None,
    require_different_actor: bool = False,
) -> None:
    if not any(permission in _GRANTS[role] for role in roles):
        raise AuthorizationError(f"{permission.value} permission is required")
    if require_different_actor and object_owner_id == actor_id:
        raise AuthorizationError("maker cannot approve their own sensitive action")
