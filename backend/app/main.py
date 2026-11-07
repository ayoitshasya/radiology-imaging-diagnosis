"""FastAPI application: lifespan wiring and the health endpoint.

Educational use only; not a medical device.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.db import make_engine, make_session_factory
from backend.app.inference import OverlayCache
from backend.app.model_service import ModelService, load_model_service
from backend.app.orthanc import OrthancClient, OrthancError, OrthancNotFound, OrthancUnavailable
from backend.app.routers.audit_log import router as audit_router
from backend.app.routers.reviews import router as reviews_router
from backend.app.routers.studies import router as studies_router
from backend.app.settings import Settings, get_settings

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    orthanc: OrthancClient | None = None,
    engine: Engine | None = None,
    model_service: ModelService | None = None,
) -> FastAPI:
    """Build the app. Anything not injected is created at startup and closed at shutdown.

    Injection lets tests supply a mocked Orthanc, a throwaway database and a small model
    without touching the network or real data.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or get_settings()
        owned_orthanc = orthanc is None
        owned_engine = engine is None
        app.state.settings = cfg
        app.state.orthanc = orthanc or OrthancClient(
            cfg.orthanc_url,
            cfg.orthanc_username,
            cfg.orthanc_password.get_secret_value(),
            cfg.orthanc_timeout_seconds,
        )
        app.state.engine = engine or make_engine(cfg.database_url.get_secret_value())
        app.state.session_factory = make_session_factory(app.state.engine)
        app.state.overlay_cache = OverlayCache()
        app.state.model_service, app.state.model_error = model_service, None
        if model_service is None:
            try:
                app.state.model_service = load_model_service(cfg)
            except Exception as exc:  # noqa: BLE001 - reported by /health instead of crashing
                log.exception("Model failed to load")
                app.state.model_error = f"{type(exc).__name__}: {exc}"
        yield
        if owned_orthanc:
            app.state.orthanc.close()
        if owned_engine:
            app.state.engine.dispose()

    app = FastAPI(
        title="Radiology imaging diagnosis API",
        description="Educational use only. Not for clinical use.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(OrthancError)
    def orthanc_error(request: Request, exc: OrthancError) -> JSONResponse:
        """Map Orthanc failures to 404 (not found), 503 (unreachable) or 502 (other)."""
        if isinstance(exc, OrthancNotFound):
            status = 404
        elif isinstance(exc, OrthancUnavailable):
            status = 503
        else:
            status = 502
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    app.include_router(studies_router)
    app.include_router(reviews_router)
    app.include_router(audit_router)

    @app.get("/health", tags=["health"])
    def health() -> JSONResponse:
        """Report whether Orthanc, the database and the model are usable (200) or not (503)."""
        state = app.state
        checks: dict[str, dict] = {}
        try:
            version = state.orthanc.system().get("Version")
            checks["orthanc"] = {"ok": True, "version": version}
        except OrthancError as exc:
            checks["orthanc"] = {"ok": False, "error": str(exc)}
        try:
            with state.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001 - only the type name is exposed
            checks["database"] = {"ok": False, "error": type(exc).__name__}
        service: ModelService | None = state.model_service
        if service is not None:
            checks["model"] = {
                "ok": True,
                "model_name": service.model_name,
                "checkpoint_sha256": service.checkpoint_sha256,
                "threshold": service.threshold,
            }
        else:
            checks["model"] = {"ok": False, "error": state.model_error or "not loaded"}
        healthy = all(c["ok"] for c in checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "checks": checks,
                "notice": state.settings.notice,
            },
        )

    return app


app = create_app()
