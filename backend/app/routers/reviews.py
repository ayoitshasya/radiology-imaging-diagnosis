"""Review endpoints: record a reviewer's decision and list a study's review history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from backend.app.audit import record_event
from backend.app.deps import SessionDep
from backend.app.models import Prediction, Review
from backend.app.queries import latest_prediction, study_or_404
from backend.app.schemas import NO_IDENTIFIERS, ReviewHistory, ReviewIn, ReviewOut

router = APIRouter(prefix="/studies", tags=["reviews"])


def review_out(review: Review, orthanc_study_id: str, study_instance_uid: str) -> ReviewOut:
    """Response model for a stored review."""
    return ReviewOut(
        review_id=review.id,
        prediction_id=review.prediction_id,
        orthanc_study_id=orthanc_study_id,
        study_instance_uid=study_instance_uid,
        decision=review.decision,
        reason=review.reason,
        comment=review.comment,
        reviewer=review.reviewer,
        created_at=review.created_at,
    )


@router.post(
    "/{orthanc_study_id}/review",
    response_model=ReviewOut,
    status_code=201,
    description=(
        "Record approved or rejected for the study's latest prediction. A reason is "
        f"required for a rejection. Each call adds a new review; none is edited. "
        f"{NO_IDENTIFIERS}"
    ),
)
def review_study(orthanc_study_id: str, body: ReviewIn, session: SessionDep) -> ReviewOut:
    """Store a review and its audit event in one transaction.

    The review row is flushed to get its ID, the audit event referencing it joins the
    same transaction, and a single commit saves both. If anything fails before or during
    the commit, the session is closed without committing and both are rolled back. The
    audit event carries the decision and reviewer but not the reason or comment text,
    which stays only in the reviews table. Free text is never logged.
    """
    study = study_or_404(session, orthanc_study_id)
    prediction = latest_prediction(session, orthanc_study_id)
    if prediction is None:
        raise HTTPException(404, detail="Study has no prediction yet; analyse it first")

    review = Review(
        prediction_id=prediction.id,
        decision=body.decision,
        reason=body.reason,
        comment=body.comment,
        reviewer=body.reviewer,
    )
    session.add(review)
    session.flush()
    record_event(
        session,
        "review_submitted",
        study.study_instance_uid,
        {
            "orthanc_study_id": orthanc_study_id,
            "prediction_id": prediction.id,
            "review_id": review.id,
            "decision": body.decision,
            "reviewer": body.reviewer,
        },
    )
    session.commit()
    return review_out(review, orthanc_study_id, study.study_instance_uid)


@router.get("/{orthanc_study_id}/reviews", response_model=ReviewHistory)
def study_reviews(orthanc_study_id: str, session: SessionDep) -> ReviewHistory:
    """Every review of the study's predictions, oldest first; empty if none yet."""
    study = study_or_404(session, orthanc_study_id)
    rows = session.scalars(
        select(Review)
        .join(Prediction, Review.prediction_id == Prediction.id)
        .where(Prediction.orthanc_study_id == orthanc_study_id)
        .order_by(Review.created_at, Review.id)
    ).all()
    reviews = [review_out(r, orthanc_study_id, study.study_instance_uid) for r in rows]
    return ReviewHistory(orthanc_study_id=orthanc_study_id, count=len(reviews), reviews=reviews)
