import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.transactions import router as transactions_router
from app.config import get_settings
from app.core.errors import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from app.core.logging import request_id_ctx, setup_logging
from app.schemas.common import ApiResponse, HealthStatus

settings = get_settings()
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context for startup and shutdown hooks."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("AuditForge API starting up", extra={"environment": settings.ENVIRONMENT})
    yield
    logger.info("AuditForge API shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# App state
app.state.debug = settings.DEBUG

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://frontend:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register custom exception handlers for uniform envelopes
app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, generic_exception_handler)


@app.middleware("http")
async def request_id_and_logging_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware attaching X-Request-ID, setting log context, and recording request duration."""
    req_id = request.headers.get("X-Request-ID")
    if not req_id or not req_id.strip():
        req_id = uuid.uuid4().hex

    request.state.request_id = req_id
    token = request_id_ctx.set(req_id)

    start_time = time.perf_counter()
    try:
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = req_id

        # Skip spamming logs for standard root/doc checks if debug is off
        logger.info(
            "HTTP request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else "unknown",
            },
        )
        return response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(
            "HTTP request failed with unhandled exception",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
                "error": str(exc),
            },
            exc_info=True,
        )
        raise exc
    finally:
        request_id_ctx.reset(token)


# Register API Routers
app.include_router(ingestion_router, prefix=settings.API_V1_PREFIX)
app.include_router(transactions_router, prefix=settings.API_V1_PREFIX)


@app.get(
    f"{settings.API_V1_PREFIX}/health",
    response_model=ApiResponse[HealthStatus],
    tags=["System"],
    status_code=status.HTTP_200_OK,
)
async def api_health(request: Request) -> ApiResponse[HealthStatus]:
    """Health check endpoint per PRD specification."""
    req_id = getattr(request.state, "request_id", "unknown-request-id")
    data = HealthStatus(
        status="ok",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        timestamp=datetime.now(UTC).isoformat(),
        db_backend=settings.DB_BACKEND,
    )
    return ApiResponse(data=data, meta={}, request_id=req_id)


@app.get("/health", include_in_schema=False)
async def docker_health_probe() -> dict[str, str]:
    """Lightweight root health probe for Docker compose / orchestrator liveness checks."""
    return {"status": "ok"}

