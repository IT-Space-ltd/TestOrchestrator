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
MAX_REGRESSION_SUITES = 12
MAX_REGRESSION_EXECS = 10     # contributing-execution links per side
MIN_REGRESSION_SAMPLES = 3    # below this a regression row is "insufficient"
EVIDENCE_STALE_DAYS = 7       # documented freshness threshold
MAX_FRESHNESS_SUITES = 12
MAX_FRESHNESS_ENVS = 8


def _first_final_rows(runs: list, since) -> list:
    """First-attempt vs final pass-rate cohort (Group A/B shared).

    One row per first-attempt finish day: total logical runs, first
    passed, final resolved passed, retried. Head must be terminal."""
    by_day: dict[str, dict] = {}
    for r in runs:
        head = r["head"]
        if head.state not in TERMINAL or not head.finished_at:
            # Excluded: first attempt never terminated — no finish day
            # exists, so attribute the exclusion to the submission day
            # (disclosed in the counting doc).
            if head.created_at and _aw(head.created_at) >= since:
                d = _day(head.created_at)
                by_day.setdefault(
                    d, {"day": d, "total": 0, "first_passed": 0,
                        "final_passed": 0, "retried": 0,
                        "excluded": 0})["excluded"] += 1
            continue
        if _aw(head.finished_at) < since:
            continue
        row = by_day.setdefault(_day(head.finished_at),
                                {"day": _day(head.finished_at),
                                 "total": 0, "first_passed": 0,
                                 "final_passed": 0, "retried": 0,
                                 "excluded": 0})
        row["total"] += 1
        if head.outcome == Outcome.PASSED:
            row["first_passed"] += 1
        if r["final"] and r["final"].outcome == Outcome.PASSED:
            row["final_passed"] += 1
        row["retried"] += 1 if r["retries"] else 0
    return [by_day[k] for k in sorted(by_day)]


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
    first_final = _first_final_rows(runs, since)

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

    # --- 4. execution activity (logical runs once — retries and unit
    # shards never inflate the count). Submitted = chain-head
    # created_at; started = earliest member started_at (never-started
    # runs excluded from started mode). UTC buckets.
    act_sub, act_start = [], []
    for r in runs:
        head = r["head"]
        if head.created_at and _aw(head.created_at) >= since:
            t = _aw(head.created_at)
            act_sub.append({"dow": t.weekday(), "hour": t.hour,
                            "exec_id": (r["final"] or head).id})
        first_start = min((_aw(m.started_at) for m in r["members"]
                           if m.started_at), default=None)
        if first_start and first_start >= since:
            act_start.append({"dow": first_start.weekday(),
                              "hour": first_start.hour,
                              "exec_id": (r["final"] or head).id})
    def _matrix(rows):
        cells = {}
        for x in rows:
            cells[(x["dow"], x["hour"])] = \
                cells.get((x["dow"], x["hour"]), 0) + 1
        return [{"dow": d, "hour": h, "count": n}
                for (d, h), n in sorted(cells.items())]
    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "project_outcomes": cmp_rows,
        "project_outcomes_truncated": comparison_truncated,
        "first_final": first_final,
        "queue_wait": _stats(wait_d),
        "turnaround": _stats(turn_d),
        "activity_submitted": _matrix(act_sub),
        "activity_started": _matrix(act_start),
    }


# ------------------------------------------------------------- project


def _project_executions_range(project_id: str, since, until,
                              suite: str = "", state: str = "",
                              source_ref: str = "",
                              environment: str = ""):
    """Terminal executions finished in [since, until) for a project
    under the page's filters. `since=None`/`until=None` = unbounded
    on that side."""
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
    out = []
    for e in q.all():
        if e.state not in TERMINAL or not e.finished_at:
            continue
        f = _aw(e.finished_at)
        if since is not None and f < since:
            continue
        if until is not None and f >= until:
            continue
        out.append(e)
    return out


def _project_executions(project_id: str, days: int, suite: str = "",
                        state: str = "", source_ref: str = "",
                        environment: str = ""):
    """Terminal-in-window executions for a project under the page's
    filters (mirrors project_dashboard.summary scoping)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return _project_executions_range(project_id, since, None,
                                     suite, state, source_ref,
                                     environment)


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
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # --- 4. first-attempt vs final pass rate — same Group A cohort
    # policy (grouped by first-attempt finish day), project filters
    # applied. No drill-through: accepted limitation.
    proj_first_final = _first_final_rows(runs, since)

    # --- 5. suite-duration regression — median resolved-attempt
    # wall-clock, current period vs the previous equal-length period,
    # identical filters on both sides. Chains are resolved ONCE over
    # the combined window, then assigned to current/baseline by the
    # final resolved attempt's finish — a head finishing in baseline
    # whose retry finishes in current must not count as a logical run
    # in both windows.
    union_exes = _project_executions_range(
        project_id, since - timedelta(days=days), None,
        suite, state, source_ref, environment)
    union_runs = resolve_logical_runs(union_exes)
    base_lo = since - timedelta(days=days)
    base_runs = [r for r in union_runs
                 if r["final"]
                 and base_lo <= _aw(r["final"].finished_at) < since]
    cur_runs = [r for r in union_runs
                if r["final"]
                and _aw(r["final"].finished_at) >= since]

    def _wall_secs(rr):
        f = rr["final"]
        if not f or not f.started_at or not f.finished_at:
            return None
        s = (_aw(f.finished_at) - _aw(f.started_at)).total_seconds()
        return s if s >= 0 else None

    def _by_suite(rruns):
        out: dict[str, dict] = {}
        for rr in rruns:
            s = _wall_secs(rr)
            if s is None:
                continue
            f = rr["final"]
            name = suite_names.get(f.suite_id, "(no suite)")
            row = out.setdefault(name, {"secs": [], "execs": []})
            row["secs"].append(s)
            row["execs"].append(f.id)
        return out

    cur_by, base_by = _by_suite(cur_runs), _by_suite(base_runs)
    reg_rows = []
    for name in sorted(set(cur_by) | set(base_by)):
        cur, base = cur_by.get(name), base_by.get(name)
        cn = len(cur["secs"]) if cur else 0
        bn = len(base["secs"]) if base else 0
        cmed = median(cur["secs"]) if cur else None
        bmed = median(base["secs"]) if base else None
        delta_s = (round(cmed - bmed, 1)
                   if cmed is not None and bmed is not None else None)
        delta_pct = (round(100 * (cmed - bmed) / bmed, 1)
                     if delta_s is not None and bmed else None)
        reg_rows.append({
            "suite": name,
            "current_median_s": (round(cmed, 1)
                                 if cmed is not None else None),
            "baseline_median_s": (round(bmed, 1)
                                  if bmed is not None else None),
            "current_n": cn, "baseline_n": bn,
            "delta_s": delta_s, "delta_pct": delta_pct,
            "insufficient": cn < MIN_REGRESSION_SAMPLES
                            or bn < MIN_REGRESSION_SAMPLES,
            "current_executions": (cur["execs"][:MAX_REGRESSION_EXECS]
                                   if cur else []),
            "baseline_executions": (base["execs"][:MAX_REGRESSION_EXECS]
                                    if base else []),
        })
    reg_truncated = len(reg_rows) > MAX_REGRESSION_SUITES
    # ranked by duration increase; N/A rows last, insufficient flagged
    reg_rows.sort(key=lambda r: (
        r["delta_s"] is None, -(r["delta_s"] or 0), r["suite"]))
    reg_rows = reg_rows[:MAX_REGRESSION_SUITES]

    # --- 6. evidence freshness — latest usable result per suite×env
    # combo in scope. "Usable result" = a terminal attempt of a
    # logical run that produced >=1 test result (a complete failing
    # result is still evidence). Looked up across ALL history — the
    # period filter must not make older evidence look never-observed;
    # `beyond_window` discloses when that happened.
    all_exes = _project_executions_range(
        project_id, None, None, suite, "", source_ref, environment)
    fr_combos: dict[tuple, dict] = {}
    for rr in resolve_logical_runs(all_exes):
        usable = [m for m in rr["members"]
                  if m.state in TERMINAL and m.finished_at
                  and len(m.results) > 0]
        if not usable:
            continue
        u = usable[-1]          # latest attempt that produced results
        sname = suite_names.get(u.suite_id, "(no suite)")
        env = u.environment or "(unset)"
        key = (sname, env)
        cur = fr_combos.get(key)
        if cur is None or _aw(u.finished_at) > cur["at"]:
            fr_combos[key] = {"at": _aw(u.finished_at),
                              "exec": u}
    # combo scope = suites existing in config × environments ever used
    fr_suites = sorted({s.name
                        for s in Suite.query.filter_by(
                            project_id=project_id).all()
                        if not suite or s.id == suite})
    if any(e.suite_id is None for e in all_exes) and not suite:
        fr_suites.append("(no suite)")
    fr_envs = sorted({e.environment or "(unset)" for e in all_exes})
    fr_trunc_s = len(fr_suites) > MAX_FRESHNESS_SUITES
    fr_trunc_e = len(fr_envs) > MAX_FRESHNESS_ENVS
    fr_suites = fr_suites[:MAX_FRESHNESS_SUITES]
    fr_envs = fr_envs[:MAX_FRESHNESS_ENVS]
    fresh_rows = []
    for sn in fr_suites:
        for ev in fr_envs:
            c = fr_combos.get((sn, ev))
            if c is None:
                # never observed — valid only because suite (config)
                # and env (history) are both known to exist
                fresh_rows.append({"suite": sn, "env": ev,
                                   "state": "never",
                                   "last_execution_id": None,
                                   "last_finished_at": None,
                                   "outcome": None, "age_s": None,
                                   "beyond_window": False})
                continue
            age = (now - c["at"]).total_seconds()
            fresh_rows.append({
                "suite": sn, "env": ev,
                "state": ("fresh" if age
                          <= EVIDENCE_STALE_DAYS * 86400 else "stale"),
                "last_execution_id": c["exec"].id,
                "last_finished_at": c["at"].isoformat(),
                "outcome": c["exec"].outcome.value,
                "age_s": round(age),
                "beyond_window": c["at"] < since,
            })
    fresh_rows.sort(key=lambda r: (r["age_s"] is None,
                                   -(r["age_s"] or 0), r["suite"]))

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "history": history,
        "suite_durations": box_rows,
        "suite_durations_truncated": box_truncated,
        "env_cells": env_cells,
        "env_suites": suites_sorted,
        "env_envs": envs_sorted,
        "env_truncated_suites": env_trunc_s,
        "env_truncated_envs": env_trunc_e,
        "first_final": proj_first_final,
        "duration_regression": reg_rows,
        "duration_regression_truncated": reg_truncated,
        "regression_baseline": {
            "from": (since - timedelta(days=days)).date().isoformat(),
            "to": since.date().isoformat(),
            "current_from": since.date().isoformat(),
            "current_to": now.date().isoformat(),
        },
        "evidence_freshness": fresh_rows,
        "freshness_suites": fr_suites,
        "freshness_envs": fr_envs,
        "freshness_threshold_days": EVIDENCE_STALE_DAYS,
        "freshness_truncated_suites": fr_trunc_s,
        "freshness_truncated_envs": fr_trunc_e,
    }
