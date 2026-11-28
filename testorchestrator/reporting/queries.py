"""Scoped reporting queries.

The initial Reports-menu slices intentionally reuse the execution schema,
analytics logical-run semantics and project scoping rules without adding export
dependencies. Every caller gets a query already restricted to projects the user
may see; client-supplied project filters are intersected with that
authorization scope, never trusted.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..analytics import (LOGICAL_ROLES, TERMINAL, _aw, _day,
                         resolve_logical_runs)
from ..extensions import db
from ..execution import (DiscoveredItem, Execution, Plan, Project, Release,
                         ReleaseItem, Runner, RuntimeConnection, Schedule, Suite,
                         TestResult)
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
    for field in ("state", "outcome", "suite_id", "runner_id",
                  "schedule_id", "release_id"):
        value = (filters.get(field) or "").strip()
        if value:
            q = q.filter(getattr(Execution, field) == value)
    created_by = (filters.get("user") or "").strip()
    if created_by:
        q = q.filter(Execution.created_by == created_by)
    source_sha = (filters.get("source_sha") or "").strip()
    if source_sha:
        q = q.filter(Execution.source_sha == source_sha)
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
    for field in ("state", "outcome", "suite_id", "runner_id",
                  "schedule_id", "release_id"):
        expected = (filters.get(field) or "").strip()
        if expected and _enum_value(getattr(final, field)) != expected:
            return False
    environment = (filters.get("environment") or "").strip()
    if environment == "__none__" and final.environment is not None:
        return False
    if environment not in ("", "__none__") and final.environment != environment:
        return False
    created_by = (filters.get("user") or "").strip()
    if created_by and final.created_by != created_by:
        return False
    source_sha = (filters.get("source_sha") or "").strip()
    if source_sha and final.source_sha != source_sha:
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


def _scope_allows(scope_json, visible_ids):
    """Empty scope is a wildcard; otherwise intersect with visible projects."""
    try:
        allowed = set(json.loads(scope_json or "[]"))
    except (TypeError, ValueError):
        allowed = set()
    return bool(visible_ids) and (not allowed or bool(allowed.intersection(visible_ids)))


def traceability_report(user, filters, tz=None):
    """Release-to-repository-target traceability and execution evidence.

    Release items are matched to immutable execution source_target triples by
    binding+kind+path. If the item's stored discovered-item link is absent,
    the binding is inferred only when exactly one current inventory candidate
    exists; ambiguous paths are not conflated across bindings. Evidence uses
    terminal logical runs, so retries count once. This is release/test-target
    traceability — the product has no requirement/issue-link model yet.
    """
    ids = visible_project_ids(user)
    days = _bounded_days(filters.get("days"))
    project_id = (filters.get("project_id") or "").strip()
    rq = (db.session.query(ReleaseItem, Release)
          .join(Release, ReleaseItem.release_id == Release.id)
          .filter(Release.project_id.in_(ids or [""])))
    if project_id:
        rq = rq.filter(Release.project_id == (project_id if project_id in ids else ""))
    total_items = rq.count()
    item_rows = (rq.order_by(Release.name, ReleaseItem.path)
                 .limit(MAX_REPORT_ROWS).all())
    source_ids = [item.source_item_id for item, _rel in item_rows
                  if item.source_item_id]
    direct_items = {d.id: d for d in DiscoveredItem.query.filter(
        DiscoveredItem.id.in_(source_ids or [""])).all()}
    unresolved_pairs = {(item.kind, item.path) for item, _rel in item_rows
                        if item.source_item_id not in direct_items}
    candidates_by_pair = {}
    if unresolved_pairs:
        paths = [path for _kind, path in unresolved_pairs]
        kinds = [kind for kind, _path in unresolved_pairs]
        candidates = DiscoveredItem.query.filter(
            DiscoveredItem.project_id.in_(ids or [""]),
            DiscoveredItem.kind.in_(kinds),
            DiscoveredItem.path.in_(paths)).all()
        for cand in candidates:
            if (cand.kind, cand.path) in unresolved_pairs:
                candidates_by_pair.setdefault((cand.kind, cand.path), []).append(cand)

    selection = _select_logical_runs(user, filters)
    selected = selection["selected"]
    sources_by_final, result_ids = _logical_result_sources(selected)
    result_counts = _result_status_counts(result_ids)
    evidence = {}
    for _run, final in selected:
        st = (final.snapshot().get("source_target") or {})
        key = (final.project_id, st.get("binding_id") or "",
               st.get("kind") or "", st.get("path") or "")
        if not all(key):
            continue
        evidence.setdefault(key, []).append((final, sources_by_final.get(final.id, [])))

    rows = []
    status_counts = {}
    for item, rel in item_rows:
        direct = direct_items.get(item.source_item_id)
        pair = (item.kind, item.path)
        candidates = candidates_by_pair.get(pair, [])
        binding_id = ""
        name = item.path
        framework = ""
        link_state = "unresolved"
        if direct is not None:
            binding_id = direct.binding_id
            name = direct.name or item.path
            framework = direct.framework or "katalon"
            link_state = "linked"
        elif candidates:
            bindings = {c.binding_id for c in candidates}
            if len(bindings) == 1:
                cand = candidates[0]
                binding_id = cand.binding_id
                name = cand.name or item.path
                framework = cand.framework or "katalon"
                link_state = "inferred"
            else:
                link_state = "ambiguous"
        key = (rel.project_id, binding_id, item.kind, item.path)
        matches = evidence.get(key, []) if binding_id else []
        count = len(matches)
        passed = failed = incomplete = none = 0
        case_passed = case_failed = case_error = case_skipped = 0
        latest = None
        duration_total = 0.0
        duration_count = 0
        for final, sources in matches:
            outcome = _enum_value(final.outcome) or "none"
            if outcome == "passed":
                passed += 1
            elif outcome == "failed":
                failed += 1
            elif outcome == "incomplete":
                incomplete += 1
            else:
                none += 1
            if latest is None or _aw(final.finished_at) > _aw(latest.finished_at):
                latest = final
            if final.started_at and final.finished_at:
                duration_total += max(0.0, (_aw(final.finished_at)
                                            - _aw(final.started_at)).total_seconds())
                duration_count += 1
            for source in sources:
                counts = result_counts.get(source.id, {})
                case_passed += counts.get("passed", 0)
                case_failed += counts.get("failed", 0)
                case_error += counts.get("error", 0)
                case_skipped += counts.get("skipped", 0)
        latest_outcome = (_enum_value(latest.outcome) or "none") if latest else ""
        if not count:
            coverage = "no evidence"
        elif latest_outcome == "passed":
            coverage = "passing"
        elif latest_outcome == "failed":
            coverage = "failing"
        elif latest_outcome == "incomplete":
            coverage = "incomplete"
        else:
            coverage = "no outcome"
        status_counts[coverage] = status_counts.get(coverage, 0) + 1
        denom = case_passed + case_failed + case_error
        rows.append({
            "release_id": rel.id, "release": rel.name,
            "release_status": rel.status, "project_id": rel.project_id,
            "kind": item.kind, "path": item.path, "name": name,
            "framework": framework, "link_state": link_state,
            "runs": count, "passed": passed, "failed": failed,
            "incomplete": incomplete, "none": none,
            "run_pass_rate": round(100 * passed / count, 1) if count else None,
            "case_passed": case_passed, "case_failed": case_failed,
            "case_error": case_error, "case_skipped": case_skipped,
            "case_pass_rate": round(100 * case_passed / denom, 1) if denom else None,
            "avg_duration_s": round(duration_total / duration_count, 1)
            if duration_count else None,
            "latest_finished_at": latest.finished_at if latest else None,
            "latest_outcome": latest_outcome,
            "coverage": coverage,
        })
    projects = {p.id: p.name for p in Project.query.filter(Project.id.in_(ids or [""])).all()}
    for row in rows:
        row["project"] = projects.get(row["project_id"], row["project_id"])
    rank = {"failing": 0, "no evidence": 1, "incomplete": 2,
            "no outcome": 3, "passing": 4}
    rows.sort(key=lambda r: (rank.get(r["coverage"], 5), -r["runs"],
                             r["release"].lower(), r["path"]))
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters), "timezone": _zone_name(tz),
        "days": days, "rows": rows, "total": total_items,
        "evidence_runs": sum(r["runs"] for r in rows),
        "status_counts": status_counts,
        "rows_truncated": total_items > len(item_rows),
        "runs_truncated": selection["total"] > selection["bounded_count"],
        "truncated": (total_items > len(item_rows)
                      or selection["total"] > selection["bounded_count"]),
        "max_rows": MAX_REPORT_ROWS,
        "counting": "release items matched exactly by project+binding+kind+path to terminal logical-run source targets; retries count once; ambiguous same-path bindings are never conflated; no requirement/issue-link model exists yet",
    }


def traceability_csv(report):
    """CSV rows for release traceability."""
    import csv
    import io
    import json as _json
    out = io.StringIO()
    fields = ["release", "release_status", "project", "kind", "path", "name",
              "framework", "link_state", "coverage", "logical_runs",
              "passed", "failed", "incomplete", "none", "run_pass_rate",
              "case_passed", "case_failed", "case_error", "case_skipped",
              "case_pass_rate", "avg_duration_s", "latest_finished_at_utc",
              "latest_outcome", "tz", "generated_at_utc", "report_type",
              "total_release_items", "evidence_runs", "truncated",
              "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = _json.dumps(report.get("filters", {}), sort_keys=True)
    for r in report["rows"]:
        w.writerow({
            "release": _csv_safe(r["release"]),
            "release_status": r["release_status"],
            "project": _csv_safe(r.get("project", "")),
            "kind": r["kind"], "path": _csv_safe(r["path"]),
            "name": _csv_safe(r["name"]), "framework": r["framework"],
            "link_state": r["link_state"], "coverage": r["coverage"],
            "logical_runs": r["runs"], "passed": r["passed"],
            "failed": r["failed"], "incomplete": r["incomplete"],
            "none": r["none"], "run_pass_rate": r["run_pass_rate"],
            "case_passed": r["case_passed"],
            "case_failed": r["case_failed"],
            "case_error": r["case_error"],
            "case_skipped": r["case_skipped"],
            "case_pass_rate": r["case_pass_rate"],
            "avg_duration_s": r["avg_duration_s"],
            "latest_finished_at_utc": (_aw(r["latest_finished_at"]).isoformat()
                                       if r["latest_finished_at"] else ""),
            "latest_outcome": r["latest_outcome"], "tz": report["timezone"],
            "generated_at_utc": generated, "report_type": "traceability",
            "total_release_items": report["total"],
            "evidence_runs": report["evidence_runs"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"], "filters_json": filters_json,
        })
    return out.getvalue()


def audit_compliance_report(user, filters, tz=None):
    """Admin-only audit/compliance summary and bounded event rows.

    Event-type aggregates are computed in SQL over the full selected window;
    the detailed rows are separately capped at MAX_REPORT_ROWS and truncation
    is disclosed. Audit details were redacted before persistence by the audit
    writer. This report is global system evidence and must only be exposed to
    Admin users by the route layer.
    """
    days = _bounded_days(filters.get("days"))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = AuditEvent.query.filter(AuditEvent.occurred_at >= since)
    event_filter = (filters.get("event") or "").strip()
    username_filter = (filters.get("username") or "").strip()
    if event_filter:
        q = q.filter(AuditEvent.event == event_filter)
    if username_filter:
        q = q.filter(AuditEvent.username == username_filter)
    total = q.count()
    rows = (q.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .limit(MAX_REPORT_ROWS).all())
    aggregates = []
    agg_rows = (q.with_entities(
        AuditEvent.event,
        func.count(AuditEvent.id),
        func.count(func.distinct(AuditEvent.username)),
        func.min(AuditEvent.occurred_at),
        func.max(AuditEvent.occurred_at))
        .group_by(AuditEvent.event)
        .order_by(func.count(AuditEvent.id).desc(), AuditEvent.event)
        .all())
    for event, count, users, first, last in agg_rows:
        aggregates.append({"event": event, "count": count,
                           "user_count": users,
                           "first_at": first, "last_at": last})
    distinct_users = (q.with_entities(func.count(func.distinct(AuditEvent.username)))
                      .scalar() or 0)
    export_count = (q.filter(AuditEvent.event.like("%export%")).count())
    detail_rows = [{
        "id": row.id, "occurred_at": row.occurred_at,
        "username": row.username, "event": row.event,
        "detail": row.detail,
    } for row in rows]
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "timezone": _zone_name(tz), "days": days,
        "rows": detail_rows, "aggregates": aggregates,
        "total": total, "distinct_users": distinct_users,
        "event_type_count": len(aggregates), "export_count": export_count,
        "truncated": total > len(detail_rows), "max_rows": MAX_REPORT_ROWS,
        "counting": "admin-only global audit events in the rolling window; event aggregates cover the full window while detail rows are capped and truncation is disclosed",
    }


def audit_compliance_csv(report):
    """Detailed audit-event CSV rows plus report metadata."""
    import csv
    import io
    import json as _json
    out = io.StringIO()
    fields = ["audit_id", "occurred_at_utc", "username", "event", "detail",
              "tz", "generated_at_utc", "report_type", "total_events",
              "truncated", "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = _json.dumps(report.get("filters", {}), sort_keys=True)
    for r in report["rows"]:
        w.writerow({
            "audit_id": r["id"],
            "occurred_at_utc": _aw(r["occurred_at"]).isoformat(),
            "username": _csv_safe(r["username"]),
            "event": _csv_safe(r["event"]),
            "detail": _csv_safe(r["detail"]),
            "tz": report["timezone"], "generated_at_utc": generated,
            "report_type": "audit-compliance",
            "total_events": report["total"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"], "filters_json": filters_json,
        })
    return out.getvalue()


def framework_comparison_report(user, filters, tz=None):
    """Compare outcome/case/duration metrics by attributed test framework.

    Framework attribution comes from the immutable repository source target;
    app-side and legacy KRE suites are Katalon. Native collection operations
    are inventory maintenance, not test executions, and are excluded with a
    disclosed count. Ambiguous legacy rows remain in an explicit unknown
    bucket rather than being guessed into a framework.
    """
    selection = _select_logical_runs(user, filters)
    selected = selection["selected"]
    sources_by_final, result_ids = _logical_result_sources(selected)
    result_counts = _result_status_counts(result_ids)
    rows = {}
    excluded_collection_ops = 0

    def row_for(framework):
        row = rows.get(framework)
        if row is None:
            row = rows[framework] = {
                "framework": framework, "runs": 0, "passed": 0,
                "failed": 0, "incomplete": 0, "none": 0,
                "run_pass_rate": None, "case_passed": 0,
                "case_failed": 0, "case_error": 0, "case_skipped": 0,
                "case_pass_rate": None, "duration_total": 0.0,
                "duration_count": 0, "avg_duration_s": None,
                "projects": set(), "project_count": 0,
            }
        return row

    for _run, final in selected:
        snap = final.snapshot()
        rc = snap.get("run_config") or {}
        if rc.get("native_collect"):
            excluded_collection_ops += 1
            continue
        st = snap.get("source_target") or {}
        if st.get("framework"):
            framework = st["framework"]
        elif st or final.suite_id or snap.get("suite_id"):
            framework = "katalon"
        else:
            framework = "unknown"
        row = row_for(framework)
        row["runs"] += 1
        row["projects"].add(final.project_id)
        outcome = _enum_value(final.outcome) or "none"
        row[{"passed": "passed", "failed": "failed",
             "incomplete": "incomplete"}.get(outcome, "none")] += 1
        if final.started_at and final.finished_at:
            row["duration_total"] += max(
                0.0, (_aw(final.finished_at)
                      - _aw(final.started_at)).total_seconds())
            row["duration_count"] += 1
        for source in sources_by_final.get(final.id, []):
            counts = result_counts.get(source.id, {})
            row["case_passed"] += counts.get("passed", 0)
            row["case_failed"] += counts.get("failed", 0)
            row["case_error"] += counts.get("error", 0)
            row["case_skipped"] += counts.get("skipped", 0)

    out = []
    for row in rows.values():
        if row["runs"]:
            row["run_pass_rate"] = round(
                100 * row["passed"] / row["runs"], 1)
        denom = row["case_passed"] + row["case_failed"] + row["case_error"]
        if denom:
            row["case_pass_rate"] = round(100 * row["case_passed"] / denom, 1)
        if row["duration_count"]:
            row["avg_duration_s"] = round(
                row["duration_total"] / row["duration_count"], 1)
        row["project_count"] = len(row["projects"])
        row["projects"] = sorted(row["projects"])
        row.pop("duration_total", None)
        row.pop("duration_count", None)
        out.append(row)
    out.sort(key=lambda r: (-r["runs"], r["framework"]))
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "timezone": _zone_name(tz), "days": selection["days"],
        "rows": out, "total": sum(r["runs"] for r in out),
        "excluded_collection_ops": excluded_collection_ops,
        "truncated": selection["total"] > selection["bounded_count"],
        "max_rows": MAX_REPORT_ROWS,
        "counting": "terminal logical runs by immutable framework attribution; retries count once; case pass-rate excludes skipped; native collection operations are excluded and disclosed; ambiguous legacy rows remain unknown",
    }


def framework_comparison_csv(report):
    """CSV rows for framework comparison."""
    import csv
    import io
    import json as _json
    out = io.StringIO()
    fields = ["framework", "logical_runs", "passed", "failed", "incomplete",
              "none", "run_pass_rate", "case_passed", "case_failed",
              "case_error", "case_skipped", "case_pass_rate",
              "avg_duration_s", "project_count", "tz", "generated_at_utc",
              "report_type", "total_logical_runs", "excluded_collection_ops",
              "truncated", "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = _json.dumps(report.get("filters", {}), sort_keys=True)
    for r in report["rows"]:
        w.writerow({
            "framework": _csv_safe(r["framework"]),
            "logical_runs": r["runs"], "passed": r["passed"],
            "failed": r["failed"], "incomplete": r["incomplete"],
            "none": r["none"], "run_pass_rate": r["run_pass_rate"],
            "case_passed": r["case_passed"],
            "case_failed": r["case_failed"],
            "case_error": r["case_error"],
            "case_skipped": r["case_skipped"],
            "case_pass_rate": r["case_pass_rate"],
            "avg_duration_s": r["avg_duration_s"],
            "project_count": r["project_count"],
            "tz": report["timezone"], "generated_at_utc": generated,
            "report_type": "framework-comparison",
            "total_logical_runs": report["total"],
            "excluded_collection_ops": report["excluded_collection_ops"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"], "filters_json": filters_json,
        })
    return out.getvalue()


def target_results_report(user, filters, tz=None):
    """Results grouped by plan, app-side suite, repository suite/collection.

    Rows aggregate member terminal logical runs for the target definition. In
    particular, plan rows count member suite executions; they are not yet a
    whole-plan-run rollup. Repository target identity is binding+kind+path
    from the immutable source_target snapshot, so inventory replacement does
    not split history.
    """
    selection = _select_logical_runs(user, filters)
    selected = selection["selected"]
    ids = visible_project_ids(user)
    plans = {p.id: p.name for p in Plan.query.filter(Plan.project_id.in_(ids or [""])).all()}
    suites = {s.id: s.name for s in Suite.query.filter(Suite.project_id.in_(ids or [""])).all()}
    rows = {}
    omitted = 0

    def new_row(key, target_type, name, project_id, path="", ref=""):
        return {"key": key, "target_type": target_type, "name": name,
                "project_id": project_id, "path": path, "source_ref": ref,
                "runs": 0, "passed": 0, "failed": 0, "incomplete": 0,
                "none": 0, "success_rate": None, "duration_total": 0.0,
                "duration_count": 0, "avg_duration_s": None,
                "last_finished_at": None, "latest_outcome": ""}

    for _run, final in selected:
        snap = final.snapshot()
        st = snap.get("source_target") or {}
        plan_id = snap.get("plan_id") or ""
        if plan_id:
            key = ("plan", plan_id)
            target_type = "plan"
            name = plans.get(plan_id, plan_id)
            path = ""
            ref = ""
        elif final.suite_id:
            key = ("suite", final.suite_id)
            target_type = "suite"
            name = suites.get(final.suite_id,
                              snap.get("suite_name") or final.suite_id)
            path = ""
            ref = ""
        elif st.get("kind") in ("suite", "collection"):
            key = (st.get("kind"), st.get("binding_id") or "",
                   st.get("path") or "")
            target_type = st.get("kind")
            name = st.get("name") or st.get("path") or "repository target"
            path = st.get("path") or ""
            ref = final.source_ref or ""
        else:
            omitted += 1
            continue
        row = rows.get(key)
        if row is None:
            row = rows[key] = new_row(key, target_type, name,
                                      final.project_id, path, ref)
        elif ref and row["source_ref"] != ref:
            row["source_ref"] = "multiple"
        row["runs"] += 1
        outcome = _enum_value(final.outcome) or "none"
        row[{"passed": "passed", "failed": "failed",
             "incomplete": "incomplete"}.get(outcome, "none")] += 1
        if final.started_at and final.finished_at:
            duration = max(0.0, (_aw(final.finished_at)
                                 - _aw(final.started_at)).total_seconds())
            row["duration_total"] += duration
            row["duration_count"] += 1
        if (row["last_finished_at"] is None
                or _aw(final.finished_at) > _aw(row["last_finished_at"])):
            row["last_finished_at"] = final.finished_at
            row["latest_outcome"] = outcome

    projects = {p.id: p.name for p in Project.query.filter(Project.id.in_(ids or [""])).all()}
    out = []
    for row in rows.values():
        row["project"] = projects.get(row["project_id"], row["project_id"])
        if row["runs"]:
            row["success_rate"] = round(100 * row["passed"] / row["runs"], 1)
        if row["duration_count"]:
            row["avg_duration_s"] = round(
                row["duration_total"] / row["duration_count"], 1)
        row.pop("duration_total", None)
        row.pop("duration_count", None)
        out.append(row)
    out.sort(key=lambda r: (r["success_rate"] if r["success_rate"] is not None else 101,
                            -r["runs"], r["target_type"], r["name"].lower()))
    return {
        "generated_at": datetime.now(timezone.utc),
        "filters": _filter_snapshot(filters),
        "timezone": _zone_name(tz), "days": selection["days"],
        "rows": out, "total": sum(r["runs"] for r in out),
        "total_targets": len(out), "omitted_logical_runs": omitted,
        "truncated": selection["total"] > selection["bounded_count"],
        "max_rows": MAX_REPORT_ROWS,
        "counting": "terminal logical runs grouped by immutable target identity; plan rows aggregate member suite executions (not whole-plan-run rollups); direct test/case targets are omitted and disclosed",
    }


def target_results_csv(report):
    """CSV rows for the plan/suite/collection target report."""
    import csv
    import io
    import json as _json
    out = io.StringIO()
    fields = ["target_type", "target", "project", "path", "source_ref",
              "logical_runs", "passed", "failed", "incomplete", "none",
              "member_pass_rate", "avg_duration_s", "last_finished_at_utc",
              "latest_outcome", "tz", "generated_at_utc", "report_type",
              "total_targets", "total_logical_runs", "omitted_logical_runs",
              "truncated", "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = _json.dumps(report.get("filters", {}), sort_keys=True)
    for r in report["rows"]:
        w.writerow({
            "target_type": r["target_type"],
            "target": _csv_safe(r["name"]),
            "project": _csv_safe(r.get("project", "")),
            "path": _csv_safe(r.get("path", "")),
            "source_ref": _csv_safe(r.get("source_ref", "")),
            "logical_runs": r["runs"], "passed": r["passed"],
            "failed": r["failed"], "incomplete": r["incomplete"],
            "none": r["none"], "member_pass_rate": r["success_rate"],
            "avg_duration_s": r["avg_duration_s"],
            "last_finished_at_utc": (_aw(r["last_finished_at"]).isoformat()
                                     if r["last_finished_at"] else ""),
            "latest_outcome": r["latest_outcome"],
            "tz": report["timezone"],
            "generated_at_utc": generated,
            "report_type": "target-results",
            "total_targets": report["total_targets"],
            "total_logical_runs": report["total"],
            "omitted_logical_runs": report["omitted_logical_runs"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"], "filters_json": filters_json,
        })
    return out.getvalue()


def utilization_report(user, filters, tz=None):
    """Attempt-level runner/runtime utilization in the rolling window.

    Utilization intentionally uses terminal execution attempts, not logical
    runs: retries and partition units consume real capacity. Busy time is the
    overlap of [started_at, finished_at] with the report window. Capacity
    percentages use the dispatch ceiling min(max_slots, license_slots) for
    runners and min(runtime concurrency, host runner ceiling) for runtimes.
    """
    q, days = scoped_executions(user, filters, windowed=False)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    terminal = tuple(TERMINAL)
    q = q.filter(Execution.state.in_(terminal),
                 Execution.started_at.isnot(None),
                 Execution.finished_at.isnot(None),
                 Execution.finished_at >= since,
                 Execution.started_at < now)
    total = q.count()
    attempts = (q.order_by(Execution.finished_at.desc())
                .limit(MAX_REPORT_ROWS).all())
    ids = visible_project_ids(user)
    visible_ids = set(ids)
    all_runners = {r.id: r for r in Runner.query.all()}
    all_runtimes = {r.id: r for r in RuntimeConnection.query.all()}

    runner_rows = {}
    runtime_rows = {}

    def runner_row(runner):
        capacity = max(1, min(runner.max_slots or 1,
                              runner.license_slots or runner.max_slots or 1))
        return {
            "runner_id": runner.id, "name": runner.name,
            "target_type": runner.target_type, "os_arch": runner.os_arch,
            "enabled": runner.enabled, "draining": runner.draining,
            "health": runner.health, "capacity": capacity,
            "attempts": 0, "passed": 0, "failed": 0, "incomplete": 0,
            "none": 0, "busy_seconds": 0.0, "utilization_pct": 0.0,
            "pass_rate": None, "last_finished_at": None,
        }

    def runtime_row(runtime):
        runner = all_runners.get(runtime.runner_id)
        runner_capacity = 1
        if runner is not None:
            runner_capacity = max(1, min(runner.max_slots or 1,
                                         runner.license_slots
                                         or runner.max_slots or 1))
        capacity = max(1, min(runtime.concurrency or 1, runner_capacity))
        return {
            "runtime_id": runtime.id, "name": runtime.name,
            "runtime_kind": runtime.runtime_kind,
            "runner_id": runtime.runner_id,
            "runner": runner.name if runner else "",
            "enabled": runtime.enabled, "capacity": capacity,
            "attempts": 0, "passed": 0, "failed": 0, "incomplete": 0,
            "none": 0, "busy_seconds": 0.0, "utilization_pct": 0.0,
            "pass_rate": None, "last_finished_at": None,
        }

    for runner in all_runners.values():
        if _scope_allows(runner.allowed_projects, visible_ids):
            runner_rows[runner.id] = runner_row(runner)
    for runtime in all_runtimes.values():
        if (runtime.runner_id in runner_rows
                and _scope_allows(runtime.allowed_projects, visible_ids)):
            runtime_rows[runtime.id] = runtime_row(runtime)

    window_seconds = days * 86400
    unassigned_attempts = 0
    for ex in attempts:
        start = max(_aw(ex.started_at), since)
        end = min(_aw(ex.finished_at), now)
        busy = max(0.0, (end - start).total_seconds())
        outcome = _enum_value(ex.outcome) or "none"
        bucket = {"passed": "passed", "failed": "failed",
                  "incomplete": "incomplete"}.get(outcome, "none")
        if not ex.runner_id and not ex.runtime_id:
            unassigned_attempts += 1
        if ex.runner_id:
            row = runner_rows.get(ex.runner_id)
            if row is None and ex.runner_id in all_runners:
                # Historical visible execution data wins over the runner's
                # current scope: a scope edit must not erase past usage.
                row = runner_rows[ex.runner_id] = runner_row(
                    all_runners[ex.runner_id])
            if row is not None:
                row["attempts"] += 1
                row[bucket] += 1
                row["busy_seconds"] += busy
                if (row["last_finished_at"] is None
                        or _aw(ex.finished_at) > _aw(row["last_finished_at"])):
                    row["last_finished_at"] = ex.finished_at
        if ex.runtime_id:
            row = runtime_rows.get(ex.runtime_id)
            if row is None and ex.runtime_id in all_runtimes:
                row = runtime_rows[ex.runtime_id] = runtime_row(
                    all_runtimes[ex.runtime_id])
            if row is not None:
                row["attempts"] += 1
                row[bucket] += 1
                row["busy_seconds"] += busy
                if (row["last_finished_at"] is None
                        or _aw(ex.finished_at) > _aw(row["last_finished_at"])):
                    row["last_finished_at"] = ex.finished_at

    def finish_rows(rows):
        out = list(rows.values())
        for row in out:
            row["busy_seconds"] = round(row["busy_seconds"], 1)
            row["utilization_pct"] = round(
                100 * row["busy_seconds"]
                / (window_seconds * row["capacity"]), 2)
            if row["attempts"]:
                row["pass_rate"] = round(
                    100 * row["passed"] / row["attempts"], 1)
        out.sort(key=lambda r: (-r["utilization_pct"], -r["attempts"],
                                r["name"].lower()))
        return out

    runner_out = finish_rows(runner_rows)
    runtime_out = finish_rows(runtime_rows)
    return {
        "generated_at": now, "filters": _filter_snapshot(filters),
        "timezone": _zone_name(tz), "days": days,
        "runner_rows": runner_out, "runtime_rows": runtime_out,
        "rows": runner_out, "total": total,
        "analyzed_attempts": len(attempts),
        "unassigned_attempts": unassigned_attempts,
        "truncated": total > len(attempts), "max_rows": MAX_REPORT_ROWS,
        "counting": "terminal execution attempts (retries/units included because they consume capacity); busy time clipped to the report window; zero-use visible runners/runtimes remain visible",
    }


def utilization_csv(report):
    """Combined runner/runtime CSV for the utilization report."""
    import csv
    import io
    import json as _json
    out = io.StringIO()
    fields = ["resource_type", "resource_id", "name", "runner", "kind",
              "enabled", "capacity", "attempts", "passed", "failed",
              "incomplete", "none", "pass_rate", "busy_seconds",
              "utilization_pct", "last_finished_at_utc", "tz",
              "generated_at_utc", "report_type", "total_attempts",
              "analyzed_attempts", "unassigned_attempts", "truncated",
              "max_rows", "filters_json"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    generated = report["generated_at"].isoformat()
    filters_json = _json.dumps(report.get("filters", {}), sort_keys=True)
    def write_resource(resource_type, r):
        w.writerow({
            "resource_type": resource_type,
            "resource_id": r.get("runner_id" if resource_type == "runner"
                                 else "runtime_id"),
            "name": _csv_safe(r["name"]),
            "runner": _csv_safe(r.get("runner", "")),
            "kind": r.get("target_type") or r.get("runtime_kind", ""),
            "enabled": "true" if r["enabled"] else "false",
            "capacity": r["capacity"], "attempts": r["attempts"],
            "passed": r["passed"], "failed": r["failed"],
            "incomplete": r["incomplete"], "none": r["none"],
            "pass_rate": r["pass_rate"],
            "busy_seconds": r["busy_seconds"],
            "utilization_pct": r["utilization_pct"],
            "last_finished_at_utc": (_aw(r["last_finished_at"]).isoformat()
                                     if r["last_finished_at"] else ""),
            "tz": report["timezone"],
            "generated_at_utc": generated,
            "report_type": "utilization",
            "total_attempts": report["total"],
            "analyzed_attempts": report["analyzed_attempts"],
            "unassigned_attempts": report["unassigned_attempts"],
            "truncated": "true" if report["truncated"] else "false",
            "max_rows": report["max_rows"], "filters_json": filters_json,
        })
    for row in report["runner_rows"]:
        write_resource("runner", row)
    for row in report["runtime_rows"]:
        write_resource("runtime", row)
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
