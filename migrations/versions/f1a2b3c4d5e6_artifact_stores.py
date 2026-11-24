"""artifact_stores table + artifact durable-storage columns

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifact_stores",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32),
                  sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("config_json", sa.Text, nullable=False,
                  server_default="{}"),
        sa.Column("credential_ref", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("active", sa.Boolean, nullable=False,
                  server_default=sa.true()),
        sa.Column("retired", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("validated_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("last_error", sa.Text, nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False),
    )
    with op.batch_alter_table("artifacts") as b:
        b.add_column(sa.Column("attempt", sa.Integer, nullable=False,
                               server_default="1"))
        b.add_column(sa.Column("store_id", sa.String(32), nullable=True))
        b.create_foreign_key("fk_artifacts_store_id",
                             "artifact_stores", ["store_id"], ["id"])
        b.add_column(sa.Column("storage_state", sa.String(16),
                               nullable=False,
                               server_default="staged"))
        b.add_column(sa.Column("storage_ref", sa.String(768),
                               nullable=False, server_default=""))
        b.add_column(sa.Column("stored_at", sa.DateTime(timezone=True),
                               nullable=True))


def downgrade():
    with op.batch_alter_table("artifacts") as b:
        b.drop_column("stored_at")
        b.drop_column("storage_ref")
        b.drop_column("storage_state")
        b.drop_column("store_id")
        b.drop_column("attempt")
    op.drop_table("artifact_stores")
