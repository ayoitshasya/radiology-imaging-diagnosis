"""Clear predictions, reviews and synced studies in the dev database for a clean demo.

The audit_log is append-only by design and is NEVER modified or cleared by this script.
Because existing audit events refer to prediction and review IDs that a reset deletes,
the reset appends a demo_reset event recording exactly what was removed, so the trail
explains why those rows no longer exist.

Rows are removed with DELETE, never TRUNCATE ... RESTART IDENTITY: ID counters keep
counting, so a new prediction can never reuse an ID that an old audit event refers to
(and a running server can never serve a cached heatmap for the wrong prediction).
Orthanc is not touched; POST /studies/sync registers its studies again.

Without --yes this is a dry run: it reports what would be deleted and changes nothing.

Usage:
    python scripts/reset_demo_state.py          # dry run
    python scripts/reset_demo_state.py --yes    # delete and record a demo_reset event
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.audit import record_event  # noqa: E402
from backend.app.models import AuditLog, Prediction, Review, Study  # noqa: E402
from backend.app.settings import get_settings  # noqa: E402

TABLES = (("reviews", Review), ("predictions", Prediction), ("studies", Study))
NOTICE = (
    "audit_log is append-only and is never modified or cleared; existing events stay, "
    "and a demo_reset event is appended to record this reset."
)


def summarise(session: Session) -> dict[str, dict]:
    """Row count and ID range of each table the reset clears."""
    out = {}
    for name, model in TABLES:
        n, lo, hi = session.execute(
            select(func.count(model.id), func.min(model.id), func.max(model.id))
        ).one()
        out[name] = {"rows": n, "min_id": lo, "max_id": hi}
    return out


def reset(engine: Engine) -> dict[str, dict]:
    """Delete reviews, predictions and studies and append a demo_reset event, atomically.

    Deleting in foreign-key order (reviews, then predictions, then studies) and recording
    the event in the same transaction means either everything happens or nothing does.

    Returns:
        What was deleted, per table: row count and ID range.
    """
    with Session(engine) as session:
        deleted = summarise(session)
        for _, model in TABLES:
            session.execute(delete(model))
        record_event(
            session,
            "demo_reset",
            None,
            {
                "deleted": deleted,
                "note": "Rows deleted for a clean demo. ID counters were not restarted, so "
                "IDs referenced by earlier audit events are never reused.",
            },
        )
        session.commit()
    return deleted


def main(argv: list[str] | None = None) -> int:
    """Dry run by default; --yes performs the reset."""
    p = argparse.ArgumentParser(description="Reset the demo state (not the audit log).")
    p.add_argument("--yes", action="store_true", help="confirm: actually delete the rows")
    args = p.parse_args(argv)

    url = make_url(get_settings().database_url.get_secret_value())
    engine = create_engine(url)
    print(f"database: {url.database} on {url.host}:{url.port}")
    print(NOTICE)
    with Session(engine) as session:
        before = summarise(session)
        audit_rows = session.scalar(select(func.count(AuditLog.id)))
    for name, info in before.items():
        print(f"  {name:<12} {info['rows']} rows (IDs {info['min_id']} to {info['max_id']})")
    print(f"  audit_log    {audit_rows} rows (kept)")

    if not args.yes:
        print("Dry run: nothing deleted. Re-run with --yes to reset.")
        return 2
    deleted = reset(engine)
    with Session(engine) as session:
        after = summarise(session)
        audit_after = session.scalar(select(func.count(AuditLog.id)))
    engine.dispose()
    total = sum(d["rows"] for d in deleted.values())
    print(
        f"Deleted {total} rows; remaining: "
        + ", ".join(f"{n} {a['rows']}" for n, a in after.items())
    )
    print(f"audit_log: {audit_rows} -> {audit_after} rows (one demo_reset event appended)")
    print("Orthanc is unchanged; run POST /studies/sync to register its studies again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
