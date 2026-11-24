"""framework_projects + framework-aware discovered_items (2.7.0)

Revision ID: b7c8d9e0f1a2
Revises: a2b3c4d5e6f7
Create Date: 2026-11-24

Additive only. `framework_projects` carries independently configured
framework areas inside a git binding (monorepo support); new nullable
columns on `discovered_items` record which framework/adapter produced
an item and its executable selector. No existing row changes meaning.
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    tables = _inspect(bind).get_table_names()
    if "framework_projects" not in tables:
        op.create_table(
            "framework_projects",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("binding_id", sa.String(32),
                      sa.ForeignKey("git_bindings.id"), nullable=False),
            sa.Column("project_id", sa.String(32),
                      sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("framework", sa.String(20), nullable=False),
            sa.Column("project_root", sa.String(512), nullable=False,
                      server_default=""),
            sa.Column("workdir", sa.String(512), nullable=False,
                      server_default=""),
            sa.Column("config_file", sa.String(512), nullable=False,
                      server_default=""),
            sa.Column("test_roots_json", sa.Text(), nullable=False,
                      server_default="[]"),
            sa.Column("include_json", sa.Text(), nullable=False,
                      server_default="[]"),
            sa.Column("exclude_json", sa.Text(), nullable=False,
                      server_default="[]"),
            sa.Column("feature_roots_json", sa.Text(), nullable=False,
                      server_default="[]"),
            sa.Column("stepdef_roots_json", sa.Text(), nullable=False,
                      server_default="[]"),
            sa.Column("support_roots_json", sa.Text(), nullable=False,
                      server_default="[]"),
            sa.Column("settings_json", sa.Text(), nullable=False,
                      server_default="{}"),
            sa.Column("adapter_version", sa.String(16), nullable=False,
                      server_default=""),
            sa.Column("discovered_sha", sa.String(64), nullable=False,
                      server_default=""),
            sa.Column("discovery_status", sa.String(16), nullable=False,
                      server_default="draft"),
            sa.Column("discovery_error", sa.String(512), nullable=False,
                      server_default=""),
            sa.Column("discovery_at", sa.DateTime(timezone=True),
                      nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      nullable=True),
        )
        op.create_index("ix_framework_projects_binding",
                        "framework_projects", ["binding_id"])

    cols = {c["name"] for c in _inspect(
        bind).get_columns("discovered_items")}
    add = {
        "framework":
            sa.Column("framework", sa.String(20), nullable=False,
                      server_default=""),
        "node_id":
            sa.Column("node_id", sa.String(512), nullable=False,
                      server_default=""),
        "granularity":
            sa.Column("granularity", sa.String(16), nullable=False,
                      server_default="file"),
        "selectable":
            sa.Column("selectable", sa.Boolean(), nullable=False,
                      server_default=sa.true()),
    }
    for name, col in add.items():
        if name not in cols:
            op.add_column("discovered_items", col)
    if "framework_project_id" not in cols:
        # SQLite can't ALTER in an FK — batch mode recreates the table
        # preserving existing rows and constraints.
        with op.batch_alter_table("discovered_items") as bop:
            bop.add_column(sa.Column(
                "framework_project_id", sa.String(32), nullable=True))
            bop.create_foreign_key(
                "fk_discovered_items_fp", "framework_projects",
                ["framework_project_id"], ["id"])


def downgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    cols = {c["name"] for c in _inspect(
        bind).get_columns("discovered_items")}
    for name in ("framework_project_id", "framework", "node_id",
                 "granularity", "selectable"):
        if name in cols:
            op.drop_column("discovered_items", name)
    if "framework_projects" in _inspect(bind).get_table_names():
        op.drop_index("ix_framework_projects_binding",
                      table_name="framework_projects")
        op.drop_table("framework_projects")
