"""Add an optional review comment and length limits on review free text.

The API already sanitises and limits these fields; the CHECK constraints make the limits
hold even for rows written outside the API.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("comment", sa.Text, nullable=True))
    op.create_check_constraint(
        "ck_reviews_reason_length", "reviews", "reason IS NULL OR length(reason) <= 1000"
    )
    op.create_check_constraint(
        "ck_reviews_comment_length", "reviews", "comment IS NULL OR length(comment) <= 1000"
    )


def downgrade() -> None:
    op.drop_constraint("ck_reviews_comment_length", "reviews", type_="check")
    op.drop_constraint("ck_reviews_reason_length", "reviews", type_="check")
    op.drop_column("reviews", "comment")
