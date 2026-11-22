"""Advanced-dashboard aggregation — metric queries kept separate from
chart presentation (charts.py builds figures from these rows).

Counting policy: docs/analytics-counting.md. Terms:
- logical run  = retry-chain head, role in ("", "parent"); resolved to
  its final TERMINAL attempt for outcome metrics.
- attempt      = one Execution row (retries are separate rows).
- unit         = role="unit" shard child — never a logical run itself.
- test case    = one TestResult row.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from .execution import (Execution, ExecutionState, Outcome, Project,
                        Suite, TestResult)

TERMINAL = {ExecutionState.COMPLETED, ExecutionState.FAILED,
            ExecutionState.CANCELED}
LOGICAL_ROLES = ("", "parent")          # unit children excluded
DISPATCH_ROLES = ("", "unit")           # parents own no process

# disclosed bounds — never silently truncate
MAX_COMPARISON_PROJECTS = 30
MAX_HISTORY_RUNS = 20
MAX_HISTORY_CASES = 40
MAX_BOX_SUITES = 12
MAX_ENV_SUITES = 12
MAX_ENV_ENVS = 8
MAX_PERIOD_DAYS = 365


def _aw(dt):
    """SQLite returns tz-naive datetimes — normalize to aware UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _day(dt) -> str:
    return _aw(dt).date().isoformat()


def _attempt(e: Execution) -> int:
    return int(e.snapshot().get("attempt") or 1)


def _retry_of(e: Execution) -> str:
    return e.snapshot().get("retry_of") or ""


def head_id(ex: Execution, by_id: dict) -> str:
    """Walk retry_of links to the chain head (cycle-guarded). When the
    head itself is outside the queried set, its id still keys the chain
    consistently so members group together."""
    seen, cur = set(), ex
    while True:
        rid = _retry_of(cur)
        if not rid:
            return cur.id
        if rid in seen:
            return cur.id
        if rid not in by_id:
            return rid
        seen.add(cur.id)
        cur = by_id[rid]


def resolve_logical_runs(executions: list) -> list:
    """Group executions into retry chains; return one entry per logical
    run: {head, members, final} where final = highest-attempt terminal
    member (None if the chain has no terminal member)."""
    by_id = {e.id: e for e in executions}
    chains: dict[str, list] = {}
    for e in executions:
        if e.role not in LOGICAL_ROLES:
            continue
        h = head_id(e, by_id)
        chains.setdefault(h, []).append(e)
    runs = []
    for members in chains.values():
        members.sort(key=_attempt)
        terminal = [m for m in members if m.state in TERMINAL]
        runs.append({
            "head": members[0],
            "members": members,
            "final": terminal[-1] if terminal else None,
            "retries": max(0, len(members) - 1),
        })
    return runs


def _visible_executions(user, days: int):
    """Executions in the user's visible projects (same scope as the
    Executions list — project_allowed, never post-filtered)."""
    from .execution import Project as _P
    ids = [p.id for p in _P.query.all() if user.project_allowed(p.id)]
    if not ids:
        return []
    return Execution.query.filter(Execution.project_id.in_(ids)).all()


# ---------------------------------------------------------------- main


def main_analytics(user, days: int) -> dict:
    """Group-A advanced analytics for the Main Dashboard."""
    days = max(1, min(int(days or 30), MAX_PERIOD_DAYS))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    executions = _visible_executions(user, days)
    projects = {p.id: p for p in Project.query.all()
                if user.project_allowed(p.id)}
    runs = resolve_logical_runs(executions)

    # --- 1. project outcome comparison (logical runs, final outcome)
    per_proj: dict[str, dict] = {}
    for r in runs:
        f = r["final"]
        if not f or not f.finished_at or _aw(f.finished_at) < since:
            continue
        proj = projects.get(f.project_id)
        if proj is None:
            continue
        row = per_proj.setdefault(
            proj.id, {"project": proj.name, "project_id": proj.id,
                      "passed": 0, "failed": 0, "incomplete": 0,
                      "none": 0})
        key = (f.outcome.value
               if f.outcome.value in row else "none")
        row[key] += 1
    # deterministic bound selection: most in-window runs, then name
    cmp_rows = sorted(
        per_proj.values(),
        key=lambda r: (-(r["passed"] + r["failed"] + r["incomplete"]
                         + r["none"]), r["project"]))
    comparison_truncated = len(cmp_rows) > MAX_COMPARISON_PROJECTS
    cmp_rows = cmp_rows[:MAX_COMPARISON_PROJECTS]

    # --- 2. first-attempt vs final pass rate (same cohort)
    by_day: dict[str, dict] = {}
    for r in runs:
        head = r["head"]
        if head.state not in TERMINAL or not head.finished_at:
            continue
        d = _day(head.finished_at)
        if _aw(head.finished_at) < since:
            continue
        row = by_day.setdefault(d, {"day": d, "total": 0,
                                    "first_passed": 0,
                                    "final_passed": 0, "retried": 0})
        row["total"] += 1
        if head.outcome == Outcome.PASSED:
            row["first_passed"] += 1
        if r["final"] and r["final"].outcome == Outcome.PASSED:
            row["final_passed"] += 1
        row["retried"] += 1 if r["retries"] else 0
    first_final = [by_day[k] for k in sorted(by_day)]

    # --- 3. queue wait / turnaround (dispatchable attempts)
    wait_d: dict[str, list] = {}
    turn_d: dict[str, list] = {}
    for e in executions:
        if e.role not in DISPATCH_ROLES or not e.created_at:
            continue
        if _aw(e.created_at) < since:
            continue
        d = _day(e.created_at)
        if e.started_at:
            w = (_aw(e.started_at) - _aw(e.created_at)).total_seconds()
            if w >= 0:
                wait_d.setdefault(d, []).append(w)
        if e.finished_at:
            t = (_aw(e.finished_at) - _aw(e.created_at)).total_seconds()
            if t >= 0:
                turn_d.setdefault(d, []).append(t)

    def _stats(dd):
        out = []
        for k in sorted(dd):
            v = sorted(dd[k])
            p95 = v[min(len(v) - 1,
                        int(0.95 * (len(v) - 1) + 0.5))]
            out.append({"day": k, "n": len(v),
                        "median": round(median(v), 1),
                        "p95": round(p95, 1)})
        return out

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "project_outcomes": cmp_rows,
        "project_outcomes_truncated": comparison_truncated,
        "first_final": first_final,
        "queue_wait": _stats(wait_d),
        "turnaround": _stats(turn_d),
    }


# ------------------------------------------------------------- project


def _project_executions(project_id: str, days: int, suite: str = "",
                        state: str = "", source_ref: str = "",
                        environment: str = ""):
    """Terminal-in-window executions for a project under the page's
    filters (mirrors project_dashboard.summary scoping)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = Execution.query.filter_by(project_id=project_id)
    if suite:
        q = q.filter_by(suite_id=suite)
    if state:
        q = q.filter_by(state=state)
    if source_ref:
        q = q.filter(Execution.source_ref.is_(None)
                     if source_ref == "__none__" else
                     Execution.source_ref == source_ref)
    if environment:
        q = q.filter(Execution.environment.is_(None)
                     if environment == "__none__" else
                     Execution.environment == environment)
    return [e for e in q.all()
            if e.state in TERMINAL and e.finished_at
            and _aw(e.finished_at) >= since]


def project_analytics(project_id: str, days: int, suite: str = "",
                      state: str = "", source_ref: str = "",
                      environment: str = "") -> dict:
    """Group-A advanced analytics for the Project Dashboard.

    Runs the same filters the page applies so the advanced section is
    consistent with the existing charts."""
    days = max(1, min(int(days or 30), MAX_PERIOD_DAYS))
    exes = _project_executions(project_id, days, suite, state,
                               source_ref, environment)
    exes.sort(key=lambda e: e.finished_at)
    suite_names = {s.id: s.name for s in Suite.query.all()}

    # --- 1. test-result history heatmap (case × run)
    runs_cols = exes[-MAX_HISTORY_RUNS:]
    case_ids: list[str] = []
    cells: dict[tuple, dict] = {}
    for e in runs_cols:
        sname = suite_names.get(e.suite_id, "(no suite)")
        for r in e.results:
            ident = (r.case_ref or r.case_name)
            if not suite:
                ident = f"{sname}:{ident}"
            if ident not in case_ids:
                case_ids.append(ident)
            cells[(ident, e.id)] = {
                "status": r.status.value,
                "duration": round(r.duration_s, 2),
                "case": r.case_name,
            }
    cases_truncated = len(case_ids) > MAX_HISTORY_CASES
    case_ids = case_ids[-MAX_HISTORY_CASES:]
    cells = {k: v for k, v in cells.items() if k[0] in set(case_ids)}
    run_meta = [{"id": e.id, "label": _day(e.finished_at) + " · "
                 + e.id[:8], "attempt": _attempt(e),
                "sha": (e.source_sha or "")[:8],
                "env": e.environment or "(unset)",
                "finished": _aw(e.finished_at).isoformat()}
           for e in runs_cols]
    history = {"cases": case_ids, "runs": run_meta,
               "cells": {f"{k[0]}|{k[1]}": v for k, v in cells.items()},
               "cases_truncated": cases_truncated,
               "runs_truncated": len(exes) > MAX_HISTORY_RUNS}

    # --- 2. suite-duration distribution (logical runs)
    runs = resolve_logical_runs(exes)
    dur_by_suite: dict[str, dict] = {}
    for r in runs:
        f = r["final"]
        if not f or not f.started_at or not f.finished_at:
            continue
        secs = (_aw(f.finished_at) - _aw(f.started_at)).total_seconds()
        if secs < 0:
            continue
        name = suite_names.get(f.suite_id, "(no suite)")
        dur_by_suite.setdefault(
            name, {"suite": name, "durations": [],
                   "executions": [], "points": []})
        dur_by_suite[name]["durations"].append(round(secs, 1))
        dur_by_suite[name]["executions"].append(f.id)
        dur_by_suite[name]["points"].append(
            {"duration": round(secs, 1), "execution_id": f.id})
    # deterministic bound selection: most samples, then suite name
    box_rows = sorted(
        dur_by_suite.values(),
        key=lambda r: (-len(r["durations"]), r["suite"]))
    box_truncated = len(box_rows) > MAX_BOX_SUITES
    box_rows = box_rows[:MAX_BOX_SUITES]

    # --- 3. environment comparison (suite × environment)
    env_matrix: dict[tuple, dict] = {}
    for r in runs:
        f = r["final"]
        if not f:
            continue
        sname = suite_names.get(f.suite_id, "(no suite)")
        env = f.environment or "(unset)"
        cell = env_matrix.setdefault(
            (sname, env),
            {"suite": sname, "env": env, "suite_id": f.suite_id or "",
             "project_id": f.project_id,
             "runs": 0, "runs_passed": 0,
             "case_passed": 0, "case_total": 0, "durations": [],
             "executions": []})
        cell["runs"] += 1
        cell["executions"].append(f.id)
        if f.outcome == Outcome.PASSED:
            cell["runs_passed"] += 1
        for tr in f.results:
            if tr.status.value in ("passed", "failed", "error"):
                cell["case_total"] += 1
                cell["case_passed"] += tr.status.value == "passed"
        if f.started_at and f.finished_at:
            secs = (_aw(f.finished_at)
                    - _aw(f.started_at)).total_seconds()
            if secs >= 0:
                cell["durations"].append(secs)
    suites_sorted = sorted({k[0] for k in env_matrix})
    envs_sorted = sorted({k[1] for k in env_matrix})
    env_trunc_s = len(suites_sorted) > MAX_ENV_SUITES
    env_trunc_e = len(envs_sorted) > MAX_ENV_ENVS
    suites_sorted = suites_sorted[:MAX_ENV_SUITES]
    envs_sorted = envs_sorted[:MAX_ENV_ENVS]
    env_cells = []
    for c in env_matrix.values():
        if c["suite"] not in suites_sorted or c["env"] not in envs_sorted:
            continue
        durs = sorted(c["durations"])
        env_cells.append({
            "suite": c["suite"], "env": c["env"],
            "suite_id": c["suite_id"], "project_id": c["project_id"],
            "runs": c["runs"], "runs_passed": c["runs_passed"],
            "run_pass_rate": (round(100 * c["runs_passed"] / c["runs"], 1)
                              if c["runs"] else None),
            "case_pass_rate": (round(100 * c["case_passed"]
                                     / c["case_total"], 1)
                               if c["case_total"] else None),
            "case_total": c["case_total"],
            "median_duration": (round(median(durs), 1)
                                if durs else None),
            "executions": c["executions"],
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "history": history,
        "suite_durations": box_rows,
        "suite_durations_truncated": box_truncated,
        "env_cells": env_cells,
        "env_suites": suites_sorted,
        "env_envs": envs_sorted,
        "env_truncated_suites": env_trunc_s,
        "env_truncated_envs": env_trunc_e,
    }
