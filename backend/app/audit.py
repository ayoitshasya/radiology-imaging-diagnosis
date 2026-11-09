"""Write audit events. The table is append-only; there is deliberately no update helper."""

from __future__ import annotations

from typing import Literal, get_args

from sqlalchemy.orm import Session

from backend.app.models import AuditLog

EventType = Literal[
    "study_synced",
    "analysis_completed",
    "analysis_returned_cached",
    "review_submitted",
    "demo_reset",  # scripts/reset_demo_state.py: records what a demo reset deleted
]
EVENT_TYPES: tuple[str, ...] = get_args(EventType)


def record_event(
    session: Session, event_type: str, study_instance_uid: str | None, detail: dict
) -> None:
    """Add an audit row to the caller's transaction.

    Adding it to the same transaction as the change it describes means both are committed
    together or not at all. ``detail`` must never contain patient identifiers or
    reviewer free text.

    Raises:
        ValueError: For an event type not in EVENT_TYPES, so the /audit filter always
            knows every type that can be written.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown audit event type: {event_type}")
    session.add(
        AuditLog(event_type=event_type, study_instance_uid=study_instance_uid, detail=detail)
    )
