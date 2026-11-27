"""CI API tokens: optional expires_at (P3.13)

Revision ID: p5c6d7e8f9a0
Revises: o4b5c6d7e8f9
Create Date: 2026-11-26

Additive only. Existing tokens migrate to NULL (never expires) —
they stay valid exactly as before; expiry is opt-in per token at
creation, defaulting to 90 days for NEW tokens.
"""
from alembic import op
import sqlalchemy as sa

revision = "p5c6d7e8f9a0"
down_revision = "o4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    cols = {c["name"] for c in
            _inspect(bind).get_columns("api_tokens")}
    if "expires_at" not in cols:
        op.add_column("api_tokens", sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("api_tokens", "expires_at")
