"""Retention policies (M9 §storage-7).

Three independent domains — each has its own clock and policy:

- **Artifact files** — the durable/staged copies behind Artifact
  rows. Expiry marks rows ``expired`` and deletes file bytes; the
  execution summary stays available.
- **Execution data** — the Execution row + cascaded parsed results,
  artifact rows and reservations (metadata + summaries).
- **Operational logs** — the existing separate
  ``logs_retention_days`` + ``logs.prune()``; untouched here.

Clock: ``Execution.finished_at`` — retention never starts before an
execution reaches a terminal state, so active executions,
in-flight transfers (``uploading``) and unverified outputs
(``staged`` — the workspace copy was never durably verified) are
never touched by a sweep.

Precedence: project override (``Project.retention_json``) → global
default (``settings.retention_*_days``) → ``0``/unset means
"keep forever". Policy changes apply to ALL eligible records at
the next sweep — they are not limited to new runs.

A sweep is operator-invoked (preview → explicit confirm) — no
background deleter runs silently.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .extensions import db
from .execution import (
    Artifact, ArtifactStore, Execution, ExecutionState, Project)
from .storage import StoreError, backend_for
from . import settings as _settings

TERMINAL = (ExecutionState.COMPLETED, ExecutionState.FAILED,
            ExecutionState.CANCELED, ExecutionState.UNKNOWN)
DELETABLE_STATES = ("stored", "failed")


def effective_policy(project) -> dict:
    """{artifact_days, metadata_days} — days after finished_at;
    None/0 means keep forever. Project override wins per-key,
    else the global default applies."""
    proj = project.retention() if project else {}
    return {
        "artifact_days": (proj.get("artifact_days")
                          if proj.get("artifact_days") is not None
                          else int(_settings.get(
                              "retention_artifact_days", 0) or 0)),
        "metadata_days": (proj.get("metadata_days")
                          if proj.get("metadata_days") is not None
                          else int(_settings.get(
                              "retention_metadata_days", 0) or 0)),
    }


def _eligible_executions(project_id=None):
    q = Execution.query.filter(Execution.state.in_(TERMINAL),
                               Execution.finished_at.isnot(None))
    if project_id:
        q = q.filter(Execution.project_id == project_id)
    return q.all()


def _expired_targets(policy, now, project_id=None):
    """Executions past the artifact-file cutoff."""
    days = policy.get("artifact_days") or 0
    if days <= 0:
        return []
    cutoff = now - timedelta(days=days)
    return [e for e in _eligible_executions(project_id)
            if e.finished_at.replace(tzinfo=timezone.utc)
            < cutoff]


def _metadata_targets(policy, now, project_id=None):
    days = policy.get("metadata_days") or 0
    if days <= 0:
        return []
    cutoff = now - timedelta(days=days)
    return [e for e in _eligible_executions(project_id)
            if e.finished_at.replace(tzinfo=timezone.utc)
            < cutoff]


def preview(project_id=None) -> dict:
    """Non-destructive counts shown BEFORE a sweep — files/bytes for
    artifact expiry + executions/rows for metadata expiry."""
    now = datetime.now(timezone.utc)
    art = {"executions": 0, "files": 0, "bytes": 0}
    meta = {"executions": 0}
    if project_id:
        project = db.session.get(Project, project_id)
        policy = effective_policy(project)
    else:
        policy = effective_policy(None)
    for ex in _expired_targets(policy, now, project_id):
        # Project policy differs per execution's project — compute
        # each execution's own effective artifact cutoff.
        p = db.session.get(Project, ex.project_id)
        pol = effective_policy(p)
        days = pol.get("artifact_days") or 0
        if days <= 0:
            continue
        if ex.finished_at.replace(tzinfo=timezone.utc) >= \
                now - timedelta(days=days):
            continue
        rows = [a for a in ex.artifacts
                if a.storage_state in DELETABLE_STATES
                and a.storage_ref]
        if not rows:
            continue
        art["executions"] += 1
        art["files"] += len(rows)
        art["bytes"] += sum(a.size or 0 for a in rows)
    for ex in _metadata_targets(policy, now, project_id):
        p = db.session.get(Project, ex.project_id)
        pol = effective_policy(p)
        days = pol.get("metadata_days") or 0
        if days <= 0:
            continue
        if ex.finished_at.replace(tzinfo=timezone.utc) < \
                now - timedelta(days=days):
            meta["executions"] += 1
    return {"artifacts": art, "metadata": meta,
            "policies": {pid: effective_policy(db.session.get(Project, pid))
                         for pid in {e.project_id for e in
                                     _eligible_executions(project_id)}
                         } if not project_id
            else {project_id: policy}}


def _expire_artifact(a) -> bool:
    """Delete the durable object + redundant staged file; mark the
    row 'expired' — never silently 'missing'."""
    st = db.session.get(ArtifactStore, a.store_id) if a.store_id else None
    if st is not None and a.storage_ref:
        backend_for(st).delete(a.storage_ref)
    ex = a.execution
    staged = Path(ex.report_dir or "") / a.rel_path
    try:
        staged.resolve().relative_to(Path(ex.report_dir).resolve())
    except ValueError:
        staged = None
    if staged is not None and staged.is_file():
        staged.unlink()
    a.storage_state = "expired"
    return True


def sweep(project_id=None, actor="system") -> dict:
    """Authorized, audited retention pass. Per-file errors are
    isolated — a partial failure reports counts and leaves the row
    in its prior state for a later retry."""
    now = datetime.now(timezone.utc)
    out = {"artifacts_expired": 0, "artifact_errors": 0,
           "executions_removed": 0, "skipped_inflight": 0}
    for ex in _eligible_executions(project_id):
        p = db.session.get(Project, ex.project_id)
        pol = effective_policy(p)
        a_days = pol.get("artifact_days") or 0
        m_days = pol.get("metadata_days") or 0
        fin = ex.finished_at.replace(tzinfo=timezone.utc)
        if a_days > 0 and fin < now - timedelta(days=a_days):
            for a in ex.artifacts:
                if a.storage_state == "uploading":
                    out["skipped_inflight"] += 1
                    continue
                if a.storage_state not in DELETABLE_STATES \
                        or not a.storage_ref:
                    continue
                try:
                    _expire_artifact(a)
                    out["artifacts_expired"] += 1
                except Exception:                        # noqa: BLE001
                    out["artifact_errors"] += 1
        if m_days > 0 and fin < now - timedelta(days=m_days):
            # Metadata expiry removes the execution — its remaining
            # durable files go with it (same deadline domain applied:
            # a summary cannot outlive its own evidence rows' row).
            for a in ex.artifacts:
                if a.storage_ref:
                    try:
                        st = db.session.get(
                            ArtifactStore, a.store_id) \
                            if a.store_id else None
                        if st is not None:
                            backend_for(st).delete(a.storage_ref)
                    except Exception:                    # noqa: BLE001
                        out["artifact_errors"] += 1
            for child in ex.children:
                child.parent_id = None
            db.session.delete(ex)   # cascades results/artifacts/
                                    # reservations rows
            out["executions_removed"] += 1
    db.session.commit()
    from .models import record_audit
    record_audit(actor, "retention.sweep",
                 f"project={project_id or 'all'} "
                 f"expired={out['artifacts_expired']} "
                 f"errors={out['artifact_errors']} "
                 f"executions_removed={out['executions_removed']} "
                 f"skipped_inflight={out['skipped_inflight']}")
    return out


def parse_days(raw: str):
    """Form value → int days; ''/'inherit' → None (use global);
    negative/NaN → ValueError."""
    raw = (raw or "").strip()
    if raw in ("", "inherit"):
        return None
    v = int(raw)
    if v < 0:
        raise ValueError("days must be >= 0")
    return v
