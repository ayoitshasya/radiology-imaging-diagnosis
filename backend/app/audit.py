"""Write audit events. The table is append-only; there is deliberately no update helper."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.models import AuditLog


def record_event(
    session: Session, event_type: str, study_instance_uid: str | None, detail: dict
) -> None:
    """Add an audit row to the caller's transaction.

    Adding it to the same transaction as the change it describes means both are committed
    together or not at all. ``detail`` must never contain patient identifiers.
    """
    session.add(
        AuditLog(event_type=event_type, study_instance_uid=study_instance_uid, detail=detail)
    )
