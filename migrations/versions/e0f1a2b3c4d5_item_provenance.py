"""discovered_items.item_type — static vs native provenance

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
"""
from alembic import op
import sqlalchemy as sa

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("discovered_items") as b:
        b.add_column(sa.Column("item_type", sa.String(16),
                               nullable=False,
                               server_default="static"))


def downgrade():
    with op.batch_alter_table("discovered_items") as b:
        b.drop_column("item_type")
