"""Scoped reporting queries.

The initial Reports-menu slices intentionally reuse the execution schema,
analytics logical-run semantics and project scoping rules without adding export
dependencies. Every caller gets a query already restricted to projects the user
may see; client-supplied project filters are intersected with that
authorization scope, never trusted.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..analytics import (LOGICAL_ROLES, TERMINAL, _aw, _day,
                         resolve_logical_runs)
from ..execution import Execution, Project, TestResult

MAX_REPORT_ROWS = 5000


def _bounded_days(value):
    try:
        days = int(value or 30)
    except (TypeError, ValueError):
        days = 30
    return max(1, min(days, 365))


def _filter_snapshot(filters):
    return {k: str(filters.get(k, ""))[:256] for k in sorted(filters)
            if str(filters.get(k, "")).strip()}


def visible_project_ids(user):
    return [p.id for p in Project.query.all() if user.project_allowed(p.id)]


def scoped_executions(user, filters, windowed=True):
    """Execution query pre-scoped to the user's visible projects.

    `windowed=False` is for logical-run reports: retry chains must be
    resolved before their final attempt is assigned to the time window.
    """
    ids = visible_project_ids(user)
    q = Execution.query.filter(Execution.project_id.in_(ids or [""]))
    project_id = (filters.get("project_id") or "").strip()
    if project_id:
        q = q.filter(Execution.project_id == (project_id if project_id in ids else ""))
    days = _bounded_days(filters.get("days"))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    if windowed:
        q = q.filter(Execution.created_at.isnot(None),
                     Execution.created_at >= since)
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
    duration_sum = 0.0
    duration_count = 0
    timestamp_rows = (q.filter(Execution.started_at.isnot(None),
                               Execution.finished_at.isnot(None))
                      .with_entities(Execution.started_at,
                                     Execution.finished_at)
                      .yield_per(1000))
    for started_at, finished_at in timestamp_rows:
        secs = (_aw(finished_at) - _aw(started_at)).total_seconds()
        if secs >= 0:
            duration_sum += secs
            duration_count += 1
    avg_duration = duration_sum / duration_count if duration_count else None
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "days": days,
        "rows": rows,
        "total": total,
        "truncated": total > len(rows),
        "max_rows": MAX_REPORT_ROWS,
        "outcomes": {key(k): n for k, n in outcome_rows},
        "states": {key(k): n for k, n in state_rows},
        "avg_duration_s": round(float(avg_duration), 1) if avg_duration is not None else None,
    }


def _enum_value(value):
    return getattr(value, "value", str(value or ""))


def _final_matches_filters(final, filters):
    for field in ("state", "outcome", "suite_id", "runner_id", "schedule_id"):
        expected = (filters.get(field) or "").strip()
        if expected and _enum_value(getattr(final, field)) != expected:
            return False
    environment = (filters.get("environment") or "").strip()
    if environment == "__none__" and final.environment is not None:
        return False
    if environment not in ("", "__none__") and final.environment != environment:
        return False
    source_ref = (filters.get("source_ref") or "").strip()
    if source_ref == "__none__" and final.source_ref is not None:
        return False
    if source_ref not in ("", "__none__") and final.source_ref != source_ref:
        return False
    return True


def trend_report(user, filters, tz=None):
    """Pass-rate/duration trends using logical-run semantics.

    Retry chains are resolved before metadata filters so retries cannot
    inflate counts. The source set is terminal logical-role attempts in the
    rolling window ending now: an older missing chain head cannot change the
    final resolved attempt, because any later terminal retry would also be
    inside that window. A run belongs to the day its final resolved terminal
    attempt finished; case pass rates use that attempt's parsed results (plus
    unit-child results for partitioned parents), with skipped cases excluded
    from the denominator. Output is bounded to MAX_REPORT_ROWS logical runs
    and truncation is disclosed.
    """
    base = {"project_id": filters.get("project_id", ""),
            "days": filters.get("days", "30")}
    q, days = scoped_executions(user, base, windowed=False)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    executions = (q.filter(Execution.role.in_(LOGICAL_ROLES),
                           Execution.state.in_(tuple(TERMINAL)),
                           Execution.finished_at.isnot(None),
                           Execution.finished_at >= since)
                  .all())
    runs = resolve_logical_runs(executions)

    selected = []
    for run in runs:
        final = run["final"]
        if not final or not final.finished_at:
            continue
        if _aw(final.finished_at) < since:
            continue
        if not _final_matches_filters(final, filters):
            continue
        selected.append((run, final))
    selected.sort(key=lambda item: _aw(item[1].finished_at), reverse=True)
    total = len(selected)
    selected = selected[:MAX_REPORT_ROWS]
    bounded_count = len(selected)
    selected.reverse()

    parent_ids = [final.id for _run, final in selected if final.role == "parent"]
    parent_projects = {final.id: final.project_id
                       for _run, final in selected if final.role == "parent"}
    units_by_parent = {}
    if parent_ids:
        for unit in Execution.query.filter(Execution.parent_id.in_(parent_ids)).all():
            if unit.project_id == parent_projects.get(unit.parent_id):
                units_by_parent.setdefault(unit.parent_id, []).append(unit)

    result_execution_ids = set()
    sources_by_final = {}
    for _run, final in selected:
        sources = [final] + units_by_parent.get(final.id, [])
        sources_by_final[final.id] = sources
        result_execution_ids.update(e.id for e in sources)
    result_counts = {}
    if result_execution_ids:
        result_rows = (TestResult.query
                       .with_entities(TestResult.execution_id,
                                      TestResult.status,
                                      func.count(TestResult.id))
                       .filter(TestResult.execution_id.in_(result_execution_ids))
                       .group_by(TestResult.execution_id, TestResult.status)
                       .all())
        for execution_id, status, count in result_rows:
            result_counts.setdefault(execution_id, {})[_enum_value(status)] = count

    zone_name = getattr(tz, "key", None) or getattr(tz, "zone", None) \
        or str(tz or "UTC")
    by_day = {}
    duration_points = []
    for _run, final in selected:
        d = _day(final.finished_at, tz)
        row = by_day.setdefault(d, {
            "day": d, "logical_runs": 0, "passed_runs": 0,
            "failed_runs": 0, "incomplete_runs": 0, "none_runs": 0,
            "case_passed": 0, "case_failed": 0, "case_error": 0,
            "case_skipped": 0, "durations": []})
        row["logical_runs"] += 1
        oc = _enum_value(final.outcome) or "none"
        row[{"passed": "passed_runs", "failed": "failed_runs",
             "incomplete": "incomplete_runs"}.get(oc, "none_runs")] += 1
        for source in sources_by_final[final.id]:
            counts = result_counts.get(source.id, {})
            for st in ("passed", "failed", "error", "skipped"):
                row["case_" + st] += counts.get(st, 0)
        if final.started_at and final.finished_at:
            secs = (_aw(final.finished_at) - _aw(final.started_at)).total_seconds()
            if secs >= 0:
                row["durations"].append(secs)
                duration_points.append({"day": d, "seconds": round(secs, 2)})

    trend_rows = []
    outcome_rows = []
    pass_rows = []
    for d in sorted(by_day):
        r = by_day[d]
        denom = r["case_passed"] + r["case_failed"] + r["case_error"]
        durations = r.pop("durations")
        r["case_pass_rate"] = round(100 * r["case_passed"] / denom, 1) if denom else None
        r["avg_duration_s"] = round(sum(durations) / len(durations), 1) if durations else None
        trend_rows.append(r)
        outcome_rows.append({"day": d, "passed": r["passed_runs"],
                             "failed": r["failed_runs"],
                             "incomplete": r["incomplete_runs"],
                             "none": r["none_runs"]})
        pass_rows.append({"day": d, "passed": r["case_passed"],
                          "failed": r["case_failed"], "error": r["case_error"],
                          "skipped": r["case_skipped"]})
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "timezone": zone_name,
        "days": days, "rows": trend_rows, "total": total,
        "truncated": total > bounded_count, "max_rows": MAX_REPORT_ROWS,
        "outcome_trend": outcome_rows, "pass_rate": pass_rows,
        "durations": duration_points,
        "counting": "logical runs; final resolved attempt; case pass-rate excludes skipped",
    }


def trend_csv(report):
    """Daily-row CSV for the pass-rate/duration trend report."""
    import csv
    import io
    out = io.StringIO()
    fields = ["day", "logical_runs", "passed_runs", "failed_runs",
              "incomplete_runs", "none_runs", "case_passed", "case_failed",
              "case_error", "case_skipped", "case_pass_rate",
              "avg_duration_s", "tz", "generated_at_utc", "report_type",
              "total_logical_runs", "truncated", "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    import json
    filters_json = json.dumps(report.get("filters", {}), sort_keys=True)
    for r in report["rows"]:
        w.writerow({"day": r["day"], "logical_runs": r["logical_runs"],
                    "passed_runs": r["passed_runs"],
                    "failed_runs": r["failed_runs"],
                    "incomplete_runs": r["incomplete_runs"],
                    "none_runs": r["none_runs"],
                    "case_passed": r["case_passed"],
                    "case_failed": r["case_failed"],
                    "case_error": r["case_error"],
                    "case_skipped": r["case_skipped"],
                    "case_pass_rate": r["case_pass_rate"],
                    "avg_duration_s": r["avg_duration_s"],
                    "tz": report["timezone"],
                    "generated_at_utc": generated,
                    "report_type": "trends",
                    "total_logical_runs": report["total"],
                    "truncated": "true" if report["truncated"] else "false",
                    "max_rows": report["max_rows"],
                    "filters_json": filters_json})
    return out.getvalue()


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
              "source_sha", "environment", "error_kind", "tz",
              "generated_at_utc", "report_type", "total_executions",
              "truncated", "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    def iso(dt):
        return _aw(dt).isoformat() if dt else ""
    import json
    generated = report["generated_at"].isoformat()
    filters_json = json.dumps(report.get("filters", {}), sort_keys=True)
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
            "tz": "UTC",
            "generated_at_utc": generated,
            "report_type": "execution-summary",
            "total_executions": report["total"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"],
            "filters_json": filters_json,
        })
    return out.getvalue()
