"""Saved per-user report filter sets.

Revision ID: a3b4c5d6e7f8
Revises: p5c6d7e8f9a0
Create Date: 2026-11-28

Additive only. Per-user ownership is the initial authorization boundary;
shared report definitions/links remain a later reviewed surface.
"""
from alembic import op
import sqlalchemy as sa

revision = "a3b4c5d6e7f8"
down_revision = "p5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    if "saved_report_filters" not in _inspect(op.get_bind()).get_table_names():
        op.create_table(
            "saved_report_filters",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("username", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("filters_json", sa.Text(), nullable=False,
                      server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      nullable=False),
            sa.UniqueConstraint("username", "name",
                                name="uq_saved_report_filters_user_name"),
        )
        op.create_index("ix_saved_report_filters_username",
                        "saved_report_filters", ["username"])


def downgrade() -> None:
    op.drop_index("ix_saved_report_filters_username",
                  table_name="saved_report_filters")
    op.drop_table("saved_report_filters")
