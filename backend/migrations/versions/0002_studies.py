"""Add the studies table for synced studies.

Status (pending or analysed) is derived from the predictions table rather than stored,
so it cannot drift out of step with it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("orthanc_study_id", sa.String(64), nullable=False),
        sa.Column("study_instance_uid", sa.String(64), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("orthanc_study_id", name="uq_studies_orthanc_study_id"),
        sa.UniqueConstraint("study_instance_uid", name="uq_studies_study_instance_uid"),
    )


def downgrade() -> None:
    op.drop_table("studies")
