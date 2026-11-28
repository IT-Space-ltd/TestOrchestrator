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
from ..execution import Execution, Project, Schedule, TestResult
from ..models import AuditEvent

MAX_REPORT_ROWS = 5000
MAX_CASE_ROWS = 500
FLAKY_MIN_EXECUTED_RUNS = 3


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


def _zone_name(tz):
    return getattr(tz, "key", None) or getattr(tz, "zone", None) \
        or str(tz or "UTC")


def _select_logical_runs(user, filters):
    """Bounded terminal logical runs shared by logical-run report types."""
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
    return {"selected": selected, "days": days, "since": since,
            "total": total, "bounded_count": bounded_count}


def _logical_result_sources(selected):
    """Map final attempts plus authorized partition units to result rows."""
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
    return sources_by_final, result_execution_ids


def _result_status_counts(result_execution_ids):
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
    return result_counts


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
    selection = _select_logical_runs(user, filters)
    selected = selection["selected"]
    days = selection["days"]
    total = selection["total"]
    bounded_count = selection["bounded_count"]
    sources_by_final, result_execution_ids = _logical_result_sources(selected)
    result_counts = _result_status_counts(result_execution_ids)

    zone_name = _zone_name(tz)
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


def _case_run_status(counts):
    for status in ("error", "failed", "passed", "skipped"):
        if counts.get(status):
            return status
    return "skipped"


def _display_case(case_ref, case_name, classname):
    if classname and case_name:
        return f"{classname}.{case_name}"
    return case_name or case_ref or classname or "(unnamed case)"


def failure_report(user, filters, tz=None):
    """Top-failing and flaky test-case report over terminal logical runs.

    A test case contributes at most one status per logical run. Multiple
    iterations/rows in that run collapse by severity: error, failed, passed,
    then skipped. Flaky candidate heuristic: at least FLAKY_MIN_EXECUTED_RUNS
    executed logical runs (passed+failed+error, skips excluded), with at least
    one passed and one failed/error run. Instability is
    2*min(passed, failed+error)/executed, so perfectly balanced alternation
    approaches 100 while a rare one-off failure approaches zero.
    """
    selection = _select_logical_runs(user, filters)
    selected = selection["selected"]
    sources_by_final, result_execution_ids = _logical_result_sources(selected)
    finals_by_id = {final.id: final for _run, final in selected}
    source_to_final = {source.id: final_id
                       for final_id, sources in sources_by_final.items()
                       for source in sources}
    project_ids = {final.project_id for _run, final in selected}
    projects = {}
    if project_ids:
        projects = {p.id: p.name for p in Project.query.filter(
            Project.id.in_(project_ids)).all()}

    grouped_rows = []
    if result_execution_ids:
        grouped_rows = (TestResult.query
                        .with_entities(TestResult.execution_id,
                                       TestResult.case_ref,
                                       TestResult.case_name,
                                       TestResult.classname,
                                       TestResult.status,
                                       func.count(TestResult.id))
                        .filter(TestResult.execution_id.in_(result_execution_ids))
                        .group_by(TestResult.execution_id,
                                  TestResult.case_ref,
                                  TestResult.case_name,
                                  TestResult.classname,
                                  TestResult.status)
                        .yield_per(1000))
    case_run_counts = {}
    case_meta = {}
    for execution_id, case_ref, case_name, classname, status, count in grouped_rows:
        final_id = source_to_final.get(execution_id)
        final = finals_by_id.get(final_id)
        if final is None:
            continue
        suite = final.snapshot().get("suite_name") or "(no suite)"
        key = (final.project_id, suite, case_ref or "",
               case_name or "", classname or "")
        case_meta.setdefault(key, {
            "_key": key,
            "project_id": final.project_id,
            "project": projects.get(final.project_id, final.project_id),
            "suite": suite,
            "case_ref": case_ref or "",
            "case_name": case_name or "",
            "classname": classname or "",
            "display_case": _display_case(case_ref or "", case_name or "",
                                          classname or ""),
        })
        st = _enum_value(status)
        counts = case_run_counts.setdefault((final_id, key), {})
        counts[st] = counts.get(st, 0) + count

    stats = {}
    for (final_id, key), counts in case_run_counts.items():
        status = _case_run_status(counts)
        row = stats.setdefault(key, dict(case_meta[key], runs=0, passed=0,
                                         failed=0, error=0, skipped=0))
        row["runs"] += 1
        row[status] += 1

    rows = []
    for row in stats.values():
        executed = row["passed"] + row["failed"] + row["error"]
        failures = row["failed"] + row["error"]
        row["executed_runs"] = executed
        row["failure_count"] = failures
        row["failure_rate"] = round(100 * failures / executed, 1) if executed else None
        row["instability_score"] = (round(200 * min(row["passed"], failures) / executed, 1)
                                    if executed else 0.0)
        row["flaky_candidate"] = (executed >= FLAKY_MIN_EXECUTED_RUNS
                                  and row["passed"] > 0 and failures > 0)
        rows.append(row)

    def case_sort(row):
        return (row["project"].lower(), row["suite"].lower(),
                row["display_case"].lower())

    top_all = [r for r in rows if r["failure_count"]]
    top_all.sort(key=lambda r: (-r["failure_count"], -(r["failure_rate"] or 0),
                                *case_sort(r)))
    flaky_all = [r for r in rows if r["flaky_candidate"]]
    flaky_all.sort(key=lambda r: (-r["instability_score"], -r["executed_runs"],
                                  *case_sort(r)))
    top_rows = top_all[:MAX_CASE_ROWS]
    flaky_rows = flaky_all[:MAX_CASE_ROWS]
    for rank, row in enumerate(top_rows, 1):
        row["top_failing_rank"] = rank
    for rank, row in enumerate(flaky_rows, 1):
        row["flaky_rank"] = rank
    for row in rows:
        row.setdefault("top_failing_rank", None)
        row.setdefault("flaky_rank", None)

    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "timezone": _zone_name(tz),
        "days": selection["days"], "rows": top_rows,
        "top_failing": top_rows, "flaky": flaky_rows,
        "total": selection["total"],
        "truncated": selection["total"] > selection["bounded_count"],
        "max_rows": MAX_REPORT_ROWS,
        "total_cases": len(rows),
        "failing_cases": len(top_all), "flaky_cases": len(flaky_all),
        "cases_truncated": len(top_all) > len(top_rows) or len(flaky_all) > len(flaky_rows),
        "max_case_rows": MAX_CASE_ROWS,
        "chart_rows": [{"case": r["display_case"][:80],
                        "count": r["failure_count"]} for r in top_rows[:10]],
        "counting": "logical runs; one status per case per run; skips excluded from executed denominator",
        "flaky_heuristic": (f"executed logical runs >= {FLAKY_MIN_EXECUTED_RUNS}, at least one pass "
                            "and one failure/error; instability=2*min(pass,fail)/executed"),
    }


def failure_csv(report):
    """Case-row CSV for the top-failing/flaky report."""
    import csv
    import io
    import json
    out = io.StringIO()
    fields = ["project", "suite", "case", "case_ref", "case_name", "classname",
              "logical_runs", "executed_runs", "passed", "failed", "error",
              "skipped", "failure_count", "failure_rate", "instability_score",
              "flaky_candidate", "top_failing_rank", "flaky_rank", "tz",
              "generated_at_utc", "report_type", "total_cases", "truncated",
              "max_case_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = json.dumps(report.get("filters", {}), sort_keys=True)
    combined = {}
    for row in report["top_failing"] + report["flaky"]:
        combined[row["_key"]] = row
    rows = sorted(combined.values(),
                  key=lambda r: (r["top_failing_rank"] is None,
                                 r["top_failing_rank"] or 10**9,
                                 r["flaky_rank"] or 10**9))
    for r in rows:
        w.writerow({
            "project": _csv_safe(r["project"]),
            "suite": _csv_safe(r["suite"]),
            "case": _csv_safe(r["display_case"]),
            "case_ref": _csv_safe(r["case_ref"]),
            "case_name": _csv_safe(r["case_name"]),
            "classname": _csv_safe(r["classname"]),
            "logical_runs": r["runs"],
            "executed_runs": r["executed_runs"],
            "passed": r["passed"], "failed": r["failed"],
            "error": r["error"], "skipped": r["skipped"],
            "failure_count": r["failure_count"],
            "failure_rate": r["failure_rate"],
            "instability_score": r["instability_score"],
            "flaky_candidate": "true" if r["flaky_candidate"] else "false",
            "top_failing_rank": r["top_failing_rank"] or "",
            "flaky_rank": r["flaky_rank"] or "",
            "tz": report["timezone"],
            "generated_at_utc": generated,
            "report_type": "failures",
            "total_cases": report["total_cases"],
            "truncated": "true" if report["cases_truncated"] or report["truncated"] else "false",
            "max_case_rows": report["max_case_rows"],
            "filters_json": filters_json,
        })
    return out.getvalue()


def failure_analysis_report(user, filters, tz=None):
    """Failure-kind breakdown over non-passed terminal logical runs.

    Explicit `error_kind` values win. Otherwise a failed logical run with
    failed/error parsed case evidence is classified as a test failure;
    non-passed runs with neither evidence nor a recorded kind stay honestly
    uncategorized instead of being folded into test failure.
    """
    selection = _select_logical_runs(user, filters)
    selected = selection["selected"]
    sources_by_final, result_execution_ids = _logical_result_sources(selected)
    result_counts = _result_status_counts(result_execution_ids)
    by_kind = {}
    analyzed = 0
    for _run, final in selected:
        kind = (final.error_kind or "").strip()
        counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
        for source in sources_by_final.get(final.id, [final]):
            source_counts = result_counts.get(source.id, {})
            for st in counts:
                counts[st] += source_counts.get(st, 0)
        has_test_failure = bool(counts["failed"] or counts["error"])
        if not kind and _enum_value(final.outcome) == "failed" and has_test_failure:
            kind = "test failure"
        elif not kind and _enum_value(final.outcome) != "passed":
            kind = "uncategorized"
        if not kind or _enum_value(final.outcome) == "passed":
            continue
        analyzed += 1
        row = by_kind.setdefault(kind, {
            "kind": kind, "logical_runs": 0, "projects": set(),
            "latest_finished": None, "example_execution_id": ""})
        row["logical_runs"] += 1
        row["projects"].add(final.project_id)
        if (row["latest_finished"] is None
                or _aw(final.finished_at) > _aw(row["latest_finished"])):
            row["latest_finished"] = final.finished_at
            row["example_execution_id"] = final.id
    order = {"test failure": 0, "license": 1, "config": 2,
             "infrastructure": 3, "execution": 4, "uncategorized": 5}
    rows = list(by_kind.values())
    rows.sort(key=lambda r: (-r["logical_runs"], order.get(r["kind"], 90),
                             r["kind"]))
    for row in rows:
        row["project_count"] = len(row.pop("projects"))
        row["share_pct"] = (round(100 * row["logical_runs"] / analyzed, 1)
                            if analyzed else None)
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "timezone": _zone_name(tz),
        "days": selection["days"], "rows": rows,
        "total": selection["total"], "analyzed_failures": analyzed,
        "truncated": selection["total"] > selection["bounded_count"],
        "max_rows": MAX_REPORT_ROWS,
        "counting": "logical runs; passed runs excluded; explicit error_kind wins; test failure requires failed/error case evidence",
    }


def failure_analysis_csv(report):
    """Failure-kind rows for the failure-analysis report."""
    import csv
    import io
    import json
    out = io.StringIO()
    fields = ["kind", "logical_runs", "share_pct", "project_count",
              "latest_finished_at_utc", "example_execution_id", "tz",
              "generated_at_utc", "report_type", "analyzed_failures",
              "total_logical_runs", "truncated", "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = json.dumps(report.get("filters", {}), sort_keys=True)
    for r in report["rows"]:
        w.writerow({
            "kind": _csv_safe(r["kind"]),
            "logical_runs": r["logical_runs"],
            "share_pct": r["share_pct"],
            "project_count": r["project_count"],
            "latest_finished_at_utc": _aw(r["latest_finished"]).isoformat()
                                      if r["latest_finished"] else "",
            "example_execution_id": r["example_execution_id"],
            "tz": report["timezone"],
            "generated_at_utc": generated,
            "report_type": "failure-analysis",
            "analyzed_failures": report["analyzed_failures"],
            "total_logical_runs": report["total"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"],
            "filters_json": filters_json,
        })
    return out.getvalue()


def schedule_reliability_report(user, filters, tz=None):
    """Schedule reliability over terminal logical runs and fire audit events.

    Run reliability uses final resolved logical-run outcomes. Misfire,
    overlap, target-unavailable and fire-failure counts come from the audited
    scheduler events in the same rolling window. Schedules with zero matching
    runs remain visible so silent schedules are not hidden.
    """
    selection = _select_logical_runs(user, filters)
    selected = selection["selected"]
    days = selection["days"]
    since = selection["since"]
    ids = visible_project_ids(user)
    sq = Schedule.query.filter(Schedule.project_id.in_(ids or [""]))
    project_id = (filters.get("project_id") or "").strip()
    if project_id:
        sq = sq.filter(Schedule.project_id == (project_id if project_id in ids else ""))
    schedules = sq.all()
    projects = {p.id: p.name for p in Project.query.filter(Project.id.in_(ids or [""])).all()} \
        if ids else {}
    rows = {}
    for sched in schedules:
        rows[sched.id] = {
            "schedule_id": sched.id, "name": sched.name,
            "project_id": sched.project_id,
            "project": projects.get(sched.project_id, sched.project_id),
            "target_type": sched.target_type, "kind": sched.kind,
            "enabled": sched.enabled, "runs": 0, "passed": 0,
            "failed": 0, "incomplete": 0, "none": 0,
            "success_rate": None, "fire_failures": 0,
            "misfire_skips": 0, "overlap_skips": 0,
            "target_unavailable": 0, "last_run_at": sched.last_run_at,
            "next_run_at": sched.next_run_at, "latest_outcome": "",
        }
    analyzed_runs = 0
    latest_by_schedule = {}
    for _run, final in selected:
        row = rows.get(final.schedule_id)
        if row is None:
            continue
        analyzed_runs += 1
        row["runs"] += 1
        oc = _enum_value(final.outcome) or "none"
        row[{"passed": "passed", "failed": "failed",
             "incomplete": "incomplete"}.get(oc, "none")] += 1
        prior = latest_by_schedule.get(final.schedule_id)
        if prior is None or _aw(final.finished_at) > _aw(prior.finished_at):
            latest_by_schedule[final.schedule_id] = final
    for sid, final in latest_by_schedule.items():
        rows[sid]["latest_outcome"] = _enum_value(final.outcome) or "none"

    event_map = {"schedule.fire_failed": "fire_failures",
                 "schedule.misfire_skipped": "misfire_skips",
                 "schedule.overlap_skipped": "overlap_skips",
                 "schedule.target_unavailable": "target_unavailable"}
    schedule_ids = set(rows)
    events = []
    if schedule_ids:
        # IDs are fixed-width uuid4 hex values; matching the first 32 detail
        # characters covers both exact IDs and "id: detail" audit payloads
        # while keeping the audit query scoped to visible schedules.
        events = (AuditEvent.query
                  .filter(AuditEvent.occurred_at >= since,
                          AuditEvent.event.in_(tuple(event_map)),
                          func.substr(AuditEvent.detail, 1, 32)
                          .in_(tuple(schedule_ids)))
                  .all())
    for event in events:
        detail_schedule = (event.detail or "").split(":", 1)[0]
        row = rows.get(detail_schedule)
        if row is not None:
            row[event_map[event.event]] += 1

    out = list(rows.values())
    for row in out:
        if row["runs"]:
            row["success_rate"] = round(100 * row["passed"] / row["runs"], 1)
    out.sort(key=lambda r: (r["success_rate"] is None,
                            r["success_rate"] if r["success_rate"] is not None else 0,
                            -(r["fire_failures"] + r["misfire_skips"]
                              + r["overlap_skips"] + r["target_unavailable"]),
                            -r["runs"], r["name"].lower()))
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "timezone": _zone_name(tz),
        "days": days, "rows": out, "total": analyzed_runs,
        "total_schedules": len(out),
        "truncated": selection["total"] > selection["bounded_count"],
        "max_rows": MAX_REPORT_ROWS,
        "counting": "terminal logical runs per schedule; audit fire events in the same window; zero-run schedules remain visible",
    }


def schedule_reliability_csv(report):
    """Schedule-row CSV for the schedule reliability report."""
    import csv
    import io
    import json
    out = io.StringIO()
    fields = ["schedule_id", "schedule", "project", "target_type", "kind",
              "enabled", "logical_runs", "passed", "failed", "incomplete",
              "none", "success_rate", "fire_failures", "misfire_skips",
              "overlap_skips", "target_unavailable", "last_run_at_utc",
              "next_run_at_utc", "latest_outcome", "tz", "generated_at_utc",
              "report_type", "total_schedules", "total_logical_runs",
              "truncated", "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = json.dumps(report.get("filters", {}), sort_keys=True)
    def iso(dt):
        return _aw(dt).isoformat() if dt else ""
    for r in report["rows"]:
        w.writerow({
            "schedule_id": r["schedule_id"],
            "schedule": _csv_safe(r["name"]),
            "project": _csv_safe(r["project"]),
            "target_type": r["target_type"], "kind": r["kind"],
            "enabled": "true" if r["enabled"] else "false",
            "logical_runs": r["runs"], "passed": r["passed"],
            "failed": r["failed"], "incomplete": r["incomplete"],
            "none": r["none"], "success_rate": r["success_rate"],
            "fire_failures": r["fire_failures"],
            "misfire_skips": r["misfire_skips"],
            "overlap_skips": r["overlap_skips"],
            "target_unavailable": r["target_unavailable"],
            "last_run_at_utc": iso(r["last_run_at"]),
            "next_run_at_utc": iso(r["next_run_at"]),
            "latest_outcome": r["latest_outcome"],
            "tz": report["timezone"], "generated_at_utc": generated,
            "report_type": "schedule-reliability",
            "total_schedules": report["total_schedules"],
            "total_logical_runs": report["total"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"],
            "filters_json": filters_json,
        })
    return out.getvalue()


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
