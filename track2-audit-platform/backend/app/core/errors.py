from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import ApiErrorDetail, ApiErrorResponse


class AppException(Exception):
    """Base application exception with structured code and details."""

    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "INTERNAL_ERROR",
        message: str = "An unexpected error occurred",
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class NotFoundError(AppException):
    def __init__(self, message: str = "Resource not found", details: Any = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message=message,
            details=details,
        )


class ConflictError(AppException):
    def __init__(self, message: str = "Conflict occurred", details: Any = None) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="CONFLICT",
            message=message,
            details=details,
        )


class ForbiddenError(AppException):
    def __init__(self, message: str = "Access forbidden", details: Any = None) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code="FORBIDDEN",
            message=message,
            details=details,
        )


class UnauthorizedError(AppException):
    def __init__(self, message: str = "Authentication required", details: Any = None) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
            message=message,
            details=details,
        )


def get_request_id(request: Request) -> str:
    """Helper to extract request ID from request state or fallback."""
    return getattr(request.state, "request_id", "unknown-request-id")


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom application exceptions."""
    req_id = get_request_id(request)
    body = ApiErrorResponse(
        error=ApiErrorDetail(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        ),
        request_id=req_id,
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump())


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI / Pydantic request validation errors."""
    req_id = get_request_id(request)
    body = ApiErrorResponse(
        error=ApiErrorDetail(
            code="VALIDATION_ERROR",
            message="Request input validation failed",
            details=exc.errors(),
        ),
        request_id=req_id,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=body.model_dump(),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    req_id = get_request_id(request)
    body = ApiErrorResponse(
        error=ApiErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="Internal server error",
            details={"error": str(exc)} if getattr(request.app.state, "debug", False) else None,
        ),
        request_id=req_id,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=body.model_dump(),
    )
