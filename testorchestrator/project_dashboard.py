"""Project-level dashboard aggregation — metric queries kept separate
from chart presentation (charts.py builds figures from these rows)."""
from datetime import datetime, timedelta, timezone
from .execution import Execution, ExecutionState

TERMINAL = {ExecutionState.COMPLETED, ExecutionState.FAILED,
            ExecutionState.CANCELED}


def _aw(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _lday(dt, tz=None) -> str:
    aware = _aw(dt)
    if tz is not None:
        aware = aware.astimezone(tz)
    return aware.date().isoformat()


def summary(project_id: str, days: int = 30, suite: str = "",
            state: str = "", source_ref: str = "",
            environment: str = "", tz=None) -> dict:
    """`tz` = viewer's display zone — per-day chart buckets group by
    the user's local calendar day (UTC when not passed)."""
    since = _aw(datetime.now(timezone.utc) - timedelta(days=days))
    q = Execution.query.filter_by(project_id=project_id)
    if suite:
        q = q.filter_by(suite_id=suite)
    if state:
        q = q.filter_by(state=state)
    if source_ref:
        # "(unavailable)" selects the historical/NULL records
        if source_ref == "__none__":
            q = q.filter(Execution.source_ref.is_(None))
        else:
            q = q.filter_by(source_ref=source_ref)
    if environment:
        if environment == "__none__":
            q = q.filter(Execution.environment.is_(None))
        else:
            q = q.filter_by(environment=environment)
    exes = [e for e in q.all()
            if e.state in TERMINAL and e.finished_at
            and _aw(e.finished_at) >= since]
    exes.sort(key=lambda e: e.finished_at)

    # outcome trend: per-day terminal executions
    by_day = {}
    for e in exes:
        d = _lday(e.finished_at, tz)
        row = by_day.setdefault(d, {"day": d, "passed": 0,
                                    "failed": 0, "error": 0,
                                    "skipped": 0})
        row[e.outcome.value if e.outcome.value in
            ("passed", "failed", "error", "skipped") else "error"] += 1

    # pass-rate trend: test-case outcomes per day, skips excluded
    pr_by_day = {}
    durations = []
    for e in exes:
        d = _lday(e.finished_at, tz)
        pr = pr_by_day.setdefault(d, {"day": d, "passed": 0,
                                      "failed": 0, "error": 0,
                                      "skipped": 0})
        for r in e.results:
            if r.status in ("passed", "failed", "error", "skipped"):
                pr[r.status] += 1
        if e.started_at and e.finished_at:
            durations.append({
                "day": _lday(e.finished_at, tz),
                "seconds": (_aw(e.finished_at)
                            - _aw(e.started_at)).total_seconds()})

    # failure breakdown: failing test cases by frequency
    fail_counts = {}
    for e in exes:
        for r in e.results:
            if r.status in ("failed", "error"):
                fail_counts[r.case_name] = \
                    fail_counts.get(r.case_name, 0) + 1
    failures = [{"case": c, "count": n}
                for c, n in sorted(fail_counts.items(),
                                   key=lambda x: -x[1])[:10]]

    return {
        "outcome_trend": list(by_day.values()),
        "pass_rate": list(pr_by_day.values()),
        "durations": durations,
        "failures": failures,
        "executions": exes[-15:][::-1],      # newest first
        "total": len(exes),
        "period_days": days,
    }
