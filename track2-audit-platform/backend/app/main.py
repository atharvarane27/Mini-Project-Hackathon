"""AuditForge FastAPI application factory."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.activity import create_activity_router
from app.api.v1.auth import create_auth_router
from app.api.v1.cases import create_cases_router
from app.api.v1.detectors import (
    create_circular_router,
    create_findings_router,
    create_splitting_router,
)
from app.api.v1.duplicates import create_duplicates_router
from app.api.v1.ingestion import create_ingestion_router
from app.api.v1.metrics import create_metrics_router
from app.api.v1.reconciliation import create_reconciliation_router
from app.api.v1.rules import create_rules_router
from app.api.v1.transactions import create_transactions_router
from app.api.v1.workflows import create_workflows_router
from app.config import Settings, load_settings
from app.db.session import create_database_engine
from app.runtime import RuntimeServices


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or load_settings()
    configure_logging(configured.log_level)
    logger = logging.getLogger("auditforge.api")
    app = FastAPI(title=configured.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID", "X-Actor-ID", "X-Roles"],
    )
    runtime = RuntimeServices.create(configured.demo_admin_password)
    app.state.runtime = runtime
    database_engine = (
        create_database_engine(configured)
        if configured.database_url is not None
        else None
    )
    app.state.database_engine = database_engine

    routers = [
        create_ingestion_router(runtime.ingestion, ingest=runtime.ingest_csv),
        create_transactions_router(runtime.canonical),
        create_duplicates_router(runtime.duplicates),
        create_reconciliation_router(
            repository=runtime.reconciliation,
            load_ledger=runtime.load_ledger,
            load_journals=runtime.load_journals,
            load_policy=runtime.reconciliation_policy,
        ),
        create_rules_router(service=runtime.rules),
        create_cases_router(runtime.cases, runtime.activity),
        create_workflows_router(runtime.workflows),
        create_auth_router(runtime.auth),
        create_activity_router(runtime.auth, runtime.activity),
        create_metrics_router(runtime),
    ]
    splitting_router = create_splitting_router(
        repository=runtime.splitting,
        load_policy=runtime.splitting_policy,
        load_transfers=runtime.load_transfers,
    )
    circular_router = create_circular_router(
        repository=runtime.circular,
        load_policy=runtime.circular_policy,
        load_candidates=runtime.load_cycles,
    )
    # Each detector factory exposes a standalone findings endpoint for focused
    # deployments. The composed application uses splitting as the shared empty
    # finding store until durable detector persistence is connected.
    circular_router.routes = [
        route for route in circular_router.routes
        if getattr(route, "path", "") != "/findings"
    ]
    splitting_router.routes = [
        route for route in splitting_router.routes
        if getattr(route, "path", "") != "/findings"
    ]
    routers.extend(
        (
            splitting_router,
            circular_router,
            create_findings_router(runtime.splitting, runtime.circular),
        )
    )
    for router in routers:
        app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", "").strip() or str(uuid4())
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                json.dumps({"event": "request_failed", "request_id": request_id})
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {"code": "INTERNAL_ERROR", "message": "internal error"},
                    "request_id": request_id,
                },
            )
            response.headers["X-Request-ID"] = request_id
            return response
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                {
                    "event": "request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                }
            )
        )
        return response

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        database_connected = False
        if database_engine is not None:
            try:
                with database_engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                database_connected = True
            except Exception:
                logger.exception(json.dumps({"event": "database_health_failed"}))
        return {
            "data": {
                "status": "ok",
                "service": configured.app_name,
                "environment": configured.environment,
                "database_configured": configured.database_url is not None,
                "database_connected": database_connected,
            },
            "meta": {},
        }

    return app


app = create_app()
