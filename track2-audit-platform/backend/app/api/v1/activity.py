"""Authorized read-only activity ledger endpoint."""

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from app.api.v1.auth import bearer_token
from app.core.audit_writer import ActivityLedger
from app.core.auth import AuthenticationError, AuthService
from app.core.rbac import AuthorizationError, Permission, authorize


def create_activity_router(auth: AuthService, ledger: ActivityLedger) -> APIRouter:
    router = APIRouter()

    @router.get("/activity", response_model=None)
    def list_activity(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object] | JSONResponse:
        try:
            session = auth.authenticate(bearer_token(authorization))
            authorize(session.roles, Permission.ACTIVITY_READ, actor_id=session.user_id)
        except AuthenticationError as error:
            return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHENTICATED", "message": str(error)}})
        except AuthorizationError as error:
            return JSONResponse(status_code=403, content={"error": {"code": "FORBIDDEN", "message": str(error)}})
        entries = ledger.list()
        page = entries[offset : offset + limit]
        return {"data": [entry.as_dict() for entry in page], "meta": {"offset": offset, "limit": limit, "total": len(entries)}}

    return router
