"""Execution trigger origin.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-28 09:58:00.000000

Adds an explicit trigger-origin column. Historical rows intentionally remain
``unknown``: ``schedule_id`` is an overloaded link because manual schedule
run-now also records it, and ``created_by`` actor conventions are not a safe
schema contract. Backfilling from either field would misclassify real runs.
"""
from alembic import op
import sqlalchemy as sa


revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "executions",
        sa.Column("trigger_origin", sa.String(length=16), nullable=False,
                  server_default="unknown"),
    )


def downgrade():
    op.drop_column("executions", "trigger_origin")
