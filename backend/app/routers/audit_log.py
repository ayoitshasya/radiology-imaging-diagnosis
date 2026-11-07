"""Read-only access to the audit log. There are no write routes, by design."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from backend.app.audit import EventType
from backend.app.deps import SessionDep
from backend.app.models import AuditLog
from backend.app.schemas import AuditEntry, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])

MAX_PAGE = 100


def as_utc(value: datetime | None) -> datetime | None:
    """Treat a datetime without a timezone as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@router.get("", response_model=AuditPage)
def list_audit(
    session: SessionDep,
    study_instance_uid: Annotated[
        str | None,
        Query(max_length=64, pattern=r"^[0-9.]+$", description="DICOM StudyInstanceUID"),
    ] = None,
    event_type: Annotated[EventType | None, Query()] = None,
    since: Annotated[
        datetime | None, Query(description="ISO 8601; inclusive; UTC if no timezone")
    ] = None,
    until: Annotated[
        datetime | None, Query(description="ISO 8601; exclusive; UTC if no timezone")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    """Audit events filtered by study, type and time range; newest first, paginated.

    Ordered by created_at then id, so events with the same timestamp keep a stable order
    across pages. ``total`` counts all events matching the filters.
    """
    since, until = as_utc(since), as_utc(until)
    if since is not None and until is not None and since > until:
        raise HTTPException(
            422,
            detail=[
                {
                    "loc": ["query", "since"],
                    "msg": "since must not be after until",
                    "type": "value_error",
                }
            ],
        )
    filters = []
    if study_instance_uid is not None:
        filters.append(AuditLog.study_instance_uid == study_instance_uid)
    if event_type is not None:
        filters.append(AuditLog.event_type == event_type)
    if since is not None:
        filters.append(AuditLog.created_at >= since)
    if until is not None:
        filters.append(AuditLog.created_at < until)

    total = session.scalar(select(func.count(AuditLog.id)).where(*filters))
    rows = session.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        AuditEntry(
            id=r.id,
            event_type=r.event_type,
            study_instance_uid=r.study_instance_uid,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AuditPage(total=total, limit=limit, offset=offset, items=items)
