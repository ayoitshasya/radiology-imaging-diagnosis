"""Initial schema: predictions, reviews and an append-only audit log.

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Row triggers do not fire on TRUNCATE, so a statement-level trigger covers it separately.
APPEND_ONLY_SQL = """
CREATE FUNCTION audit_log_reject_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_reject_modification();

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_reject_modification();
"""


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("orthanc_study_id", sa.String(64), nullable=False),
        sa.Column("study_instance_uid", sa.String(64), nullable=False),
        sa.Column("probability", sa.Float, nullable=False),
        sa.Column("label", sa.SmallInteger, nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("checkpoint_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 1", name="ck_predictions_probability"
        ),
        sa.CheckConstraint("threshold >= 0 AND threshold <= 1", name="ck_predictions_threshold"),
        sa.CheckConstraint("label IN (0, 1)", name="ck_predictions_label"),
        sa.CheckConstraint("checkpoint_sha256 ~ '^[0-9a-f]{64}$'", name="ck_predictions_sha256"),
    )
    op.create_index("ix_predictions_orthanc_study_id", "predictions", ["orthanc_study_id"])
    op.create_index("ix_predictions_study_instance_uid", "predictions", ["study_instance_uid"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "prediction_id",
            sa.Integer,
            sa.ForeignKey("predictions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("reviewer", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_reviews_decision"),
        sa.CheckConstraint(
            "decision = 'approved' OR (reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="ck_reviews_reason_required_for_rejection",
        ),
        sa.CheckConstraint("length(btrim(reviewer)) > 0", name="ck_reviews_reviewer"),
    )
    op.create_index("ix_reviews_prediction_id", "reviews", ["prediction_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("study_instance_uid", sa.String(64), nullable=True),
        sa.Column("detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_study_instance_uid", "audit_log", ["study_instance_uid"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.execute(APPEND_ONLY_SQL)


def downgrade() -> None:
    # Dropping the table removes its triggers; the function is dropped explicitly.
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_reject_modification()")
    op.drop_table("reviews")
    op.drop_table("predictions")
