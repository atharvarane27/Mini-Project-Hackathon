"""Session login/logout endpoints."""

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import AuthenticationError, AuthService


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


def bearer_token(header: str | None) -> str:
    if header is None or not header.startswith("Bearer ") or not header[7:].strip():
        raise AuthenticationError("Bearer session token is required")
    return header[7:].strip()


def create_auth_router(service: AuthService) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login", response_model=None)
    def login(request: LoginRequest) -> dict[str, object] | JSONResponse:
        try:
            session = service.login(request.username, request.password)
        except AuthenticationError as error:
            return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHENTICATED", "message": str(error)}})
        return {"data": {"access_token": session.token, "token_type": "bearer", "expires_at": session.expires_at.isoformat(), "roles": sorted(role.value for role in session.roles)}}

    @router.post("/auth/logout", status_code=204, response_model=None)
    def logout(authorization: str | None = Header(default=None)) -> None | JSONResponse:
        try:
            token = bearer_token(authorization)
            service.authenticate(token)
        except AuthenticationError as error:
            return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHENTICATED", "message": str(error)}})
        service.logout(token)
        return None

    return router
