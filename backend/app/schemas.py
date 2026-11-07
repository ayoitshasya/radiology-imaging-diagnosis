"""Response models. Every JSON response carries the fixed educational-use notice."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.text import FreeText, ReviewerName

NOTICE = "Educational use only. Not for clinical use."
NO_IDENTIFIERS = (
    "Do not type patient names, patient IDs, dates of birth or any other patient "
    "identifier into this field."
)


class ReviewSummary(BaseModel):
    """Latest review decision, shown next to a prediction."""

    review_id: int
    prediction_id: int
    decision: Literal["approved", "rejected"]
    reviewer: str
    created_at: datetime


class Noticed(BaseModel):
    """Base for responses that must show the notice."""

    notice: str = Field(default=NOTICE)


class PredictionSummary(BaseModel):
    """Short form of a prediction for study listings."""

    prediction_id: int
    probability: float
    label: int
    threshold: float
    created_at: datetime


class StudyStatus(BaseModel):
    """One Orthanc study and where it is in the workflow."""

    orthanc_study_id: str
    study_instance_uid: str
    status: Literal["not_synced", "pending", "analysed"]
    latest_prediction: PredictionSummary | None = None
    latest_review: ReviewSummary | None = None


class StudyList(Noticed):
    """GET /studies."""

    count: int
    studies: list[StudyStatus]


LABEL_MEANING = (
    "1 = model score at or above the validation-chosen threshold (pneumonia opacity "
    "predicted); 0 = below it. A model output, not a diagnosis."
)


class PredictionOut(Noticed):
    """A stored prediction with everything needed to interpret and trace it."""

    prediction_id: int
    orthanc_study_id: str
    study_instance_uid: str
    probability: float
    label: int
    label_meaning: str = Field(default=LABEL_MEANING)
    threshold: float
    threshold_source: str = Field(default="validation split, Youden J")
    model_name: str
    checkpoint_sha256: str
    created_at: datetime
    cached: bool = False
    prediction_count: int = 1
    latest_review: ReviewSummary | None = None


class SyncResult(Noticed):
    """POST /studies/sync."""

    orthanc_studies: int
    added: int
    already_synced: int
    pending: int
    missing_from_orthanc: int


class ReviewIn(BaseModel):
    """A reviewer's decision on the study's latest prediction."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reviewer: ReviewerName = Field(
        description=f"Reviewer name, max 100 characters. {NO_IDENTIFIERS}"
    )
    reason: FreeText | None = Field(
        default=None,
        description=f"Required when rejected; not used for approvals. Max 1000 characters. "
        f"{NO_IDENTIFIERS}",
    )
    comment: FreeText | None = Field(
        default=None, description=f"Optional, max 1000 characters. {NO_IDENTIFIERS}"
    )

    @model_validator(mode="after")
    def reason_matches_decision(self) -> ReviewIn:
        """A rejection needs a reason; an approval uses comment instead."""
        if self.decision == "rejected" and not self.reason:
            raise ValueError("reason is required when the decision is rejected")
        if self.decision == "approved" and self.reason:
            raise ValueError("reason is only for rejections; use comment for an approval")
        return self


class ReviewOut(Noticed):
    """One stored review."""

    review_id: int
    prediction_id: int
    orthanc_study_id: str
    study_instance_uid: str
    decision: Literal["approved", "rejected"]
    reason: str | None
    comment: str | None
    reviewer: str
    created_at: datetime


class ReviewHistory(Noticed):
    """GET /studies/{id}/reviews, oldest first."""

    orthanc_study_id: str
    count: int
    reviews: list[ReviewOut]


class AuditEntry(BaseModel):
    """One audit event."""

    id: int
    event_type: str
    study_instance_uid: str | None
    detail: dict
    created_at: datetime


class AuditPage(Noticed):
    """GET /audit: one page of events, newest first, with the total for the filters."""

    total: int
    limit: int
    offset: int
    items: list[AuditEntry]
