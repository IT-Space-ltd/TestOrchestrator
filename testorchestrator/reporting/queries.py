"""Scoped reporting queries.

The first Reports-menu slice intentionally reuses the execution schema and
project scoping rules without adding export dependencies. Every caller gets a
query already restricted to projects the user may see; client-supplied project
filters are intersected with that authorization scope, never trusted.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..execution import Execution, Project
from ..extensions import db

MAX_REPORT_ROWS = 5000


def _aw(dt):
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def visible_project_ids(user):
    return [p.id for p in Project.query.all() if user.project_allowed(p.id)]


def scoped_executions(user, filters):
    """Execution query pre-scoped to the user's visible projects."""
    ids = visible_project_ids(user)
    q = Execution.query.filter(Execution.project_id.in_(ids or [""]))
    project_id = (filters.get("project_id") or "").strip()
    if project_id:
        q = q.filter(Execution.project_id == (project_id if project_id in ids else ""))
    days = max(1, min(int(filters.get("days") or 30), 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = q.filter(Execution.created_at >= since.replace(tzinfo=None))
    for field in ("state", "outcome", "suite_id", "runner_id", "schedule_id"):
        value = (filters.get(field) or "").strip()
        if value:
            q = q.filter(getattr(Execution, field) == value)
    environment = (filters.get("environment") or "").strip()
    if environment == "__none__":
        q = q.filter(Execution.environment.is_(None))
    elif environment:
        q = q.filter(Execution.environment == environment)
    source_ref = (filters.get("source_ref") or "").strip()
    if source_ref == "__none__":
        q = q.filter(Execution.source_ref.is_(None))
    elif source_ref:
        q = q.filter(Execution.source_ref == source_ref)
    return q, days


def execution_summary(user, filters):
    """Rows and aggregate cards for the first execution-summary report."""
    q, days = scoped_executions(user, filters)
    total = q.count()
    rows = (q.order_by(Execution.created_at.desc())
             .limit(MAX_REPORT_ROWS).all())
    outcome_rows = (q.with_entities(Execution.outcome, func.count(Execution.id))
                    .group_by(Execution.outcome).all())
    state_rows = (q.with_entities(Execution.state, func.count(Execution.id))
                  .group_by(Execution.state).all())
    def key(v):
        return getattr(v, "value", str(v or ""))
    finished = [e for e in rows if e.started_at and e.finished_at]
    durations = [(_aw(e.finished_at) - _aw(e.started_at)).total_seconds()
                 for e in finished]
    return {
        "generated_at": datetime.now(timezone.utc),
        "days": days,
        "rows": rows,
        "total": total,
        "truncated": total > len(rows),
        "max_rows": MAX_REPORT_ROWS,
        "outcomes": {key(k): n for k, n in outcome_rows},
        "states": {key(k): n for k, n in state_rows},
        "avg_duration_s": round(sum(durations) / len(durations), 1) if durations else None,
    }


def _csv_safe(value):
    """Prevent spreadsheet-formula execution in CSV consumers."""
    text = str(value or "")
    return "\'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def execution_csv(report):
    """Stable raw-data CSV contract for the execution-summary report."""
    import csv
    import io
    out = io.StringIO()
    fields = ["execution_id", "project_id", "suite_id", "state", "outcome",
              "created_at_utc", "started_at_utc", "finished_at_utc",
              "created_by", "runner_id", "schedule_id", "source_ref",
              "source_sha", "environment", "error_kind"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    def iso(dt):
        return _aw(dt).isoformat() if dt else ""
    for e in report["rows"]:
        w.writerow({
            "execution_id": e.id, "project_id": e.project_id,
            "suite_id": e.suite_id or "",
            "state": getattr(e.state, "value", str(e.state)),
            "outcome": getattr(e.outcome, "value", str(e.outcome)),
            "created_at_utc": iso(e.created_at),
            "started_at_utc": iso(e.started_at),
            "finished_at_utc": iso(e.finished_at),
            "created_by": _csv_safe(e.created_by), "runner_id": e.runner_id or "",
            "schedule_id": e.schedule_id or "",
            "source_ref": _csv_safe(e.source_ref),
            "source_sha": e.source_sha or "",
            "environment": _csv_safe(e.environment),
            "error_kind": _csv_safe(e.error_kind),
        })
    return out.getvalue()
