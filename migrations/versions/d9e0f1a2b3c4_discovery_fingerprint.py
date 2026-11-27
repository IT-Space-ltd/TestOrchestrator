"""discovery fingerprint + tags columns

Adds DiscoveredItem.tags/fingerprint and
FrameworkProject.discovery_warnings_json/discovery_fingerprint —
config-fingerprint-based staleness (not just git SHA).

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
"""
from alembic import op
import sqlalchemy as sa

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("discovered_items") as b:
        b.add_column(sa.Column("tags", sa.Text(), nullable=False,
                               server_default=""))
        b.add_column(sa.Column("fingerprint", sa.String(80),
                               nullable=False, server_default=""))
    with op.batch_alter_table("framework_projects") as b:
        b.add_column(sa.Column("discovery_warnings_json", sa.Text(),
                               nullable=False, server_default="[]"))
        b.add_column(sa.Column("discovery_fingerprint",
                               sa.String(80), nullable=False,
                               server_default=""))


def downgrade():
    with op.batch_alter_table("framework_projects") as b:
        b.drop_column("discovery_fingerprint")
        b.drop_column("discovery_warnings_json")
    with op.batch_alter_table("discovered_items") as b:
        b.drop_column("fingerprint")
        b.drop_column("tags")
