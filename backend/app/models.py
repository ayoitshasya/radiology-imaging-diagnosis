"""SQLAlchemy models: predictions, reviews and the append-only audit log.

Only the Orthanc study ID and the StudyInstanceUID identify a study. There are no columns
for patient name, patient ID, birth date or any other personal identifier.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base


class Study(Base):
    """A study known to the backend after a sync. Status is derived, not stored."""

    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    orthanc_study_id: Mapped[str] = mapped_column(String(64), unique=True)
    study_instance_uid: Mapped[str] = mapped_column(String(64), unique=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prediction(Base):
    """One model output for one study, with the exact model and threshold used."""

    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint("probability >= 0 AND probability <= 1", name="ck_predictions_probability"),
        CheckConstraint("threshold >= 0 AND threshold <= 1", name="ck_predictions_threshold"),
        CheckConstraint("label IN (0, 1)", name="ck_predictions_label"),
        CheckConstraint("checkpoint_sha256 ~ '^[0-9a-f]{64}$'", name="ck_predictions_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    orthanc_study_id: Mapped[str] = mapped_column(String(64), index=True)
    study_instance_uid: Mapped[str] = mapped_column(String(64), index=True)
    probability: Mapped[float] = mapped_column(Float)
    label: Mapped[int] = mapped_column(SmallInteger)
    threshold: Mapped[float] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String(100))
    checkpoint_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reviews: Mapped[list[Review]] = relationship(back_populates="prediction")


class Review(Base):
    """A human decision on a prediction. A new review is a new row; rows are never edited."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_reviews_decision"),
        CheckConstraint(
            "decision = 'approved' OR (reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="ck_reviews_reason_required_for_rejection",
        ),
        CheckConstraint("length(btrim(reviewer)) > 0", name="ck_reviews_reviewer"),
        CheckConstraint(
            "reason IS NULL OR length(reason) <= 1000", name="ck_reviews_reason_length"
        ),
        CheckConstraint(
            "comment IS NULL OR length(comment) <= 1000", name="ck_reviews_comment_length"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id", ondelete="RESTRICT"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prediction: Mapped[Prediction] = relationship(back_populates="reviews")


class AuditLog(Base):
    """Append-only event log; a database trigger rejects UPDATE, DELETE and TRUNCATE."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    study_instance_uid: Mapped[str | None] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
