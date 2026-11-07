"""Response models. Every JSON response carries the fixed educational-use notice."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NOTICE = "Educational use only. Not for clinical use."


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


class StudyList(Noticed):
    """GET /studies."""

    count: int
    studies: list[StudyStatus]


class SyncResult(Noticed):
    """POST /studies/sync."""

    orthanc_studies: int
    added: int
    already_synced: int
    pending: int
    missing_from_orthanc: int
