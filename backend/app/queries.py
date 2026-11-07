"""Database lookups shared by the routers."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import Prediction, Review, Study
from backend.app.schemas import ReviewSummary


def study_or_404(session: Session, orthanc_study_id: str) -> Study:
    """The synced study, or 404 telling the caller to sync first."""
    study = session.scalar(select(Study).where(Study.orthanc_study_id == orthanc_study_id))
    if study is None:
        raise HTTPException(404, detail="Unknown study; call POST /studies/sync first")
    return study


def latest_prediction(session: Session, orthanc_study_id: str) -> Prediction | None:
    """Most recent prediction for a study, if any."""
    return session.scalar(
        select(Prediction)
        .where(Prediction.orthanc_study_id == orthanc_study_id)
        .order_by(Prediction.id.desc())
        .limit(1)
    )


def latest_predictions(session: Session) -> dict[str, Prediction]:
    """Latest prediction per Orthanc study ID."""
    newest = (
        select(Prediction.orthanc_study_id, func.max(Prediction.id).label("max_id"))
        .group_by(Prediction.orthanc_study_id)
        .subquery()
    )
    rows = session.scalars(select(Prediction).join(newest, Prediction.id == newest.c.max_id))
    return {p.orthanc_study_id: p for p in rows}


def latest_reviews(session: Session, prediction_ids: list[int]) -> dict[int, Review]:
    """Latest review for each of the given predictions.

    Callers pass the latest prediction of each study, so a review of a superseded
    prediction (before a forced re-analysis) is not shown as current.
    """
    if not prediction_ids:
        return {}
    newest = (
        select(Review.prediction_id, func.max(Review.id).label("max_id"))
        .where(Review.prediction_id.in_(prediction_ids))
        .group_by(Review.prediction_id)
        .subquery()
    )
    rows = session.scalars(select(Review).join(newest, Review.id == newest.c.max_id))
    return {r.prediction_id: r for r in rows}


def review_summary(review: Review | None) -> ReviewSummary | None:
    """Short form of a review for listings and results."""
    if review is None:
        return None
    return ReviewSummary(
        review_id=review.id,
        prediction_id=review.prediction_id,
        decision=review.decision,
        reviewer=review.reviewer,
        created_at=review.created_at,
    )
