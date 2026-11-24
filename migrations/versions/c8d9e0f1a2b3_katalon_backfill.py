"""backfill: one katalon FrameworkProject per existing binding (2.7.0)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-24

Existing GitBindings keep identical behavior — each gains one
`katalon` framework project whose project_root reproduces the
previous effective base (coalesce(prj_path dir, subdirectory)).
Discovered items keep working through the unchanged binding-linked
queries; framework_project_id is set for traceability only.
"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def _nid() -> str:
    return uuid.uuid4().hex[:32]


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    tables = _inspect(bind).get_table_names()
    if "framework_projects" not in tables:
        return
    fp = sa.table(
        "framework_projects",
        sa.column("id"), sa.column("binding_id"),
        sa.column("project_id"), sa.column("name"),
        sa.column("framework"), sa.column("project_root"),
        sa.column("workdir"), sa.column("config_file"),
        sa.column("test_roots_json"), sa.column("include_json"),
        sa.column("exclude_json"), sa.column("feature_roots_json"),
        sa.column("stepdef_roots_json"),
        sa.column("support_roots_json"), sa.column("settings_json"),
        sa.column("adapter_version"), sa.column("discovered_sha"),
        sa.column("discovery_status"), sa.column("discovery_error"),
        sa.column("discovery_at"), sa.column("created_at"),
    )
    gb = sa.table(
        "git_bindings",
        sa.column("id"), sa.column("project_id"), sa.column("name"),
        sa.column("subdirectory"), sa.column("prj_path"),
        sa.column("discovered_sha"), sa.column("discovery_status"),
        sa.column("discovery_at"),
    )
    have = {r[0] for r in bind.execute(
        sa.select(fp.c.binding_id))}
    rows = bind.execute(sa.select(
        gb.c.id, gb.c.project_id, gb.c.name, gb.c.subdirectory,
        gb.c.prj_path, gb.c.discovered_sha, gb.c.discovery_status,
        gb.c.discovery_at)).fetchall()
    for (bid, pid, name, subdir, prj, dsha, dstat, dat) in rows:
        if bid in have:
            continue
        # Effective-behavior backfill (review correction): discovery
        # ran under worktree+subdirectory and rglobbed for exactly one
        # .prj — `prj_path` was stored but NEVER read. `subdirectory`
        # is the checkout-level scope that stays on the binding, so
        # the backfilled project_root is "" (= binding scope root),
        # NOT prj_path — activating that ignored field would re-root
        # discovery and change behavior. prj_path is recorded only as
        # informational config_file text. The katalon adapter
        # replicates the legacy rglob semantics verbatim.
        status = {"ok": "ok", "failed": "failed"}.get(dstat, "draft")
        bind.execute(fp.insert().values(
            id=_nid(), binding_id=bid, project_id=pid,
            name=f"{name} (Katalon)", framework="katalon",
            project_root="", workdir="",
            config_file=prj or "",
            test_roots_json="[]", include_json="[]",
            exclude_json="[]", feature_roots_json="[]",
            stepdef_roots_json="[]", support_roots_json="[]",
            settings_json="{}", adapter_version="1",
            discovered_sha=dsha or "",
            discovery_status=status, discovery_error="",
            discovery_at=dat, created_at=dat))
    # Link existing items to their binding's katalon project.
    di = sa.table(
        "discovered_items",
        sa.column("binding_id"), sa.column("framework_project_id"),
        sa.column("framework"),
    )
    bind.execute(di.update().values(
        framework="katalon",
        framework_project_id=sa.select(fp.c.id).where(
            fp.c.binding_id == di.c.binding_id).scalar_subquery(),
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE discovered_items SET framework='', "
        "framework_project_id=NULL WHERE framework='katalon'"))
    bind.execute(sa.text(
        "DELETE FROM framework_projects WHERE framework='katalon'"))
