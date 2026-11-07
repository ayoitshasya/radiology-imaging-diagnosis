"""Study endpoints: listing and sync with Orthanc."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.audit import record_event
from backend.app.deps import OrthancDep, SessionDep
from backend.app.models import Prediction, Study
from backend.app.schemas import PredictionSummary, StudyList, StudyStatus, SyncResult

router = APIRouter(prefix="/studies", tags=["studies"])


def latest_predictions(session: Session) -> dict[str, Prediction]:
    """Latest prediction per Orthanc study ID."""
    newest = (
        select(Prediction.orthanc_study_id, func.max(Prediction.id).label("max_id"))
        .group_by(Prediction.orthanc_study_id)
        .subquery()
    )
    rows = session.scalars(select(Prediction).join(newest, Prediction.id == newest.c.max_id))
    return {p.orthanc_study_id: p for p in rows}


@router.get("", response_model=StudyList)
def list_studies(session: SessionDep, orthanc: OrthancDep) -> StudyList:
    """List every study in Orthanc with its status: not_synced, pending or analysed."""
    synced = set(session.scalars(select(Study.orthanc_study_id)))
    latest = latest_predictions(session)
    studies = []
    for s in orthanc.list_studies():
        oid = s["orthanc_study_id"]
        pred = latest.get(oid)
        status = "analysed" if pred else ("pending" if oid in synced else "not_synced")
        studies.append(
            StudyStatus(
                **s,
                status=status,
                latest_prediction=PredictionSummary(
                    prediction_id=pred.id,
                    probability=pred.probability,
                    label=pred.label,
                    threshold=pred.threshold,
                    created_at=pred.created_at,
                )
                if pred
                else None,
            )
        )
    return StudyList(count=len(studies), studies=studies)


@router.post("/sync", response_model=SyncResult)
def sync_studies(session: SessionDep, orthanc: OrthancDep) -> SyncResult:
    """Register Orthanc studies the database does not know yet; they start as pending.

    List-and-diff rather than Orthanc's changes feed: one request lists all studies, the
    diff is stateless and idempotent, and no cursor has to be stored. The cost is linear
    in the number of studies, which is fine at demo scale. ON CONFLICT DO NOTHING keeps
    concurrent syncs from creating duplicates. Studies gone from Orthanc are counted,
    never deleted.
    """
    in_orthanc = orthanc.list_studies()
    known = set(session.scalars(select(Study.orthanc_study_id)))
    added = 0
    for s in in_orthanc:
        if s["orthanc_study_id"] in known:
            continue
        result = session.execute(insert(Study).values(**s).on_conflict_do_nothing())
        if result.rowcount:
            added += 1
            record_event(
                session,
                "study_synced",
                s["study_instance_uid"],
                {"orthanc_study_id": s["orthanc_study_id"]},
            )
    session.commit()

    orthanc_ids = {s["orthanc_study_id"] for s in in_orthanc}
    all_known = set(session.scalars(select(Study.orthanc_study_id)))
    analysed = set(session.scalars(select(Prediction.orthanc_study_id).distinct()))
    return SyncResult(
        orthanc_studies=len(in_orthanc),
        added=added,
        already_synced=len(in_orthanc) - added,
        pending=len((all_known & orthanc_ids) - analysed),
        missing_from_orthanc=len(all_known - orthanc_ids),
    )
