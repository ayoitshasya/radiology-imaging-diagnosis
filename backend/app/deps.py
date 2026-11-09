"""FastAPI dependencies that hand out the per-app resources built in the lifespan."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request
from sqlalchemy.orm import Session

from backend.app.db import session_scope
from backend.app.inference import OverlayCache
from backend.app.model_service import ModelService
from backend.app.orthanc import OrthancClient
from backend.app.settings import Settings


def get_session(request: Request) -> Iterator[Session]:
    """A database session closed after the request."""
    yield from session_scope(request.app.state.session_factory)


def get_orthanc(request: Request) -> OrthancClient:
    """The shared Orthanc client."""
    return request.app.state.orthanc


def get_settings_dep(request: Request) -> Settings:
    """The settings the app was started with."""
    return request.app.state.settings


def get_model(request: Request) -> ModelService:
    """The loaded model, or 503 if it failed to load at startup."""
    service = request.app.state.model_service
    if service is None:
        raise HTTPException(503, detail=f"Model not loaded: {request.app.state.model_error}")
    return service


def get_overlay_cache(request: Request) -> OverlayCache:
    """The in-memory Grad-CAM overlay cache."""
    return request.app.state.overlay_cache


# Orthanc study IDs are five dash-separated hex groups; this pattern accepts them and
# rejects NUL bytes, quotes, slashes and oversized input with a 422 before any database
# or Orthanc call.
StudyId = Annotated[
    str,
    Path(
        pattern=r"^[A-Za-z0-9._-]{1,64}$",
        description="Orthanc study ID, e.g. 29aa9e33-a3c9c0ba-d412334d-8decdd60-7eedb09b",
    ),
]

# Annotated aliases, FastAPI's recommended form for declaring dependencies once.
OverlayCacheDep = Annotated[OverlayCache, Depends(get_overlay_cache)]
SessionDep = Annotated[Session, Depends(get_session)]
OrthancDep = Annotated[OrthancClient, Depends(get_orthanc)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ModelDep = Annotated[ModelService, Depends(get_model)]
