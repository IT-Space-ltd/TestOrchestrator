"""Portal blueprint: projects, bindings, suites, plans, executions (§10).

Role model (§16), enforced server-side:
  Admin + Test Manager — definitions, bindings, schedules, execution
  Tester               — launch + cancel own executions, view reports
  PO                   — read-only results/evidence, no mutation/execution
Project scope is checked on every endpoint including artifact downloads
and log streams.
"""

import hashlib
import io
import json
import re
import mimetypes
import threading
from datetime import datetime, timedelta
from pathlib import Path

import os
from flask import (abort, after_this_request, current_app, flash,
                   redirect, render_template, request, Response,
                   send_file, session, url_for)
from flask_login import current_user, login_required

from .. import dispatch, gitsync
from ..capture import CAPTURE_CATEGORIES
from ..execution import (ArtifactStore, DiscoveredItem, Execution,
                         ExecutionState, FrameworkProject,
                         ReleaseItem, RuntimeConnection,
                       GitBinding, OutboxEvent,
                         Outcome, Project, Release,
                         Schedule, Suite, SuiteEntry, utcnow)
from ..extensions import db
from ..models import Role, User, record_audit
from ..security import role_required
from . import portal_bp
from .. import results as results_mod
from ..discovery import FRAMEWORK_CHOICES, discover
from .forms import (BindingForm, FrameworkProjectForm, PlainForm,
                    ProjectForm, ScheduleForm, SuiteForm,
                    reject_url_password)

EDIT_ROLES = (Role.ADMIN, Role.TEST_MANAGER)
RUN_ROLES = (Role.ADMIN, Role.TEST_MANAGER, Role.TESTER)


def _dash_trend(qs, days: int = 14):
    """Daily passed/failed counts — bar-chart data like the main
    dashboard's chart_outcomes. Aggregated in SQL over the window —
    never a full-history scan into Python."""
    from collections import Counter
    from datetime import date, timedelta
    from sqlalchemy import func
    cutoff = utcnow() - timedelta(days=days)
    rows = (qs.filter(Execution.created_at >= cutoff)
              .with_entities(func.date(Execution.created_at),
                             Execution.outcome,
                             func.count(Execution.id))
              .group_by(func.date(Execution.created_at),
                        Execution.outcome).all())
    cp, cf = Counter(), Counter()
    for day, outcome, n in rows:
        if outcome == Outcome.PASSED:
            cp[day] += n
        elif outcome in (Outcome.FAILED, Outcome.INCOMPLETE):
            cf[day] += n
    out = []
    for i in range(days):
        day = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        out.append({"day": day, "passed": cp.get(day, 0),
                    "failed": cf.get(day, 0)})
    return out


def _project_or_404(project_id) -> Project:
    project = db.session.get(Project, project_id)
    if project is None:
        abort(404)
    if not current_user.project_allowed(project_id):
        abort(403)
    return project


def _execution_or_404(execution_id) -> Execution:
    ex = db.session.get(Execution, execution_id)
    if ex is None:
        abort(404)
    if not current_user.project_allowed(ex.project_id):
        abort(403)
    return ex


def _suite_hash(suite: Suite) -> str:
    content = json.dumps([
        {"case_ref": e.case_ref, "order": e.order, "enabled": e.enabled,
         "config": e.config_json}
        for e in suite.entries
    ], sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


# ---------- projects ----------

@portal_bp.route("/projects")
@login_required
def projects():
    from ..dashboard import ACTIVE_STATES, TERMINAL_STATES
    from ..execution import Execution
    q = request.args.get("q", "").strip().lower()
    sort = request.args.get("sort", "name")
    all_projects = [p for p in Project.query.all()
                    if current_user.project_allowed(p.id)]
    if q:
        all_projects = [p for p in all_projects
                        if q in p.name.lower()
                        or q in (p.description or "").lower()]
    if all_projects:
        totals = dict(db.session.query(
            Execution.project_id, db.func.count(Execution.id))
            .group_by(Execution.project_id).all())
        actives = dict(db.session.query(
            Execution.project_id, db.func.count(Execution.id))
            .filter(Execution.state.in_(ACTIVE_STATES))
            .group_by(Execution.project_id).all())
        mx = (db.session.query(
                Execution.project_id,
                db.func.max(Execution.finished_at).label("mx"))
              .filter(Execution.state.in_(TERMINAL_STATES),
                      Execution.finished_at.isnot(None))
              .group_by(Execution.project_id).subquery())
        latest_map = {
            e.project_id: e
            for e in Execution.query.join(
                mx, db.and_(Execution.project_id == mx.c.project_id,
                            Execution.finished_at == mx.c.mx)).all()}
    else:
        totals, actives, latest_map = {}, {}, {}
    cards = []
    for p in all_projects:
        cards.append({
            "project": p,
            "latest": latest_map.get(p.id),
            "active": actives.get(p.id, 0),
            "total": totals.get(p.id, 0),
        })
    if sort == "recent":
        cards.sort(key=lambda c: (c["latest"].finished_at
                                  if c["latest"] else ""),
                   reverse=True)
    else:
        cards.sort(key=lambda c: c["project"].name.lower())
    return render_template("portal/projects.html", cards=cards,
                           form=ProjectForm(), q=q, sort=sort)


@portal_bp.route("/projects", methods=["POST"])
@role_required(*EDIT_ROLES)
def create_project():
    form = ProjectForm()
    if form.validate_on_submit():
        project = Project(name=form.name.data.strip(),
                          description=form.description.data or "")
        db.session.add(project)
        db.session.commit()
        record_audit(current_user.username, "project.created", project.id)
    return redirect(url_for("portal.projects"))


@portal_bp.route("/projects/<project_id>/edit", methods=["POST"])
@role_required(*EDIT_ROLES)
def edit_project(project_id):
    project = _project_or_404(project_id)
    form = ProjectForm()
    if form.validate_on_submit():
        project.name = form.name.data.strip()
        project.description = form.description.data or ""
        db.session.commit()
        record_audit(current_user.username, "project.edited", project.id)
    return redirect(url_for("portal.projects"))


@portal_bp.route("/projects/<project_id>")
@login_required
def project_detail(project_id):
    project = _project_or_404(project_id)
    _bind_aw = session.pop("_bind_aw", None)
    _bind_rw = session.pop("_bind_rw", None)
    _bind_err = session.pop("_bind_err", None)
    if _bind_err:
        flash(f"Binding not saved — {_bind_err}", "error")
    can_edit = current_user.role.value in ("admin", "test_manager")
    can_run = current_user.role.value in ("admin", "test_manager", "tester")
    suite_form = SuiteForm()
    # Case choices mirror create_suite's selection: the project's first
    # binding's synced worktree (read-only listing, never executed).
    first_binding = GitBinding.query.filter_by(project_id=project.id).first()
    cases = gitsync.list_test_cases(first_binding) if first_binding else []
    suite_form.case_refs.choices = [(c, c) for c in cases]
    schedule_form = ScheduleForm()
    # repository definitions first (binding · kind · path), then
    # legacy App suites explicitly labelled.
    repo_defs = DiscoveredItem.query.join(GitBinding).filter(
        GitBinding.project_id == project.id,
        DiscoveredItem.kind.in_(("suite", "collection"))).all()
    bind_names = {b.id: b.name for b in GitBinding.query.filter_by(
        project_id=project.id)}

    # ---- Test tab: read-only Git-discovered cases + suites/collections
    test_subtab = request.args.get("subtab") or "case"
    test_repo = request.args.get("repo") or ""
    test_q = (request.args.get("q") or "").strip().lower()
    bindings_nav = GitBinding.query.filter_by(
        project_id=project.id).order_by(GitBinding.name).all()
    case_defs = DiscoveredItem.query.join(GitBinding).filter(
        GitBinding.project_id == project.id,
        DiscoveredItem.kind == "case").all()
    # per-case execution stats from parsed results (documented mapping;
    # unavailable metadata left as None -> rendered as —)
    from ..execution import TestResult, Execution, CaseStatus
    stats = {}
    res_rows = (db.session.query(TestResult)
                .join(Execution, TestResult.execution_id == Execution.id)
                .filter(Execution.project_id == project.id).all())
    for r in res_rows:
        s = stats.setdefault(r.case_name, {"n": set(), "dur": 0.0,
                                           "fail": 0, "last": None})
        s["n"].add(r.execution_id)
        s["dur"] += (r.duration_s or 0.0)
        s["fail"] += int(r.status != CaseStatus.PASSED)
        fin = getattr(r.execution, "finished_at", None)
        if fin and (s["last"] is None or fin > s["last"]):
            s["last"] = fin
    def _cstats(name):
        s = stats.get(name)
        if not s:
            return None
        n = len(s["n"])
        return {"execs": n,
                "avg_dur": round(s["dur"] / n, 1) if n else None,
                "flakiness": round(100.0 * s["fail"] /
                                   (s["fail"] + max(0, n - s["fail"]))
                                   if n else 0.0, 1),
                "last": s["last"]}
    def _in_repo(i):
        return (not test_repo) or i.binding_id == test_repo
    def _in_q(i):
        return (not test_q) or test_q in (i.name or "").lower() \
            or test_q in (i.path or "").lower()
    test_cases = [{"item": i, "stats": _cstats(i.name),
                   "repo": bind_names.get(i.binding_id, "?")}
                  for i in case_defs if _in_repo(i) and _in_q(i)]
    test_suites = [i for i in repo_defs
                   if i.kind == "suite" and _in_repo(i) and _in_q(i)]
    test_colls = [i for i in repo_defs
                  if i.kind == "collection" and _in_repo(i) and _in_q(i)]
    # app-side suite last-execution + outcome summary (P/F/E/I/S)
    from ..execution import Execution as _Ex
    suite_exec = {}
    for s in project.suites:
        ex = (_Ex.query.filter_by(project_id=project.id, suite_id=s.id)
              .order_by(_Ex.finished_at.desc()).first())
        cnt = {"passed": 0, "failed": 0, "error": 0,
               "incomplete": 0, "skipped": 0}
        if ex:
            for r in ex.results:
                k = r.status.value if hasattr(r.status, "value") \
                    else str(r.status)
                cnt[k] = cnt.get(k, 0) + 1
        suite_exec[s.id] = {"ex": ex, "cnt": cnt}
    repo_targets = [
        {"v": f"repo:{d.id}",
         "l": f"{d.name or d.path.split('/')[-1].rsplit('.', 1)[0]} "
             f"({d.kind}) · {bind_names.get(d.binding_id, '?')} · "
             f"{d.path}"} for d in repo_defs]
    schedule_form.target_id.choices = (
        [(f"repo:{d.id}", f"{bind_names.get(d.binding_id, '?')} · "
          f"{d.kind} · {d.path}") for d in repo_defs] +
        [(f"app:{s.id}", f"app-side suite · {s.name}")
         for s in project.suites])
    from ..execution import Runner, RuntimeConnection
    _runners = [x for x in Runner.query.filter_by(enabled=True).all()
                if not x.draining]
    schedule_form.runner_id.choices = [
        ("", "Auto — first eligible")] + [
        (x.id, f"{x.name} ({x.os_arch or 'unknown os'})")
        for x in _runners]
    schedule_form.runtime_id.choices = [
        ("", "Auto — compatible on runner")] + [
        (x.id, f"{x.name} ({x.detected_version or 'unknown ver'})")
        for x in RuntimeConnection.query.filter_by(enabled=True).all()]
    _qs = Execution.query.filter_by(project_id=project.id)
    _since = request.args.get("since", "")
    if _since:
        from datetime import datetime as _dt, timezone as _tz
        _qs = _qs.filter(Execution.created_at >= _dt.fromisoformat(
            _since).replace(tzinfo=_tz.utc))
    _n = _qs.count()
    _done = _qs.filter(Execution.finished_at.isnot(None)).all()
    _pass = sum(1 for e in _done if e.outcome.value == "passed")
    _rate = round(100 * _pass / len(_done)) if _done else 0
    dash = {"count": _n, "passed": _pass,
            "failed": sum(1 for e in _done
                          if e.outcome.value == "failed"),
            "running": _qs.filter(Execution.started_at.isnot(None),
                                  Execution.finished_at.is_(None)).count(),
            "queued": _qs.filter(Execution.started_at.is_(None)).count(),
            "rate": _rate, "since": _since,
            "trend": _dash_trend(_qs),
            "pub_pending": OutboxEvent.query.filter_by(
                status="pending").count(),
            "pub_failed": OutboxEvent.query.filter_by(
                status="failed").count(),
            "recent": _qs.order_by(
                Execution.created_at.desc()).limit(8).all()}
    # per-release testing progress: latest outcome per scoped target
    # (path+kind+binding+config), not all history.
    progress = {}
    rel_summary = {}
    for rel in project.releases:
        items = ReleaseItem.query.filter_by(
            release_id=rel.id).all()
        counts = {"passed": 0, "failed": 0, "running": 0,
                  "queued": 0, "cancelled": 0, "unexecuted": 0,
                  "unavailable": 0}
        latest = {}
        _runs = list(Execution.query.filter_by(release_id=rel.id)
                   .order_by(Execution.created_at.desc()))
        for e in _runs:
            st = e.snapshot().get("source_target", {})
            key = (st.get("path", ""), st.get("kind", ""),
                   st.get("binding_id", ""))
            if key not in latest:
                latest[key] = e
        for it in items:
            src = (db.session.get(DiscoveredItem, it.source_item_id)
                   if it.source_item_id else None)
            key = (it.path, it.kind,
                   src.binding_id if src else "")
            if src is None and it.source_item_id:
                counts["unavailable"] += 1
                continue
            e = latest.get(key) or next(
                (e for (p, _k, _b), e in latest.items()
                 if p == it.path), None)
            if e is None:
                counts["unexecuted"] += 1
            elif e.finished_at:
                counts["passed" if e.outcome.value == "passed"
                        else "failed"] += 1
            elif e.started_at:
                counts["running"] += 1
            else:
                counts["queued"] += 1
        progress[rel.id] = counts
        # TestOps-style readiness: empty (no cases), ready (all passed,
        # none pending/failed), not_ready (failures or in-flight).
        tot = sum(counts.values())
        pending = (counts.get("failed", 0) + counts.get("running", 0)
                   + counts.get("queued", 0))
        dur = sum((e.finished_at - e.started_at).total_seconds()
                  for e in _runs if e.started_at and e.finished_at)
        rel_summary[rel.id] = {
            "category": ("empty" if tot == 0 else
                         "ready" if counts.get("passed") and not pending
                         else "not_ready"),
            "test_cases": tot, "test_runs": len(_runs),
            "duration_s": int(dur),
            "failed": counts.get("failed", 0), "counts": counts,
        }
    # Dashboard release overview: active releases (draft+in_progress),
    # dated timeline + undated list — "current state", not
    # date-filtered.
    active = [rel for rel in project.releases
              if rel.status in ("draft", "in_progress")]
    dated_active = [rel for rel in active if rel.start_date]
    undated_active = [rel for rel in active if not rel.start_date]
    from datetime import timezone as _tz, datetime as _dt
    _today = _dt.now(_tz.utc).date()
    overdue_active = [rel for rel in active
                      if rel.end_date and rel.end_date < _today]
    tlo = (min((rel.start_date for rel in dated_active))
           if dated_active else None)
    thi = (max((rel.end_date or _today for rel in dated_active))
           if dated_active else None)
    return render_template(
        "portal/project_detail.html", project=project,
        rel_progress=progress, rel_summary=rel_summary,
        repo_targets=repo_targets,
        sched_targets=[],
        active_releases=active, dated_active=dated_active,
        undated_active=undated_active,
        overdue_active=overdue_active,
        tlo=tlo, thi=thi, dash=dash,
        binding_form=BindingForm(),
        bind_aw=_bind_aw, bind_rw=_bind_rw,
        can_author=GitBinding.query.filter_by(
            project_id=project.id, authoring_writable=True).count() > 0,
        repo_cases=cases,
        repo_suites=[i.path for i in
                     DiscoveredItem.query.filter_by(
                         binding_id=first_binding.id if first_binding else '',
                         kind='suite').all()],
        suite_form=suite_form, plain_form=PlainForm(),
        schedule_form=schedule_form, can_edit=can_edit, can_run=can_run,
        artifact_stores=ArtifactStore.query.filter_by(
            project_id=project.id).order_by(ArtifactStore.name).all(),
        capture_categories=CAPTURE_CATEGORIES,
        capture_policy=project.capture_policy(),
        retention_eff=_retention_context(project),
        users=(User.query.order_by(User.username).all()
               if current_user.role.value == "admin" else []),
        executions=Execution.query.filter_by(project_id=project_id)
        .order_by(Execution.created_at.desc()).limit(25).all(),
        discovered=_discovery_summary(project_id),
        plan_summaries={p.id: results_mod.plan_summary(p)
                        for p in project.plans},
        state_labels=results_mod.STATE_LABELS,
        test_subtab=test_subtab, test_repo=test_repo, test_q=test_q,
        bindings_nav=bindings_nav, test_cases=test_cases,
        test_suites=test_suites, test_colls=test_colls,
        suite_exec=suite_exec,
        # Analytics tab content is only computed when that tab is
        # requested — keeps ordinary project visits light.
        **(_project_dashboard_ctx(project)
           if request.args.get("tab") == "analytics" else {}),
    )


# ---------- git bindings ----------

@portal_bp.route("/projects/<project_id>/access")
@role_required(Role.ADMIN)
def project_access(project_id):
    """Project → Settings → Access: this project's assigned users
    with their roles — the inverse view of Users → Project access.
    Both edit the SAME membership list (User.allowed_projects);
    Administrator rows show 'through role', not a checkbox."""
    project = _project_or_404(project_id)
    users = User.query.order_by(User.username).all()
    return render_template(
        "portal/project_access.html", project=project, users=users,
        plain_form=PlainForm())


@portal_bp.route("/projects/<project_id>/access", methods=["POST"])
@role_required(Role.ADMIN)
def save_project_access(project_id):
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    wanted = {int(x) for x in request.form.getlist("user_ids")
              if x.isdigit()}
    changes = []
    for u in User.query.filter(User.role != Role.ADMIN).all():
        before = set(u.assigned_project_ids())
        after = set(before)
        if u.id in wanted:
            after.add(project.id)
        else:
            after.discard(project.id)
        if after != before:
            u.set_assigned_projects(after)
            changes.append(
                f"{u.username}: {sorted(before)} -> {sorted(after)}")
    if changes:
        db.session.commit()
        for c in changes:
            record_audit(current_user.username,
                         "user.project_access",
                         f"{project.name}: {c}")
        flash(f"Access updated ({len(changes)} change(s)).", "info")
    else:
        flash("No changes.", "info")
    return redirect(url_for("portal.project_detail",
                            project_id=project.id, tab="access"))


def _project_dashboard_ctx(project):
    """Reporting+advanced analytics template context — shared by the
    standalone dashboard page and the project-detail Analytics tab."""
    from ..charts import (outcome_trend, pass_rate_trend,
                          duration_trend, failure_breakdown)
    from ..project_dashboard import summary
    days = request.args.get("period", 30, type=int) or 30
    suite = request.args.get("suite", "")
    state = request.args.get("state", "")
    source_ref = request.args.get("source_ref", "")
    environment = request.args.get("environment", "")
    from .. import usertz as _utz
    data = summary(project.id, days=days, suite=suite, state=state,
                   source_ref=source_ref, environment=environment,
                   tz=_utz.user_zone(current_user))
    # filter option sets for the controls (authorized project scope)
    refs = sorted({x for (x,) in db.session.query(Execution.source_ref)
                   .filter_by(project_id=project.id)
                   if x})
    envs = sorted({x for (x,) in db.session.query(Execution.environment)
                   .filter_by(project_id=project.id)
                   if x})
    return dict(
        data=data, days=days,
        fig_outcomes=outcome_trend(data["outcome_trend"]),
        fig_passrate=pass_rate_trend(data["pass_rate"]),
        fig_duration=duration_trend(data["durations"]),
        fig_failures=failure_breakdown(data["failures"]),
        suites=Suite.query.filter_by(project_id=project.id).all(),
        sel_suite=suite, sel_state=state,
        source_refs=refs, environments=envs,
        sel_source_ref=source_ref, sel_environment=environment,
        adv=_proj_adv(project.id, request.args))


@portal_bp.route("/projects/<project_id>/dashboard")
@login_required
def project_dashboard(project_id):
    """Project reporting dashboard — trends, failures, drill-down.
    Aggregation in project_dashboard.py; figures in charts.py.
    The same content renders in the project-detail Analytics tab."""
    project = _project_or_404(project_id)
    return render_template(
        "portal/project_dashboard.html",
        project=project, **_project_dashboard_ctx(project))


def _proj_adv(project_id: str, args):
    """Advanced-analytics payload for the project dashboard (docs/
    analytics-counting.md). Same filters as the page; JSON/CSV served
    by /projects/<id>/analytics."""
    from .. import analytics
    from ..charts import (env_comparison, result_history,
                          suite_duration_box, first_final_trend,
                          duration_regression_bars, freshness_heatmap)
    days = args.get("period", 30, type=int) or 30
    env_metric = args.get("env_metric") or "case_pass_rate"
    if env_metric not in ("case_pass_rate", "run_pass_rate",
                          "median_duration"):
        env_metric = "case_pass_rate"
    reg_mode = args.get("reg_mode") or "seconds"
    if reg_mode not in ("seconds", "percent"):
        reg_mode = "seconds"
    from .. import usertz as _utz
    tz = _utz.user_zone(current_user)
    data = analytics.project_analytics(
        project_id, days,
        suite=args.get("suite", ""),
        state=args.get("state", ""),
        source_ref=args.get("source_ref", ""),
        environment=args.get("environment", ""), tz=tz)
    return {
        "data": data, "env_metric": env_metric, "reg_mode": reg_mode,
        "fig_history": result_history(data["history"]),
        "fig_durations": suite_duration_box(data["suite_durations"]),
        "fig_env": env_comparison(
            data["env_cells"], data["env_suites"], data["env_envs"],
            env_metric),
        "fig_first_final": first_final_trend(data["first_final"]),
        "fig_regression": duration_regression_bars(
            data["duration_regression"], reg_mode),
        "fig_freshness": freshness_heatmap(
            data["evidence_freshness"], data["freshness_suites"],
            data["freshness_envs"]),
    }


@portal_bp.route("/projects/<project_id>/analytics")
@login_required
def project_analytics(project_id):
    """Advanced-analytics JSON/CSV for the project dashboard —
    project_allowed() enforced via _project_or_404 (same as page)."""
    import csv
    import io
    from flask import jsonify
    project = _project_or_404(project_id)
    adv = _proj_adv(project.id, request.args)
    if request.args.get("format") == "csv":
        name = request.args.get("chart", "")
        d = adv["data"]
        hist_rows = []
        for case in d["history"]["cases"]:
            for run in d["history"]["runs"]:
                c = d["history"]["cells"].get(case + "|" + run["id"])
                hist_rows.append({
                    "case": case, "run": run["label"],
                    "execution_id": run["id"],
                    "attempt": run["attempt"],
                    "status": c["status"] if c else "",
                    "duration_s": c["duration"] if c else ""})
        dur_rows = [{"suite": s["suite"], "duration_s": v,
                     "execution_id": eid}
                    for s in d["suite_durations"]
                    for v, eid in zip(s["durations"], s["executions"])]
        env_rows = [
            {"suite": c["suite"], "environment": c["env"],
             "runs": c["runs"], "runs_passed": c["runs_passed"],
             "run_pass_rate": c["run_pass_rate"],
             "case_pass_rate": c["case_pass_rate"],
             "case_total": c["case_total"],
             "median_duration_s": c["median_duration"]}
            for c in d["env_cells"]]
        reg_rows = [
            {"suite": r["suite"],
             "current_median_s": r["current_median_s"],
             "baseline_median_s": r["baseline_median_s"],
             "current_n": r["current_n"],
             "baseline_n": r["baseline_n"],
             "delta_s": r["delta_s"], "delta_pct": r["delta_pct"],
             "insufficient": r["insufficient"]}
            for r in d["duration_regression"]]
        fresh_rows = [
            {"suite": r["suite"], "environment": r["env"],
             "state": r["state"], "age_s": r["age_s"],
             "last_execution_id": r["last_execution_id"],
             "last_finished_at_utc": r["last_finished_at"],
             "last_finished_at_local": r["last_finished_at_local"],
             "outcome": r["outcome"],
             "beyond_window": r["beyond_window"]}
            for r in d["evidence_freshness"]]
        rows_map = {
            "history": (["case", "run", "execution_id", "attempt",
                         "status", "duration_s"], hist_rows),
            "suite_durations": (["suite", "duration_s",
                                 "execution_id"], dur_rows),
            "environment": (["suite", "environment", "runs",
                             "runs_passed", "run_pass_rate",
                             "case_pass_rate", "case_total",
                             "median_duration_s"], env_rows),
            "first_final": (["day", "total", "first_passed",
                             "final_passed", "retried", "excluded"],
                            d["first_final"]),
            "duration_regression": (
                ["suite", "current_median_s", "baseline_median_s",
                 "current_n", "baseline_n", "delta_s", "delta_pct",
                 "insufficient"], reg_rows),
            "evidence_freshness": (
                ["suite", "environment", "state", "age_s",
                 "last_execution_id", "last_finished_at_utc",
                 "last_finished_at_local", "outcome",
                 "beyond_window"], fresh_rows),
        }
        if name not in rows_map:
            return jsonify({"error": "unknown chart"}), 404
        header, rows = rows_map[name]
        zone = d.get("timezone", "UTC")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=header + ["tz"],
                           extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "tz": zone})
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition":
                                 f"attachment; filename={name}.csv"})
    return jsonify({"generated_at": adv["data"]["generated_at"],
                    "generated_at_local":
                        adv["data"]["generated_at_local"],
                    "timezone": adv["data"]["timezone"],
                    "period_days": adv["data"]["period_days"],
                    "tables": adv["data"],
                    "charts": {"history": json.loads(adv["fig_history"]),
                               "durations": json.loads(
                                   adv["fig_durations"]),
                               "env": json.loads(adv["fig_env"]),
                               "first_final": json.loads(
                                   adv["fig_first_final"]),
                               "regression": json.loads(
                                   adv["fig_regression"]),
                               "freshness": json.loads(
                                   adv["fig_freshness"])},
                    "env_metric": adv["env_metric"],
                    "reg_mode": adv["reg_mode"]})


@portal_bp.route("/projects/<project_id>/bindings", methods=["POST"])
@role_required(*EDIT_ROLES)
def create_binding(project_id):
    project = _project_or_404(project_id)
    form = BindingForm()
    if form.validate_on_submit():
        url_err = reject_url_password(form.url.data.strip())
        if url_err:
            session["_bind_err"] = url_err
            return redirect(url_for("portal.project_detail",
                                    project_id=project_id))
        binding = GitBinding(
            authoring_writable=form.authoring_writable.data,
            report_writable=form.report_writable.data,
            project_id=project.id,
            name=form.name.data.strip(),
            url=form.url.data.strip(),
            ref=form.ref.data.strip() or "main",
            subdirectory=(form.subdirectory.data or "").strip(),
            prj_path=(form.prj_path.data or "").strip(),
            credential_ref=(form.credential_ref.data or "").strip(),
        )
        db.session.add(binding)
        db.session.flush()
        db.session.add(OutboxEvent(
            kind="git-sync",
            payload_json=json.dumps({"binding_id": binding.id})))
        db.session.commit()
        record_audit(current_user.username, "binding.created", binding.id)
    else:
        # Validation failure: preserve the submitted selection + errors so
        # the re-rendered form shows what the user entered (not defaults).
        session["_bind_aw"] = bool(request.form.get("authoring_writable"))
        session["_bind_rw"] = bool(request.form.get("report_writable"))
        session["_bind_err"] = "; ".join(
            e for errs in form.errors.values() for e in errs)
    return redirect(url_for("portal.project_detail", project_id=project_id))


@portal_bp.route("/bindings/<binding_id>/edit", methods=["POST"])
@role_required(*EDIT_ROLES)
def edit_binding(binding_id):
    binding = db.session.get(GitBinding, binding_id)
    if binding is None:
        abort(404)
    _project_or_404(binding.project_id)
    form = BindingForm()
    if form.validate_on_submit():
        url_err = reject_url_password(form.url.data.strip())
        if url_err:
            flash(url_err, "error")
            return redirect(url_for(
                "portal.project_detail",
                project_id=binding.project_id))
        binding.name = form.name.data.strip()
        binding.url = form.url.data.strip()
        binding.ref = form.ref.data.strip() or "main"
        binding.subdirectory = (form.subdirectory.data or "").strip()
        binding.prj_path = (form.prj_path.data or "").strip()
        binding.credential_ref = (form.credential_ref.data or "").strip()
        binding.authoring_writable = form.authoring_writable.data
        binding.report_writable = form.report_writable.data
        db.session.commit()
        record_audit(current_user.username, "binding.edited", binding.id)
        flash("Binding updated.", "info")
    return redirect(url_for("portal.project_detail",
                          project_id=binding.project_id))


@portal_bp.route("/bindings/<binding_id>/sync", methods=["POST"])
@role_required(*EDIT_ROLES)
def sync_binding(binding_id):
    binding = db.session.get(GitBinding, binding_id)
    if binding is None:
        abort(404)
    _project_or_404(binding.project_id)
    PlainForm().validate_on_submit()
    db.session.add(OutboxEvent(
        kind="git-sync",
        payload_json=json.dumps({"binding_id": binding.id})))
    db.session.commit()
    record_audit(current_user.username, "binding.sync_queued", binding.id)
    return redirect(url_for("portal.project_detail",
                          project_id=binding.project_id))


# ---------- framework projects (2.7.0 onboarding) ----------

def _lines(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def _fp_from_form(form, fp=None):
    fp = fp or FrameworkProject()
    fp.name = form.name.data.strip()
    fp.framework = form.framework.data
    fp.project_root = (form.project_root.data or "").strip().strip("/")
    if fp.project_root == ".":
        fp.project_root = ""
    fp.workdir = (form.workdir.data or "").strip().strip("/")
    fp.config_file = (form.config_file.data or "").strip()
    fp.test_roots_json = json.dumps(_lines(form.test_roots.data))
    fp.include_json = json.dumps(_lines(form.include.data))
    fp.exclude_json = json.dumps(_lines(form.exclude.data))
    fp.feature_roots_json = json.dumps(_lines(form.feature_roots.data))
    fp.stepdef_roots_json = json.dumps(_lines(form.stepdef_roots.data))
    fp.support_roots_json = json.dumps(_lines(form.support_roots.data))
    return fp


def _fp_form(fp=None):
    form = FrameworkProjectForm()
    form.framework.choices = FRAMEWORK_CHOICES
    if fp is not None and request.method == "GET":
        form.name.data = fp.name
        form.framework.data = fp.framework
        form.project_root.data = fp.project_root
        form.workdir.data = fp.workdir
        form.config_file.data = fp.config_file
        form.test_roots.data = "\n".join(fp.test_roots())
        form.include.data = "\n".join(fp.include())
        form.exclude.data = "\n".join(fp.exclude())
        form.feature_roots.data = "\n".join(fp.feature_roots())
        form.stepdef_roots.data = "\n".join(fp.stepdef_roots())
        form.support_roots.data = "\n".join(fp.support_roots())
    return form


def _binding_or_404(bid):
    b = db.session.get(GitBinding, bid)
    if b is None:
        abort(404)
    _project_or_404(b.project_id)
    return b


@portal_bp.route("/bindings/<binding_id>/framework-projects/new",
                 methods=["GET", "POST"])
@role_required(*EDIT_ROLES)
def fp_new(binding_id):
    """Onboard a framework project: select framework → locations →
    optional preview → save. `action=preview` runs static discovery
    WITHOUT saving; `action=save` persists as draft."""
    binding = _binding_or_404(binding_id)
    form = _fp_form()
    if form.validate_on_submit():
        fp = _fp_from_form(form)
        if request.form.get("action") == "preview":
            fp.binding_id = binding.id
            fp.project_id = binding.project_id
            res = discover(fp, binding)   # static only, not persisted
            return render_template(
                "portal/framework_project.html", form=form,
                binding=binding, fp=fp, preview=res, saved=False,
                items=None, plain_form=PlainForm(),
                can_edit=True)
        fp.binding_id = binding.id
        fp.project_id = binding.project_id
        fp.discovery_status = "draft"
        db.session.add(fp)
        db.session.commit()
        record_audit(current_user.username,
                     "framework_project.created", fp.id)
        flash(f"Framework project {fp.name!r} saved as draft — "
              "run discovery to validate before executing.", "info")
        return redirect(url_for("portal.fp_detail", fp_id=fp.id))
    for errs in form.errors.values():
        for e in errs:
            flash(e, "error")
    return render_template("portal/framework_project.html",
                           form=form, binding=binding, fp=None,
                           preview=None, saved=False, items=None,
                           plain_form=PlainForm(), can_edit=True)


@portal_bp.route("/framework-projects/<fp_id>",
                 methods=["GET"])
@login_required
def fp_detail(fp_id):
    fp = db.session.get(FrameworkProject, fp_id)
    if fp is None:
        abort(404)
    binding = _binding_or_404(fp.binding_id)
    items = DiscoveredItem.query.filter_by(
        framework_project_id=fp.id).order_by(
        DiscoveredItem.kind, DiscoveredItem.path).all()
    form = _fp_form(fp)
    return render_template(
        "portal/framework_project.html", form=form, binding=binding,
        fp=fp, preview=None, saved=True, items=items,
        plain_form=PlainForm(),
        can_edit=current_user.role.value in
        ("admin", "test_manager"))


@portal_bp.route("/framework-projects/<fp_id>/edit",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def fp_edit(fp_id):
    fp = db.session.get(FrameworkProject, fp_id)
    if fp is None:
        abort(404)
    binding = _binding_or_404(fp.binding_id)
    form = _fp_form()
    if form.validate_on_submit():
        fp = _fp_from_form(form, fp)
        # Config changed → validated inventory is stale until the
        # new fingerprint is confirmed by a discovery run.
        from ..discovery import fingerprint
        if fp.discovery_status == "ok" and \
                fp.discovery_fingerprint != fingerprint(fp):
            fp.discovery_status = "stale"
        db.session.commit()
        record_audit(current_user.username,
                     "framework_project.edited", fp.id)
        flash("Framework project updated "
              + ("— discovery is stale, re-run to validate."
                 if fp.discovery_status == "stale" else "."), "info")
    else:
        for errs in form.errors.values():
            for e in errs:
                flash(e, "error")
    return redirect(url_for("portal.fp_detail", fp_id=fp.id))


@portal_bp.route("/framework-projects/<fp_id>/preview",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def fp_preview(fp_id):
    """Static discovery preview for a saved project — does not
    persist the inventory."""
    fp = db.session.get(FrameworkProject, fp_id)
    if fp is None:
        abort(404)
    binding = _binding_or_404(fp.binding_id)
    PlainForm().validate_on_submit()
    res = discover(fp, binding)
    items = DiscoveredItem.query.filter_by(
        framework_project_id=fp.id).all()
    return render_template(
        "portal/framework_project.html", form=_fp_form(fp),
        binding=binding, fp=fp, preview=res, saved=True,
        items=items, plain_form=PlainForm(), can_edit=True)


@portal_bp.route("/framework-projects/<fp_id>/discover",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def fp_discover(fp_id):
    """Validate + persist the inventory — sets the project to 'ok'
    (validated) or 'failed' (last good kept)."""
    fp = db.session.get(FrameworkProject, fp_id)
    if fp is None:
        abort(404)
    binding = _binding_or_404(fp.binding_id)
    PlainForm().validate_on_submit()
    out = gitsync.sync_framework_project(fp, binding)
    record_audit(current_user.username,
                 "framework_project.discovered", fp.id)
    if out.get("error"):
        flash(f"Discovery failed: {out['error']}", "error")
    else:
        msg = (f"Discovery validated — {out['items']} items "
               f"({out['added']} added, {out['removed']} removed).")
        if out.get("needs_native"):
            msg += (" Some items need native collection on a worker "
                    "to become selectable.")
        flash(msg, "info")
    return redirect(url_for("portal.fp_detail", fp_id=fp.id))


@portal_bp.route("/framework-projects/<fp_id>/collect",
                 methods=["GET", "POST"])
@role_required(*EDIT_ROLES)
def fp_collect(fp_id):
    """Discover-on-worker: queues a native collection run. GET shows
    the code-execution notice + compatible target list; POST requires
    the `ack` checkbox (repository code may execute) and creates an
    Execution whose collector writes Reports/collect.json — the
    standard collect pipeline then reconciles validated identities
    into the inventory. A still-valid inventory (same sha + config
    fingerprint) needs no new approval — reading it is not a rerun."""
    fp = db.session.get(FrameworkProject, fp_id)
    if fp is None:
        abort(404)
    binding = _binding_or_404(fp.binding_id)
    runtimes = _native_collect_targets(fp)
    if request.method == "POST":
        PlainForm().validate_on_submit()
        runtime = next(
            (r for r in runtimes
             if r.id == (request.form.get("runtime_id") or "")),
            None)
        if not request.form.get("ack"):
            flash("Native collection needs the approval checkbox — "
                  "repository code may execute on the target.",
                  "error")
        elif runtime is None:
            flash("Select a compatible worker/SSH target.", "error")
        else:
            try:
                from ..gitsync import request_native_collection
                ex = request_native_collection(
                    fp, binding, runtime, current_user.username)
            except Exception as exc:
                flash(f"Collection queue failed: {exc}", "error")
            else:
                record_audit(
                    current_user.username,
                    "framework_project.native_collect",
                    f"{fp.id} on {runtime.name} -> {ex.id}")
                flash(
                    f"Native collection queued (execution {ex.id}) — "
                    "inventory reconciles when collect.json returns.",
                    "info")
                return redirect(url_for(
                    "portal.execution_detail", execution_id=ex.id))
    return render_template(
        "portal/fp_collect.html", fp=fp, binding=binding,
        runtimes=runtimes, plain_form=PlainForm())


def _native_collect_targets(fp) -> list:
    """Enabled runtimes whose kind can host this framework's native
    collector (server-side gate — the UI list is a convenience)."""
    from ..dispatch import FRAMEWORK_RUNTIME
    from ..models import RunnerInstance
    want = FRAMEWORK_RUNTIME.get(fp.framework, "")
    return [r for r in RunnerInstance.query.filter_by(
        enabled=True).order_by(RunnerInstance.name).all()
        if getattr(r, "runtime_kind", "") == want]


# ---------- Results & Artifacts storage (M9–M11) ----------

def _store_form_fields(project_id):
    """Parse the Add-Storage form. Only fields relevant to the
    selected kind are read — hidden incompatible settings are never
    persisted even if submitted (§Storage UI 9). Returns
    (kind, name, cfg, credential_ref, error)."""
    kind = (request.form.get("kind") or "local").strip()
    name = (request.form.get("name") or "").strip() or kind
    # credential_ref only exists for S3 — dropped for other kinds
    # even if a hidden field was forcibly submitted.
    credential_ref = ""
    cfg = {}
    err = None
    if kind in ("local", "mounted"):
        cfg = {"root": (request.form.get("root") or "").strip(),
               "subdir": (request.form.get("subdir") or "").strip()}
        if not cfg["root"]:
            err = "A root path is required."
    elif kind == "s3":
        credential_ref = (request.form.get("credential_ref")
                          or "").strip()
        cfg = {k: (request.form.get(k) or "").strip()
               for k in ("bucket", "prefix", "region",
                         "endpoint_url", "ca_bundle")}
        cfg["path_style"] = bool(request.form.get("path_style"))
        if not cfg["bucket"]:
            err = "S3-compatible storage requires a bucket."
    else:
        err = f"unknown store kind {kind!r}"
    return kind, name, cfg, credential_ref, err


def _flash_probe_steps(steps):
    """Render a connection-test checklist as flash lines — one row
    per check (§Storage UI 3)."""
    for label, ok, detail in steps:
        mark = "✓" if ok else "✗"
        flash(f"{mark} {label}" + (f" — {detail}" if detail else ""),
              "info" if ok else "error")


@portal_bp.route("/projects/<project_id>/artifact-stores/test",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def store_test(project_id):
    """Test Connection — run the probe against an UNSAVED store so
    the user can verify the destination before saving. The probe
    only creates/reads/deletes a small temporary object (§3)."""
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    kind, name, cfg, credential_ref, err = _store_form_fields(
        project.id)
    if err:
        flash(err, "error")
        return redirect(url_for("portal.project_detail",
                                project_id=project.id, tab="storage"))
    store = ArtifactStore(
        project_id=project.id, name=name[:128], kind=kind,
        config_json=json.dumps(cfg), credential_ref=credential_ref)
    try:
        from ..storage import backend_for, run_bounded
        steps = run_bounded(backend_for(store).probe_steps)
    except Exception as exc:
        steps = [("destination configuration", False, str(exc))]
    _flash_probe_steps(steps)
    ok = all(s[1] for s in steps)
    record_audit(current_user.username, "artifact_store.test",
                 f"{project.id} {kind} -> {'ok' if ok else 'FAIL'}")
    flash(("Connection test passed — the destination can be saved."
           if ok else "Connection test FAILED — fix the destination "
           "or ask an administrator for access, then test again."),
          "info" if ok else "error")
    return redirect(url_for("portal.project_detail",
                            project_id=project.id, tab="storage"))


@portal_bp.route("/projects/<project_id>/capture-policy",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def capture_policy_update(project_id):
    """Save the project's artifact-collection permissions
    (§storage-5). These are COLLECTION permissions — they do not
    prevent a framework from generating the files. Snapshotted per
    execution at dispatch; enforcement is server-side in _collect."""
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    from ..capture import CAPTURE_CATEGORIES, normalize_policy
    raw = {k: bool(request.form.get(f"cat_{k}"))
           for k, _, req, _ in CAPTURE_CATEGORIES if not req}
    project.capture_policy_json = json.dumps(normalize_policy(raw))
    db.session.commit()
    record_audit(current_user.username,
                 "capture_policy.updated",
                 f"{project.id}: {project.capture_policy()}")
    flash("Capture policy saved — applies to NEW executions; "
          "recorded policy on past runs is unchanged.", "info")
    return redirect(url_for("portal.project_detail",
                            project_id=project.id, tab="storage"))


@portal_bp.route("/projects/<project_id>/retention",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def retention_update(project_id):
    """Per-project retention overrides — empty field = inherit the
    global default. Applies to ALL eligible records at the next
    cleanup run, not only new executions (§storage-7)."""
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    from .. import retention
    try:
        a_days = retention.parse_days(
            request.form.get("artifact_days"))
        m_days = retention.parse_days(
            request.form.get("metadata_days"))
    except ValueError as exc:
        flash(f"Retention days must be a whole number ≥ 0. {exc}",
              "error")
        return redirect(url_for("portal.project_detail",
                                project_id=project.id, tab="storage"))
    pol = {}
    if a_days is not None:
        pol["artifact_days"] = a_days
    if m_days is not None:
        pol["metadata_days"] = m_days
    project.retention_json = json.dumps(pol)
    db.session.commit()
    record_audit(current_user.username, "retention.policy",
                 f"{project.id}: {pol}")
    flash("Retention policy saved — it applies to existing eligible "
          "records at the next cleanup run, not only new runs. "
          "Saving a policy never deletes anything by itself.", "info")
    return redirect(url_for("portal.project_detail",
                            project_id=project.id, tab="storage"))


@portal_bp.route("/projects/<project_id>/retention/preview",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def retention_preview(project_id):
    """Non-destructive count of what the CURRENT policy would expire —
    required before the destructive run is enabled."""
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    from .. import retention
    out = retention.preview(project_id=project.id)
    session[f"retention_preview_ok_{project.id}"] = \
        datetime.now().timestamp()
    a, m = out["artifacts"], out["metadata"]
    flash(f"Retention preview: {a['files']} artifact file(s) "
          f"({a['bytes']} bytes) across {a['executions']} execution(s) "
          f"would expire; {m['executions']} execution(s) including "
          "their summaries would be deleted. Nothing has been "
          "removed.", "info")
    return redirect(url_for("portal.project_detail",
                            project_id=project.id, tab="storage"))


@portal_bp.route("/projects/<project_id>/retention/run",
                 methods=["POST"])
@role_required(Role.ADMIN)
def retention_run(project_id):
    """Destructive sweep — allowed only right after a preview so the
    operator saw the affected scope first (§storage-7)."""
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    key = f"retention_preview_ok_{project.id}"
    when = session.pop(key, 0)
    if datetime.now().timestamp() - when > 600:
        flash("Run the preview first — the affected scope must be "
              "shown before deletion is allowed.", "error")
        return redirect(url_for("portal.project_detail",
                                project_id=project.id, tab="storage"))
    from .. import retention
    out = retention.sweep(project_id=project.id,
                          actor=current_user.username)
    if out["artifact_errors"]:
        flash(f"Cleanup finished with PARTIAL failures: "
              f"{out['artifacts_expired']} artifact file(s) expired, "
              f"{out['artifact_errors']} deletion error(s) (left in "
              "place for retry), "
              f"{out['executions_removed']} execution record(s) "
              "removed.", "error")
    else:
        flash(f"Cleanup complete: {out['artifacts_expired']} artifact "
              f"file(s) expired, {out['executions_removed']} "
              "execution record(s) removed.", "info")
    return redirect(url_for("portal.project_detail",
                            project_id=project.id, tab="storage"))


@portal_bp.route("/projects/<project_id>/artifact-stores/new",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def store_new(project_id):
    """Create a durable artifact store. local/mounted roots must sit
    inside the administrator-approved root lists — enforced again at
    every use, not just save. Credentials stay referenced, never in
    config_json/URLs/logs."""
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    kind, name, cfg, credential_ref, err = _store_form_fields(
        project.id)
    if err:
        flash(err, "error")
        return redirect(url_for("portal.project_detail",
                                project_id=project.id, tab="storage"))
    store = ArtifactStore(
        project_id=project.id, name=name[:128], kind=kind,
        config_json=json.dumps(cfg),
        credential_ref=credential_ref)
    try:
        from ..storage import backend_for
        ok, msg = backend_for(store).probe()
    except Exception as exc:
        ok, msg = False, str(exc)
    store.validated_at = utcnow() if ok else None
    store.last_error = "" if ok else msg[:512]
    db.session.add(store)
    db.session.commit()
    record_audit(current_user.username, "artifact_store.created",
                 f"{store.id} {kind} probe={'ok' if ok else 'FAIL'}")
    flash(f"Store {name!r} saved — probe "
          f"{'passed' if ok else 'FAILED: ' + msg}.", "info" if ok
          else "error")
    return redirect(url_for("portal.project_detail",
                            project_id=project.id, tab="storage"))


@portal_bp.route("/artifact-stores/<store_id>/probe",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def store_probe(store_id):
    """Explicit write/read/delete validation of a saved store."""
    store = db.session.get(ArtifactStore, store_id)
    if store is None:
        abort(404)
    PlainForm().validate_on_submit()
    try:
        from ..storage import backend_for, run_bounded
        steps = run_bounded(backend_for(store).probe_steps)
    except Exception as exc:
        steps = [("destination configuration", False, str(exc))]
    ok = all(s[1] for s in steps)
    msg = "; ".join(f"{l}: {d}" for l, o, d in steps if not o) or \
        "write/read/delete verified"
    store.validated_at = utcnow() if ok else None
    store.last_error = "" if ok else msg[:512]
    db.session.commit()
    record_audit(current_user.username, "artifact_store.probed",
                 f"{store.id} -> {'ok' if ok else 'FAIL'}")
    _flash_probe_steps(steps)
    flash(f"Connection test {'passed' if ok else 'FAILED'}.",
          "info" if ok else "error")
    return redirect(url_for("portal.project_detail",
                            project_id=store.project_id,
                            tab="storage"))


@portal_bp.route("/artifact-stores/<store_id>/toggle",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def store_toggle(store_id):
    """Active flag applies to NEW executions only — historical
    artifacts keep their store_id/ref and stay retrievable. Retired
    destinations cannot be re-activated (retirement is final —
    create a new destination instead)."""
    store = db.session.get(ArtifactStore, store_id)
    if store is None:
        abort(404)
    PlainForm().validate_on_submit()
    if store.retired:
        flash("Retired destinations cannot be re-activated — create "
              "a new destination instead.", "error")
        return redirect(url_for("portal.project_detail",
                                project_id=store.project_id,
                                tab="storage"))
    store.active = not store.active
    db.session.commit()
    record_audit(current_user.username, "artifact_store.toggled",
                 f"{store.id} active={store.active}")
    return redirect(url_for("portal.project_detail",
                            project_id=store.project_id,
                            tab="storage"))


@portal_bp.route("/artifact-stores/<store_id>/delete",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def store_delete(store_id):
    """Retire a destination that stored artifacts still reference —
    the config is kept so historical files stay retrievable, but it
    can never receive new writes. Only an unreferenced store is
    actually deleted (§Storage UI 4)."""
    store = db.session.get(ArtifactStore, store_id)
    if store is None:
        abort(404)
    PlainForm().validate_on_submit()
    from ..execution import Artifact
    in_use = Artifact.query.filter_by(
        store_id=store.id, storage_state="stored").count()
    if in_use:
        store.retired = True
        store.active = False
        db.session.commit()
        record_audit(current_user.username, "artifact_store.retired",
                     f"{store.id} ({in_use} stored artifacts keep "
                     "retrieval access)")
        flash(f"Destination retired — {in_use} stored artifact(s) "
              "keep retrieval access through its saved "
              "configuration; it will not receive new files.",
              "info")
    else:
        db.session.delete(store)
        db.session.commit()
        record_audit(current_user.username, "artifact_store.deleted",
                     store_id)
        flash("Destination removed — no stored artifacts referenced "
              "it.", "info")
    return redirect(url_for("portal.project_detail",
                            project_id=store.project_id,
                            tab="storage"))


@portal_bp.route("/framework-projects/<fp_id>/delete",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def fp_delete(fp_id):
    fp = db.session.get(FrameworkProject, fp_id)
    if fp is None:
        abort(404)
    binding = _binding_or_404(fp.binding_id)
    PlainForm().validate_on_submit()
    DiscoveredItem.query.filter_by(framework_project_id=fp.id).delete()
    db.session.delete(fp)
    db.session.commit()
    record_audit(current_user.username,
                 "framework_project.deleted", fp_id)
    return redirect(url_for("portal.project_detail",
                            project_id=binding.project_id,
                            tab="bindings"))


@portal_bp.route("/bindings/<binding_id>/browse")
@role_required(*EDIT_ROLES)
def binding_browse(binding_id):
    """Directory browser for onboarding — bounded, contained JSON
    listing inside the checkout. Never executes or installs."""
    from ..discovery.base import SKIP_DIRS, safe_under
    binding = _binding_or_404(binding_id)
    base = (Path(binding.worktree_path or "") /
            (binding.subdirectory or ""))
    base = base.resolve()
    rel = (request.args.get("path") or "").strip().strip("/")
    target = (base / rel).resolve()
    out = {"path": rel, "dirs": [], "files": [], "truncated": False}
    if not binding.worktree_path or not base.is_dir() or \
            not safe_under(target, base):
        return out
    if not target.is_dir():
        return out
    try:
        for e in sorted(target.iterdir())[:500]:
            if e.name.startswith(".") or e.name in SKIP_DIRS:
                continue
            if e.is_dir() and not e.is_symlink():
                out["dirs"].append(e.name)
            elif e.is_file():
                out["files"].append(e.name)
            if len(out["dirs"]) + len(out["files"]) >= 400:
                out["truncated"] = True
                break
    except OSError:
        pass
    return out


# ---------- suites ----------

@portal_bp.route("/projects/<project_id>/suites", methods=["POST"])
@role_required(*EDIT_ROLES)
def create_suite(project_id):
    project = _project_or_404(project_id)
    form = SuiteForm()
    binding = (db.session.get(GitBinding, form.binding_id.data)
               if form.binding_id.data else
               GitBinding.query.filter_by(
                   project_id=project.id).first())
    cases = gitsync.list_test_cases(binding) if binding else []
    form.case_refs.choices = [(c, c) for c in cases]
    if form.validate_on_submit():
        # posted refs — validate explicitly (field validation drops
        # non-choices silently, which would create a partial suite)
        refs = [x.strip() for x in
                request.form.getlist("case_refs") if x.strip()]
        if binding and refs:
            valid = set(gitsync.list_test_cases(binding))
            bad = [x for x in refs if x not in valid]
            if bad:
                flash("Some cases are not in the selected binding's "
                      f"source: {', '.join(bad[:3])}", "error")
                return redirect(url_for(
                    "portal.project_detail", project_id=project.id))
        suite = Suite(project_id=project.id, name=form.name.data.strip(),
                      description=form.description.data or "",
                      imported=bool(binding))
        db.session.add(suite)
        db.session.flush()  # id assigned before entries reference it
        for i, ref in enumerate(refs):
            db.session.add(SuiteEntry(
                suite_id=suite.id, order=i, case_ref=ref))
        suite.content_hash = _suite_hash(suite)
        db.session.commit()
        record_audit(current_user.username, "suite.created", suite.id)
    else:
        errs = "; ".join(
            f"{k}: {', '.join(v[:2])}"
            for k, v in form.errors.items())
        if errs:
            flash(f"Suite not created — {errs}", "error")
    return redirect(url_for("portal.project_detail", project_id=project_id))


@portal_bp.route("/projects/<project_id>/suites/new")
@role_required(*EDIT_ROLES)
def suite_new(project_id):
    project = _project_or_404(project_id)
    bindings = GitBinding.query.filter_by(project_id=project.id).all()
    binding = bindings[0] if bindings else None
    cases = (gitsync.list_test_cases(binding)
             if binding else [])
    return render_template(
        "portal/suite_edit.html", project=project, suite=None,
        binding=binding, bindings=bindings, cases=cases, selected=[],
        suite_form=SuiteForm(), can_edit=True)


@portal_bp.route("/suites/<suite_id>/edit")
@role_required(*EDIT_ROLES)
def suite_edit(suite_id):
    suite = db.session.get(Suite, suite_id)
    if suite is None:
        abort(404)
    _project_or_404(suite.project_id)
    if suite.readonly:
        abort(409)
    project = suite.project
    bindings = GitBinding.query.filter_by(project_id=project.id).all()
    binding = bindings[0] if bindings else None
    cases = (gitsync.list_test_cases(binding)
             if binding else [])
    selected = [e.case_ref for e in sorted(
        suite.entries, key=lambda e: e.order) if e.enabled]
    # keep selected-but-absent refs visible in the selector
    for c in selected:
        if c not in cases:
            cases.append(c)
    return render_template(
        "portal/suite_edit.html", project=project, suite=suite,
        binding=binding, bindings=bindings, cases=cases,
        selected=selected,
        suite_form=SuiteForm(), can_edit=True)


@portal_bp.route("/suites/<suite_id>/save", methods=["POST"])
@role_required(*EDIT_ROLES)
def save_suite(suite_id):
    suite = db.session.get(Suite, suite_id)
    if suite is None:
        abort(404)
    _project_or_404(suite.project_id)
    if suite.readonly:
        abort(409)
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    refs = [r.strip() for r in
            request.form.getlist("case_refs") if r.strip()]
    bindings = GitBinding.query.filter_by(
        project_id=suite.project_id).all()
    binding = bindings[0] if bindings else None
    if binding and refs:
        valid = set(gitsync.list_test_cases(binding))
        bad = [r for r in refs if r not in valid]
        if bad:
            # re-render with the user's work preserved
            return render_template(
                "portal/suite_edit.html", project=suite.project,
                suite=suite, binding=binding, bindings=bindings,
                cases=gitsync.list_test_cases(binding),
                selected=refs,
                suite_form=SuiteForm(), can_edit=True,
                posted_name=name,
                error=("Some cases are not in the binding's source: "
                       + ", ".join(bad[:3])))
    if not name:
        return render_template(
            "portal/suite_edit.html", project=suite.project,
            suite=suite, binding=binding, bindings=bindings,
            cases=(gitsync.list_test_cases(binding)
                   if binding else []),
            selected=refs, suite_form=SuiteForm(), can_edit=True,
            posted_name=name,
            error="Suite name is required.")
    # wholesale ordered replacement — positions come from the selector
    for e in suite.entries:
        db.session.delete(e)
    db.session.flush()
    for i, ref in enumerate(dict.fromkeys(refs)):   # dedupe, keep order
        db.session.add(SuiteEntry(suite_id=suite.id, order=i,
                                  case_ref=ref))
    suite.name = name
    suite.description = description
    suite.version += 1
    suite.content_hash = _suite_hash(suite)
    db.session.commit()
    record_audit(current_user.username, "suite.saved", suite.id)
    flash("Suite saved.", "info")
    return redirect(url_for("portal.suite_detail", suite_id=suite.id))


@portal_bp.route("/suites/<suite_id>")
@login_required
def suite_detail(suite_id):
    from ..execution import DiscoveredItem
    suite = db.session.get(Suite, suite_id)
    if suite is None:
        abort(404)
    _project_or_404(suite.project_id)
    can_run = current_user.role.value in ("admin", "test_manager", "tester")
    binding = GitBinding.query.filter_by(project_id=suite.project_id).first()
    from ..execution import Runner, RuntimeConnection
    runners = [x for x in Runner.query.filter_by(enabled=True).all()
               if not x.draining]
    runtimes = [x for x in
                RuntimeConnection.query.filter_by(enabled=True).all()
                if (not json.loads(x.allowed_projects or "[]")
                    or suite.project_id in json.loads(
                        x.allowed_projects or "[]"))]
    return render_template(
        "portal/suite_detail.html", suite=suite,
        can_author=GitBinding.query.filter_by(
            project_id=suite.project_id,
            authoring_writable=True).count() > 0, can_run=can_run,
        source_items=[i for i in DiscoveredItem.query.filter_by(
            project_id=suite.project_id).all()
            if i.kind in ("suite", "collection")],
        profiles=[i.name for i in DiscoveredItem.query.filter_by(
            project_id=suite.project_id, kind="profile")],
        binding=binding, plain_form=PlainForm(),
        workers=runners, runtimes=runtimes)


def _history_matrix(exs):
    """Case × execution matrix from a chronological execution list —
    rows keyed by case_ref (source identity, not display name)."""
    from ..execution import TestResult
    ids = [e.id for e in exs]
    rows = (TestResult.query.filter(TestResult.execution_id.in_(ids))
            .all() if ids else [])
    cases = {}
    for r in rows:
        cell = cases.get(r.case_ref)
        if cell is None:
            cell = cases[r.case_ref] = {
                "ref": r.case_ref, "name": r.case_name or r.case_ref,
                "cells": {}, "statuses": set(), "unresolved": False}
        cell["cells"][r.execution_id] = r.status.value
        cell["statuses"].add(r.status.value)
        cell["unresolved"] = cell["unresolved"] or r.unresolved
    for c in cases.values():
        c["flaky"] = "passed" in c["statuses"] and \
            len(c["statuses"] - {"skipped"}) > 1
        c["always_failing"] = bool(c["statuses"]) and \
            c["statuses"] <= {"failed", "error"}
    return sorted(cases.values(),
                  key=lambda c: (not c["flaky"],
                                 not c["always_failing"],
                                 c["name"].lower()))


_TERMINAL_FOR_MATRIX = [ExecutionState.COMPLETED,
                        ExecutionState.FAILED,
                        ExecutionState.CANCELED]


@portal_bp.route("/suites/<suite_id>/matrix")
@login_required
def suite_matrix(suite_id):
    """Case × execution history matrix (§8). A flake shows as a mixed
    row, a persistent regression as a uniformly-failing one. Skips
    stay visible as skips; unresolved rows are marked, not guessed."""
    suite = db.session.get(Suite, suite_id)
    if suite is None:
        abort(404)
    _project_or_404(suite.project_id)
    exs = (Execution.query.filter(
        Execution.suite_id == suite_id,
        Execution.state.in_(_TERMINAL_FOR_MATRIX))
        .order_by(Execution.created_at.desc(), Execution.id.desc())
        .limit(15).all())
    exs = [e for e in reversed(exs)
           if current_user.project_allowed(e.project_id or "")]
    return render_template(
        "portal/suite_matrix.html", suite=suite, item=None,
        executions=exs, cases=_history_matrix(exs))


@portal_bp.route("/discovered/<item_id>/matrix")
@login_required
def discovered_matrix(item_id):
    """Same matrix for a repository-discovered suite/collection —
    its own run history (flake + regression view)."""
    from ..execution import DiscoveredItem
    item = db.session.get(DiscoveredItem, item_id)
    if item is None:
        abort(404)
    _project_or_404(item.project_id)
    exs = (Execution.query.filter(
        Execution.source_item_id == item_id,
        Execution.state.in_(_TERMINAL_FOR_MATRIX))
        .order_by(Execution.created_at.desc(), Execution.id.desc())
        .limit(15).all())
    exs = [e for e in reversed(exs)
           if current_user.project_allowed(e.project_id or "")]
    return render_template(
        "portal/suite_matrix.html", suite=None, item=item,
        executions=exs, cases=_history_matrix(exs))


# ---------- executions ----------

@portal_bp.route("/discovered/<item_id>")
@login_required
def discovered_detail(item_id):
    from ..execution import DiscoveredItem
    item = db.session.get(DiscoveredItem, item_id)
    if item is None:
        abort(404)
    _project_or_404(item.project_id)
    from ..execution import Runner, RuntimeConnection
    runners = [x for x in Runner.query.filter_by(enabled=True).all()
               if not x.draining]
    runtimes = RuntimeConnection.query.filter_by(enabled=True).all()
    profiles = [i.name for i in DiscoveredItem.query.filter_by(
        binding_id=item.binding_id, kind="profile")]
    b2 = db.session.get(GitBinding, item.binding_id)
    coll_detail = None
    if item.kind == "collection" and b2 and b2.worktree_path:
        coll_detail = gitsync.parse_collection_detail(
            os.path.join(b2.worktree_path, item.path))
    releases = [r for r in Release.query.filter_by(
        project_id=item.project_id).all()
        if r.status in ("draft", "in_progress")]
    return render_template(
        "portal/discovered_detail.html", item=item, workers=runners,
        releases=releases,
        coll_detail=coll_detail,
        runtimes=runtimes, profiles=profiles,
        plain_form=PlainForm(),
        can_author=bool(b2 and b2.authoring_writable and
                        current_user.role.value in
                        ("admin", "test_manager")),
        binding=b2,
        can_run=current_user.role.value in
        ("admin", "test_manager", "tester"))


@portal_bp.route("/discovered/<item_id>/run", methods=["POST"])
@role_required(*RUN_ROLES)
def run_discovered(item_id):
    from ..execution import DiscoveredItem
    item = db.session.get(DiscoveredItem, item_id)
    if item is None:
        abort(404)
    # Dispatch gate: legacy suite/collection items, plus any
    # framework-project item the adapter marked selectable
    # (file/test/scenario). Candidate items (selectable=False) and
    # invalidated configs are rejected server-side in
    # create_execution via _fp_item_gate.
    _dispatchable = (item.kind in ("suite", "collection") or
                     (item.framework_project_id and item.selectable))
    if not _dispatchable:
        abort(404)
    _project_or_404(item.project_id)
    PlainForm().validate_on_submit()
    binding = db.session.get(GitBinding, item.binding_id)
    run_config = {
        "profile": request.form.get("execution_profile") or "default",
        "browser": request.form.get("browser_type", "").strip(),
        "runner_id": request.form.get("runner_id", "").strip(),
        "runtime_id": request.form.get("runtime_id", "").strip(),
        "timeout_seconds":
            int(request.form.get("timeout_seconds") or 0),
        "queue_timeout_seconds":
            int(request.form.get("queue_timeout_seconds") or 0),
        "parallel":
            min(max(int(request.form.get("parallel") or 0), 0), 64),
        "parallel_mode": request.form.get("parallel_mode", "").strip(),
        "shard_index": int(request.form.get("shard_index") or 0),
        "shard_total": int(request.form.get("shard_total") or 0),
        "suite_path": item.path,
        "robot_test": request.form.get("robot_test", "").strip(),
        "robot_include": request.form.get("robot_include", "").strip(),
        "robot_exclude": request.form.get("robot_exclude", "").strip(),
        "pytest_keyword": request.form.get("pytest_keyword", "").strip(),
        "pytest_markers": request.form.get("pytest_markers", "").strip(),
        "collection": item.kind == "collection",
        # Checkbox contract: hidden "0" + checkbox "on". Absent key
        # (non-form clients) = default enabled; present without "on"
        # = explicitly disabled.
        "retry_enabled": ("retry_enabled" not in request.form) or
            ("on" in request.form.getlist("retry_enabled")),
        "max_attempts": int(request.form.get("max_attempts") or 3),
    }
    try:
        ex = dispatch.create_execution(
            current_user.username, binding=binding,
            release_id=(request.form.get("release_id") or None),
            source_sha=binding.last_synced_sha if binding else "",
            run_config=run_config, source_item=item)
    except dispatch.DispatchError as exc:
        flash(str(exc), "error")
        return redirect(url_for("portal.discovered_detail",
                              item_id=item.id))
    record_audit(current_user.username, "execution.queued", ex.id)
    flash(f"Execution {ex.id[:8]} queued for "
          f"{item.kind} {item.path!r}.", "info")
    return redirect(url_for("portal.execution_detail", execution_id=ex.id))


@portal_bp.route("/discovered/<item_id>/partition", methods=["POST"])
@role_required(*RUN_ROLES)
def partition_discovered(item_id):
    """Preview or submit a partitioned unit run.

    mode=preview resolves the manifest and renders the assignment;
    mode=run freezes it into the unit children and queues them. The
    preview is advisory — the run re-resolves and re-validates
    everything server-side."""
    from ..execution import DiscoveredItem
    item = db.session.get(DiscoveredItem, item_id)
    if item is None or item.kind not in ("suite", "collection"):
        abort(404)
    _project_or_404(item.project_id)
    PlainForm().validate_on_submit()
    binding = db.session.get(GitBinding, item.binding_id)
    rt = db.session.get(RuntimeConnection,
                        request.form.get("runtime_id", "").strip())
    if rt is None or not rt.enabled:
        flash("Select a runtime for the partition run.", "error")
        return redirect(url_for("portal.discovered_detail",
                                item_id=item.id))
    kind = rt.runtime_kind or "kre"
    try:
        n = int(request.form.get("unit_count") or 0)
        run_config = {
            "runtime_id": rt.id,
            "runner_id": request.form.get("runner_id", "").strip(),
            "browser": request.form.get("browser_type", "").strip(),
            "timeout_seconds":
                int(request.form.get("timeout_seconds") or 0),
            "queue_timeout_seconds":
                int(request.form.get("queue_timeout_seconds") or 0),
            "suite_path": item.path,
            "collection": item.kind == "collection",
        }
        if kind == "cypress":
            specs = dispatch.discover_cypress_specs(
                binding, sha=binding.last_synced_sha or "",
                spec_pattern=request.form.get("spec_pattern", ""),
                exclude_pattern=request.form.get("exclude_pattern", ""),
                selection=[x for x in request.form.get(
                    "selected_specs", "").splitlines() if x.strip()])
            units = dispatch.partition_units(specs, n, "spec group",
                                             "specs")
        elif kind == "playwright":
            units = dispatch.playwright_shard_units(n)
        else:
            raise dispatch.DispatchError(
                f"partitioned runs support playwright and cypress "
                f"runtimes (got {kind!r})")
        if request.form.get("mode") == "preview":
            return render_template(
                "portal/partition_preview.html", item=item,
                units=units, runtime=rt, form=request.form,
                plain_form=PlainForm())
        run_config.update({
            "release_id": request.form.get("release_id") or None})
        parent, exs = dispatch.create_unit_run(
            current_user.username, units, binding=binding,
            release_id=(request.form.get("release_id") or None),
            source_sha=binding.last_synced_sha if binding else "",
            run_config=run_config, source_item=item)
    except dispatch.DispatchError as exc:
        flash(str(exc), "error")
        return redirect(url_for("portal.discovered_detail",
                                item_id=item.id))
    record_audit(current_user.username, "execution.unit_run_queued",
                 parent.id)
    flash(f"Unit run {parent.id[:8]} queued — {len(exs)} units "
          f"dispatch independently through capacity.", "info")
    return redirect(url_for("portal.execution_detail",
                            execution_id=parent.id))


@portal_bp.route("/executions/<execution_id>/delete",
             methods=["POST"])
@role_required(*EDIT_ROLES)
def delete_execution(execution_id):
    ex = _execution_or_404(execution_id)
    PlainForm().validate_on_submit()
    ex.deletion_status = "pending"
    db.session.add(OutboxEvent(
        kind="report-delete",
        payload_json=json.dumps({"execution_id": ex.id})))
    db.session.commit()
    record_audit(current_user.username, "execution.delete_queued",
                 ex.id)
    flash("Deletion queued — the repository report will be removed "
          "first, then the execution record.", "info")
    return redirect(url_for("portal.execution_detail",
                          execution_id=ex.id))


@portal_bp.route("/executions/<execution_id>/publish",
             methods=["POST"])
@role_required(*EDIT_ROLES)
def publish_execution_report(execution_id):
    ex = _execution_or_404(execution_id)
    PlainForm().validate_on_submit()
    ex.report_pub_status = "pending"
    db.session.add(OutboxEvent(
        kind="report-publish",
        payload_json=json.dumps({"execution_id": ex.id})))
    db.session.commit()
    record_audit(current_user.username, "execution.publish_queued",
                 ex.id)
    return redirect(url_for("portal.execution_detail",
                          execution_id=ex.id))


@portal_bp.route("/suites/<suite_id>/sync-to-repo", methods=["POST"])
@role_required(*EDIT_ROLES)
def sync_suite_to_repo(suite_id):
    """Export an App suite into a native-authoring draft — same
    draft/diff/publish flow as repo-created definitions."""
    from .. import authoring
    suite = db.session.get(Suite, suite_id)
    if suite is None:
        abort(404)
    _project_or_404(suite.project_id)
    binding = GitBinding.query.filter_by(
        project_id=suite.project_id, authoring_writable=True).first()
    if binding is None:
        flash("Enable Source authoring on a binding first.", "error")
        return redirect(url_for("portal.suite_detail",
                              suite_id=suite.id))
    PlainForm().validate_on_submit()
    name = suite.name.replace(" ", "_")
    d = authoring.open_new_draft(
        current_user.username, binding, "suite",
        f"Test Suites/{name}.ts", suite.name)
    refs = [e.case_ref for e in
            sorted(suite.entries, key=lambda e: e.order)]
    d.members_json = json.dumps(refs)
    db.session.commit()
    record_audit(current_user.username, "suite.sync_to_repo", suite.id)
    flash("Draft created — review the diff and publish.", "info")
    return redirect(url_for("portal.author_item",
                            item_id="", draft_id=d.id))


@portal_bp.route("/bindings/<binding_id>/author-new", methods=["POST"])
@role_required(*EDIT_ROLES)
def author_new(binding_id):
    from .. import authoring
    binding = db.session.get(GitBinding, binding_id)
    if binding is None:
        abort(404)
    _project_or_404(binding.project_id)
    if not binding.authoring_writable:
        abort(403)
    PlainForm().validate_on_submit()
    kind = request.form.get("kind", "suite")
    name = request.form.get("name", "").strip() or "New"
    path = request.form.get("path", "").strip()
    if not path or ".." in path or path.startswith("/"):
        flash("A safe repository-relative path is required.", "error")
        return redirect(url_for("portal.project_detail",
                              project_id=binding.project_id))
    refs = [x.strip() for x in
            request.form.getlist("case_refs") if x.strip()]
    d = authoring.open_new_draft(current_user.username, binding,
                                 kind, path, name)
    if refs:
        # suites dedupe by case identity; collections keep repeated
        # suite entries (same suite, different per-entry config)
        d.members_json = json.dumps(refs if kind == "collection"
                                  else list(dict.fromkeys(refs)))
        db.session.commit()
    item = _draft_item(d)
    return redirect(url_for("portal.author_item",
                            item_id=item.id if item else "new",
                            draft_id=d.id))


@portal_bp.route("/discovered/<item_id>/author")
@role_required(*EDIT_ROLES)
def author_item(item_id):
    from .. import authoring
    from ..execution import AuthoringDraft, DiscoveredItem
    draft = db.session.get(AuthoringDraft,
                           request.args.get("draft_id", ""))
    if draft is None:
        if item_id == "new":
            abort(404)   # draft_id required for draft-only authoring
        item = db.session.get(DiscoveredItem, item_id)
        if item is None or item.kind not in ("suite", "collection"):
            abort(404)
        _project_or_404(item.project_id)
        b = db.session.get(GitBinding, item.binding_id)
        if not (b and b.authoring_writable):
            abort(403)
        draft = AuthoringDraft.query.filter_by(
            binding_id=item.binding_id, path=item.path,
            owner=current_user.username, status="draft").first()
        if draft is None:
            draft = authoring.open_draft(current_user.username, item)
    else:
        _project_or_404(draft.project_id)
        if draft.owner != current_user.username:
            abort(403)
        b = db.session.get(GitBinding, draft.binding_id)
        item = db.session.get(DiscoveredItem, item_id)
    avail = (gitsync.list_test_cases(b) if draft.kind == "suite"
             else [i.path for i in DiscoveredItem.query.filter_by(
                 binding_id=b.id, kind="suite")])
    return render_template(
        "portal/author_edit.html", item=item, draft=draft, binding=b,
        cases=avail, diff=authoring.draft_diff(draft),
        review_sig=authoring.draft_signature(draft),
        disabled=[f"{i}:{m}" for i, m in enumerate(draft.members())
                  if draft.member_cfg().get(f"{i}:{m}",
                                            draft.member_cfg().get(m, {}))
                  .get("isRun") == "false"],
        plain_form=PlainForm())


def _draft_item(draft):
    from ..execution import DiscoveredItem
    return DiscoveredItem.query.filter_by(
        binding_id=draft.binding_id, path=draft.path).first()


@portal_bp.route("/author/<draft_id>/save", methods=["POST"])
@role_required(*EDIT_ROLES)
def author_save(draft_id):
    from ..execution import AuthoringDraft
    draft = db.session.get(AuthoringDraft, draft_id)
    if draft is None or draft.owner != current_user.username:
        abort(404)
    _project_or_404(draft.project_id)
    PlainForm().validate_on_submit()
    refs = [x.strip() for x in request.form.getlist("case_refs")
            if x.strip()]
    draft.members_json = json.dumps(
        refs if draft.kind == "collection"
        else list(dict.fromkeys(refs)))
    name = request.form.get("name", "").strip()
    if name:
        draft.name = name
    # per-member enabled state: enabled[] mirrors case_refs order
    enabled = set(request.form.getlist("member_enabled"))
    cfg = draft.member_cfg()
    is_run = {}
    for i, ref in enumerate(draft.members()):
        # idx+ref key keeps same-suite entries independent; legacy
        # ref-only keys remain readable as a fallback
        # collections: idx+ref (repeated suites stay independent);
        # suites: ref key (members unique by case identity)
        key = f"{i}:{ref}" if draft.kind == "collection" else ref
        base = cfg.get(key) or cfg.get(ref) or {}
        cfg[key] = dict(base, isRun=("true" if ref in enabled
                                     else "false"))
        if draft.kind == "collection":
            cfg[key]["runEnabled"] = (
                "true" if request.form.get(
                    f"membercfg_{i}_runEnabled") else "false")
            for f in ("profileName", "runConfigurationId"):
                v = request.form.get(f"membercfg_{i}_{f}")
                if v:
                    cfg[key][f] = v
            # canonical: isRun mirrors runEnabled — cannot diverge
            cfg[key]["isRun"] = cfg[key]["runEnabled"]
            is_run[ref] = cfg[key]["runEnabled"] == "true"
    draft.member_cfg_json = json.dumps(cfg)
    # suite-level editable settings (verified .ts fields)
    st = draft.settings()
    for k in ("description", "tag", "isRerun", "numberOfRerun",
              "rerunFailedTestCasesOnly", "rerunImmediately",
              "pageLoadTimeout", "pageLoadTimeoutDefault",
              "delayBetweenInstances", "executionMode",
              "maxConcurrentInstances"):
        v = request.form.get(f"setting_{k}")
        if v is not None and v != "":
            st[k] = v
    for k in ("isRerun", "rerunFailedTestCasesOnly",
              "rerunImmediately", "pageLoadTimeoutDefault"):
        if request.form.get(f"setting_{k}") is None:
            st[k] = "false"
    draft.settings_json = json.dumps(st)
    db.session.commit()
    record_audit(current_user.username, "author.draft_saved", draft.id)
    item = _draft_item(draft)
    return redirect(url_for("portal.author_item",
                            item_id=item.id if item else "",
                            draft_id=draft.id))


@portal_bp.route("/author/<draft_id>/publish", methods=["POST"])
@role_required(*EDIT_ROLES)
def author_publish(draft_id):
    from .. import authoring
    from ..execution import AuthoringDraft
    draft = db.session.get(AuthoringDraft, draft_id)
    if draft is None or draft.owner != current_user.username:
        abort(404)
    _project_or_404(draft.project_id)
    PlainForm().validate_on_submit()
    res = authoring.publish_draft(
        draft, request.form.get("review_sig", ""))
    if res.get("error"):
        flash(f"Publish failed: {res['error']}", "error")
    else:
        flash("Published to the authoring branch — syncing "
              "inventory.", "info")
        record_audit(current_user.username, "author.published",
                     draft.id)
        # publish -> auto-sync: the new/edited definition appears
        # under Repository Suites without a manual Sync click.
        db.session.add(OutboxEvent(
            kind="git-sync",
            payload_json=json.dumps(
                {"binding_id": draft.binding_id})))
        db.session.commit()
    item = _draft_item(draft)
    return redirect(url_for("portal.author_item",
                            item_id=item.id if item else "",
                            draft_id=draft.id))


@portal_bp.route("/author/<draft_id>/abandon", methods=["POST"])
@role_required(*EDIT_ROLES)
def author_abandon(draft_id):
    from ..execution import AuthoringDraft
    draft = db.session.get(AuthoringDraft, draft_id)
    if draft is None or draft.owner != current_user.username:
        abort(404)
    _project_or_404(draft.project_id)
    PlainForm().validate_on_submit()
    draft.status = "abandoned"
    db.session.commit()
    record_audit(current_user.username, "author.abandoned", draft.id)
    return redirect(url_for("portal.project_detail",
                          project_id=draft.project_id))


@portal_bp.route("/executions")
@login_required
def executions():
    """Execution history — server-side filters + bounded pagination.

    Filters: id-prefix, project (visibility-scoped), created date range,
    lifecycle state, outcome, runner, schedule linkage. Stable ordering
    (created_at,id desc); filters survive page turns via query args."""
    q = Execution.query
    # visibility scoping at the QUERY level (not post-page filtering) —
    # the page count and totals stay accurate for scoped users.
    # Non-admins see ONLY their assigned projects — an empty
    # membership list correctly yields an empty list, not 'all'.
    member_ids = None
    if current_user.role != Role.ADMIN:
        member_ids = current_user.assigned_project_ids()
        q = q.filter(Execution.project_id.in_(member_ids))
    args = request.args
    if args.get("q", "").strip():
        q = q.filter(Execution.id.startswith(args["q"].strip()[:32]))
    if args.get("project_id", ""):
        q = q.filter(Execution.project_id == args["project_id"])
    if args.get("state", ""):
        try:
            q = q.filter(Execution.state ==
                         ExecutionState(args["state"]))
        except ValueError:
            pass
    if args.get("outcome", ""):
        try:
            q = q.filter(Execution.outcome == Outcome(args["outcome"]))
        except ValueError:
            pass
    if args.get("runner_id", ""):
        q = q.filter(Execution.runner_id == args["runner_id"])
    if args.get("schedule_id", ""):
        q = q.filter(Execution.schedule_id == args["schedule_id"])
    if args.get("suite_id", ""):
        q = q.filter(Execution.suite_id == args["suite_id"])
    if args.get("environment", ""):
        env = args["environment"]
        q = q.filter(Execution.environment.is_(None)
                     if env == "__none__" else
                     Execution.environment == env)
    if args.get("role", "") in ("parent", "unit"):
        q = q.filter(Execution.role == args["role"])
    elif args.get("role", "") == "dispatch":
        # dispatchable attempts — every role that owns a process
        q = q.filter(Execution.role.in_(("", "unit")))
    if args.get("final", "") == "1":
        # Exact drill-through: only the final resolved attempt of each
        # logical run (retry chains resolved via analytics — the same
        # semantics the advanced-analytics cells count). Chains resolve
        # over the user's whole visible scope, not just this page.
        from .. import analytics as _an
        scope = Execution.query
        if member_ids is not None:
            scope = scope.filter(
                Execution.project_id.in_(member_ids))
        runs = _an.resolve_logical_runs(scope.limit(50000).all())
        final_ids = [r["final"].id for r in runs if r["final"]]
        q = q.filter(Execution.id.in_(final_ids))
    activity_mode = (args.get("activity") in ("submitted", "started")
                     and args.get("dow") is not None
                     and args.get("hour") is not None)
    if activity_mode:
        # Exact drill-through for the activity heatmap: logical runs
        # whose submitted time (head created_at) or first-execution
        # start (earliest member started_at) falls in this UTC
        # weekday×hour bucket, inside the chart's period window
        # (from_date/to_date bound the BUCKET timestamp here, not the
        # row's created_at, so the listed cohort equals the count).
        # Retries/units never inflate — the run's resolved attempt (or
        # head when unresolved) is shown.
        from .. import analytics as _an
        dow, hour = int(args["dow"]), int(args["hour"])
        scope = Execution.query
        if member_ids is not None:
            scope = scope.filter(
                Execution.project_id.in_(member_ids))
        mode = args["activity"]
        # from_date/to_date are LOCAL-day bounds in the viewer's zone;
        # bucket weekday/hour are also local — consistent with the
        # heatmap cells that generated this URL.
        from .. import usertz as _utz
        _tzv = _utz.user_zone(current_user)
        try:
            lo, hi = _utz.local_day_bounds(
                args.get("from_date") or None,
                args.get("to_date") or None, _tzv)
        except ValueError:
            lo = hi = None
        ids = []
        for r in _an.resolve_logical_runs(scope.limit(50000).all()):
            if mode == "submitted":
                t = r["head"].created_at
            else:
                t = min((m.started_at for m in r["members"]
                         if m.started_at), default=None)
            if t is None:
                continue
            if t.tzinfo is None:
                from datetime import timezone as _tz
                t = t.replace(tzinfo=_tz.utc)
            if (lo and t < lo) or (hi and t >= hi):
                continue
            lt = t.astimezone(_tzv)
            if lt.weekday() == dow and lt.hour == hour:
                ids.append((r["final"] or r["head"]).id)
        q = q.filter(Execution.id.in_(ids))
    if args.get("origin", "") in ("live", "imported"):
        q = q.filter(Execution.origin == args["origin"])
    if args.get("framework", ""):
        q = q.filter(Execution.framework == args["framework"])
    if not activity_mode and (args.get("from_date")
                              or args.get("to_date")):
        # Date filters are the viewer's local calendar days — the
        # entered bounds convert to UTC instants before querying
        # (a local "today" is not the UTC day boundary).
        from .. import usertz as _utz
        try:
            _lo, _hi = _utz.local_day_bounds(
                args.get("from_date") or None,
                args.get("to_date") or None,
                _utz.user_zone(current_user))
        except ValueError:
            _lo = _hi = None
        if _lo is not None:
            q = q.filter(Execution.created_at
                         >= _lo.replace(tzinfo=None))
        if _hi is not None:
            q = q.filter(Execution.created_at
                         < _hi.replace(tzinfo=None))
    page = max(1, int(args.get("page", 1) or 1))
    per = 50
    total = q.count()
    rows = (q.order_by(Execution.created_at.desc(), Execution.id.desc())
            .offset((page - 1) * per).limit(per).all())
    visible = [e for e in rows
               if current_user.project_allowed(e.project_id)]
    page_args = {k: v for k, v in args.items()
                 if k != "page" and v != ""}
    from ..execution import Runner as _R
    return render_template(
        "portal/executions.html", executions=visible,
        filters=args, total=total, page=page, per=per,
        page_args=page_args,
        states=[s.value for s in ExecutionState],
        outcomes=[o.value for o in Outcome],
        frameworks=sorted({e.framework for e in
                           q.with_entities(
                               Execution.framework).distinct()}),
        projects=[p for p in
                  Project.query.order_by(Project.name).all()
                  if current_user.project_allowed(p.id)],
        runners=_R.query.order_by(_R.name).all(),
        suites=[s for s in Suite.query.order_by(Suite.name).all()
                if current_user.project_allowed(s.project_id)],
        environments=sorted({e for (e,) in
                             q.with_entities(
                                 Execution.environment).distinct()
                             if e}),
        schedules=[s for s in
                   Schedule.query.order_by(Schedule.name).all()
                   if current_user.project_allowed(s.project_id)],
        plain_form=PlainForm(),
        can_run=current_user.role.value in
        ("admin", "test_manager", "tester"))


@portal_bp.route("/reconciliation")
@role_required(Role.ADMIN, Role.TEST_MANAGER)
def reconciliation():
    """Ambiguous-execution queue (§7/A06).

    Every row here either holds runner capacity in an uncertain state
    or needs operator attention before its resources can be trusted:

    - UNKNOWN — original process may still be alive; slot+procs stay
      charged until an admin confirms it stopped (resolve on detail).
    - CANCEL_REQUESTED — cancel in flight; may be racing a submission
      with no persisted Buildbot id (must NOT be force-resolved).
    - non-terminal with an expired lease — inside the ambiguity window
      before the lease sweep marks them UNKNOWN.

    Each row shows the capacity it holds (bb slot + open reservations)
    and how stale its heartbeat/lease is — never a silent stall."""
    from ..execution import ResourceReservation, Runner
    now = utcnow()

    from datetime import timezone as _tz

    def _aware(dt):
        # SQLite returns tz-naive datetimes; treat them as UTC before
        # comparing against the tz-aware `now`.
        return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=_tz.utc)
    now_sql = now.replace(tzinfo=None)   # stored values are naive UTC
    ambiguous = (Execution.query.filter(
        Execution.state.in_([ExecutionState.UNKNOWN,
                             ExecutionState.CANCEL_REQUESTED]))
        .order_by(Execution.created_at).all())
    expired_lease = (Execution.query.filter(
        Execution.state.notin_([
            ExecutionState.COMPLETED, ExecutionState.FAILED,
            ExecutionState.CANCELED, ExecutionState.UNKNOWN,
            ExecutionState.CANCEL_REQUESTED, ExecutionState.QUEUED]),
        Execution.lease_expires_at.isnot(None),
        Execution.lease_expires_at < now_sql).all())
    rows = []
    for ex in ambiguous + expired_lease:
        if not current_user.project_allowed(ex.project_id or ""):
            continue
        resv = ResourceReservation.query.filter_by(
            execution_id=ex.id, released_at=None).all()
        runner = db.session.get(Runner, ex.runner_id) \
            if ex.runner_id else None
        rows.append({
            "ex": ex, "runner": runner, "reservations": resv,
            "lease_age_s": ((now - _aware(ex.lease_expires_at))
                            .total_seconds()
                            if ex.lease_expires_at
                            and _aware(ex.lease_expires_at) < now else 0),
            "heartbeat_age_s": ((now - _aware(ex.heartbeat_at))
                                .total_seconds()
                                if ex.heartbeat_at else None),
        })
    # Orphaned evidence dirs — top-level dirs under managed roots no
    # Execution row owns (crashed confirms, deletion races). Listed
    # only; removal is the explicit admin action below.
    from .. import evidence
    try:
        orphan_dirs = [str(d) for d in evidence.find_orphans()]
    except Exception:
        orphan_dirs = []
    return render_template("portal/reconciliation.html", rows=rows,
                           orphan_dirs=orphan_dirs,
                           plain_form=PlainForm())


@portal_bp.route("/reconciliation/prune-orphans", methods=["POST"])
@role_required(*EDIT_ROLES)
def prune_orphan_evidence():
    """Remove orphaned evidence dirs — explicit admin action.
    prune_orphans re-guards every path at delete time (managed-root
    containment, no symlinks, no live references); it can only ever
    touch application-owned roots."""
    PlainForm().validate_on_submit()
    from .. import evidence
    res = evidence.prune_orphans(dry_run=False)
    record_audit(current_user.username, "evidence.orphans_pruned",
                 json.dumps({"removed": res["removed"]}))
    if res["removed"]:
        flash(f"Removed {len(res['removed'])} orphaned evidence "
              f"dir(s).", "info")
    else:
        flash("No orphaned evidence dirs to remove.", "info")
    return redirect(url_for("portal.reconciliation"))


@portal_bp.route("/executions/bulk-cancel", methods=["POST"])
@role_required(*RUN_ROLES)
def bulk_cancel_executions():
    """Bulk cancellation of explicitly selected executions via the
    existing request_cancel path — per-item auth + eligibility,
    per-item honest results. No 'all matching pages' scope in v1."""
    PlainForm().validate_on_submit()
    ids = list(dict.fromkeys(request.form.getlist("ex_ids")))
    if not ids:
        flash("No executions selected.", "error")
        return redirect(url_for("portal.executions"))
    results = {"canceled": [], "skipped": [], "denied": [], "failed": []}
    for eid in ids[:50]:                        # bounded selection
        ex = db.session.get(Execution, eid)
        if ex is None:
            results["failed"].append(eid[:8]); continue
        if not current_user.project_allowed(ex.project_id):
            results["denied"].append(eid[:8]); continue
        if (current_user.role == Role.TESTER
                and ex.created_by != current_user.username):
            results["denied"].append(eid[:8]); continue
        try:
            ok = dispatch.request_cancel(ex.id, current_user.username,
                                         "bulk-cancel")
            results["canceled" if ok else "skipped"].append(eid[:8])
        except Exception:
            results["failed"].append(eid[:8])
    record_audit(current_user.username, "execution.bulk_cancel",
                 f"{len(ids)} selected: "
                 f"{len(results['canceled'])} accepted")
    parts = [f"{k}: {len(v)}" for k, v in results.items() if v]
    flash("Bulk cancel — " + "; ".join(parts) +
          ". A request is queued — it does NOT confirm a remote "
          "process has stopped.", "info")
    # Return to the SAME filtered view the user selected from —
    # caller-controlled ret is whitelisted to known filter keys and
    # string values only; anything else falls back to the plain page.
    ret = {}
    try:
        _r = json.loads(request.form.get("ret", "{}") or "{}")
        ret = {k: str(v)[:128] for k, v in _r.items()
               if k in ("q", "project_id", "state", "outcome",
                        "runner_id", "schedule_id", "from_date",
                        "to_date", "page") and isinstance(v, str)}
    except Exception:
        pass
    return redirect(url_for("portal.executions", **ret))


@portal_bp.route("/projects/<project_id>/releases", methods=["POST"])
@role_required(*EDIT_ROLES)
def create_release(project_id):
    project = _project_or_404(project_id)
    name = request.form.get("name", "").strip()
    if name:
        rel = Release(project_id=project.id, name=name,
                      description=request.form.get(
                          "description", ""),
                      start_date=_parse_date(
                          request.form.get("start_date")),
                      end_date=_parse_date(
                          request.form.get("end_date")))
        if (rel.start_date and rel.end_date and
                rel.end_date < rel.start_date):
            flash("Target end date must be on or after the "
                  "start date.", "error")
            return redirect(url_for("portal.project_detail",
                                  project_id=project.id))
        db.session.add(rel)
        db.session.commit()
        record_audit(current_user.username, "release.created",
                     rel.id)
        return redirect(url_for("portal.release_detail",
                              release_id=rel.id))
    return redirect(url_for("portal.project_detail",
                          project_id=project_id))


@portal_bp.route("/releases/<release_id>")
@login_required
def release_detail(release_id):
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    items = ReleaseItem.query.filter_by(release_id=release.id).all()
    runs = Execution.query.filter_by(release_id=release.id).order_by(
        Execution.created_at.desc()).all()
    # scope summary vs historical totals — separate counts.
    # latest keyed by target + execution configuration — a pass under
    # one profile/runtime must not mask a failure under another.
    def _cfg(e):
        c = e.snapshot().get("run_config", {})
        return (c.get("profile", ""), c.get("browser", ""),
                c.get("runner_id", ""), c.get("runtime_id", ""))
    latest_by_path = {}
    for e in runs:
        st = e.snapshot().get("source_target", {})
        tgt = st.get("path", "")
        key = (tgt, st.get("kind", ""), st.get("binding_id", ""),
               _cfg(e))
        if tgt and key not in latest_by_path:
            latest_by_path[key] = e
    scope_rows = []
    unexecuted = 0
    unavailable = 0
    for it in items:
        src = (db.session.get(DiscoveredItem, it.source_item_id)
               if it.source_item_id else None)
        missing = src is None and it.source_item_id
        latest = next((e for (t, _k, _b, _c), e in
                       latest_by_path.items() if t == it.path), None)
        if missing:
            unavailable += 1
            state = "unavailable — definition removed from repository"
        elif latest is None:
            unexecuted += 1
            state = "not yet executed"
        else:
            state = latest.outcome.value
        scope_rows.append({"item": it, "state": state,
                           "missing": bool(missing),
                           "latest": latest})
    avail = DiscoveredItem.query.filter_by(
        binding_id=GitBinding.query.filter_by(
            project_id=release.project_id).first().id if
        GitBinding.query.filter_by(project_id=release.project_id).first()
        else "").filter(
        DiscoveredItem.kind.in_(("suite", "collection"))).all()
    return render_template(
        "portal/release_detail.html", release=release, items=items,
        runs=runs, scope_rows=scope_rows,
        unexecuted=unexecuted, unavailable=unavailable,
        avail=avail, plain_form=PlainForm())


def _parse_date(s):
    from datetime import date as _d
    if not s:
        return None
    try:
        return _d.fromisoformat(s.strip())
    except ValueError:
        return None


def _parse_run_at(s):
    """'YYYY-MM-DD HH:MM' (UTC) -> aware datetime; None on blank/bad."""
    from datetime import datetime as _dt, timezone as _tz
    if not s or not s.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt.strptime(s.strip(), fmt).replace(tzinfo=_tz.utc)
        except ValueError:
            continue
    return None


def _release_export(release, items, binding=None):
    """Portable release definition — repo paths + binding name, no
    DB ids, no secrets or machine paths. Per-run configuration is
    NOT exported — it is a launch-time choice, not part of the
    release definition."""
    return {
        "type": "testorchestrator-release",
        "version": 1,
        "name": release.name,
        "description": release.description,
        "status": release.status,
        "start_date": (release.start_date.isoformat()
                       if release.start_date else None),
        "end_date": (release.end_date.isoformat()
                     if release.end_date else None),
        "binding": binding.name if binding else "",
        "scope": [{"kind": i.kind, "path": i.path} for i in items]}


def _release_sync_sig(release, items, binding, path, base=""):
    h = hashlib.sha256()
    h.update(json.dumps(
        _release_export(release, items, binding),
        sort_keys=True).encode())
    h.update(path.encode())
    h.update(binding.id.encode())
    h.update(base.encode())
    return h.hexdigest()


@portal_bp.route("/releases/<release_id>/sync-preview")
@role_required(*EDIT_ROLES)
def release_sync_preview(release_id):
    from .. import git_backend
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    items = ReleaseItem.query.filter_by(release_id=release.id).all()
    binding = GitBinding.query.filter_by(
        project_id=release.project_id, authoring_writable=True).first()
    # cross-binding: scope items may reference defs on other bindings
    # — their paths don't resolve in the destination repo.
    bindings = {db.session.get(DiscoveredItem, i.source_item_id).binding_id
                for i in items
                if i.source_item_id and
                db.session.get(DiscoveredItem, i.source_item_id)}
    if len(bindings) > 1:
        flash("Release scope spans multiple bindings — sync exports "
              "only to the single binding the scope targets.", "error")
        return redirect(url_for("portal.release_detail",
                              release_id=release.id))
    export = _release_export(release, items, binding)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", release.name)
    path = (release.sync_path or
            f"TestOrchestration/release/{slug}.json")
    base = ""
    if binding and binding.worktree_path:
        try:
            base = git_backend.run(
                "resolve", Path(binding.worktree_path), "HEAD") or ""
        except Exception:
            pass
    sig = (_release_sync_sig(release, items, binding, path, base)
           if binding else "")
    return render_template(
        "portal/release_sync.html", release=release, export=export,
        path=path, binding=binding, sig=sig, base=base,
        plain_form=PlainForm())


@portal_bp.route("/releases/<release_id>/sync", methods=["POST"])
@role_required(*EDIT_ROLES)
def release_sync(release_id):
    """Write the release definition to TestOrchestration/release/ in
    the authoring branch — gated by authoring_writable, remote-conflict
    checked, and commits only on change."""
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    PlainForm().validate_on_submit()
    binding = db.session.get(GitBinding,
                             request.form.get("binding_id"))
    if binding is None or binding.project_id != release.project_id:
        abort(404)
    if not binding.authoring_writable:
        flash("Source authoring is not enabled on that binding.",
              "error")
        return redirect(url_for("portal.release_detail",
                              release_id=release.id))
    from .. import authoring, git_backend
    items = ReleaseItem.query.filter_by(release_id=release.id).all()
    export = _release_export(release, items, binding)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", release.name)
    path = (release.sync_path or
            f"TestOrchestration/release/{slug}.json")
    if request.form.get("sig") != _release_sync_sig(
            release, items, binding, path,
            request.form.get("base", "")):
        flash("Release changed since preview — review again.",
              "error")
        return redirect(url_for("portal.release_sync_preview",
                              release_id=release.id))
    wt = authoring._authoring_wt(binding.id)
    f = wt / path
    content = json.dumps(export, indent=2, sort_keys=True) + "\n"
    if f.exists() and f.read_text() == content:
        flash("Already in sync — no change.", "info")
        return redirect(url_for("portal.release_detail",
                              release_id=release.id))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    git_backend.run("commit", wt, path,
                    message=f"Release {release.name}: sync")
    release.sync_binding_id = binding.id
    release.sync_path = path
    release.synced_sha = git_backend.run(
        "resolve", wt, "HEAD") or ""
    release.sync_dirty = False
    db.session.commit()
    record_audit(current_user.username, "release.synced", release.id)
    flash(f"Synced {release.name} -> {path}", "info")
    return redirect(url_for("portal.release_detail",
                          release_id=release.id))


@portal_bp.route("/releases/<release_id>/scope", methods=["POST"])
@role_required(*EDIT_ROLES)
def release_scope_add(release_id):
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    PlainForm().validate_on_submit()
    item_id = request.form.get("item_id", "")
    item = db.session.get(DiscoveredItem, item_id)
    if item and item.kind in ("suite", "collection"):
        if not ReleaseItem.query.filter_by(
                release_id=release.id, path=item.path).first():
            db.session.add(ReleaseItem(
                release_id=release.id, kind=item.kind,
                path=item.path, source_item_id=item.id))
            release.sync_dirty = True
            db.session.commit()
    return redirect(url_for("portal.release_detail",
                          release_id=release.id))


@portal_bp.route("/releases/<release_id>/scope/<item_id>/remove",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def release_scope_remove(release_id, item_id):
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    PlainForm().validate_on_submit()
    it = db.session.get(ReleaseItem, item_id)
    if it and it.release_id == release.id:
        db.session.delete(it)
        release.sync_dirty = True
        db.session.commit()
    return redirect(url_for("portal.release_detail",
                          release_id=release.id))


@portal_bp.route("/executions/<execution_id>/link-release",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def link_execution_release(execution_id):
    """Link or unlink an existing project execution to a release."""
    ex = db.session.get(Execution, execution_id)
    if ex is None:
        abort(404)
    _project_or_404(ex.project_id)
    PlainForm().validate_on_submit()
    rel = request.form.get("release_id") or None
    if rel:
        release = db.session.get(Release, rel)
        if release is None or release.project_id != ex.project_id:
            abort(404)
    ex.release_id = rel
    db.session.commit()
    record_audit(current_user.username, "execution.link_release",
                 ex.id)
    return redirect(url_for("portal.execution_detail",
                          execution_id=ex.id))


@portal_bp.route("/releases/<release_id>/status", methods=["POST"])
@role_required(*EDIT_ROLES)
def release_status(release_id):
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    PlainForm().validate_on_submit()
    st = request.form.get("status", "")
    if st in ("draft", "in_progress", "released", "archived"):
        release.status = st
        release.sync_dirty = True
        if st == "released":
            release.released_at = utcnow()
        elif release.released_at:
            release.released_at = None   # reopened — re-release restamps
        db.session.commit()
        record_audit(current_user.username, "release.status", release.id)
    return redirect(url_for("portal.release_detail",
                          release_id=release.id))


@portal_bp.route("/releases/<release_id>/run", methods=["POST"])
@role_required(*RUN_ROLES)
def run_release(release_id):
    """Queue executions for every in-scope definition, linked to the
    release — same profile/worker/runtime flow as a direct run."""
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    PlainForm().validate_on_submit()
    items = ReleaseItem.query.filter_by(release_id=release.id).all()
    n = 0
    for it in items:
        src = db.session.get(DiscoveredItem, it.source_item_id) \
            if it.source_item_id else None
        path = src.path if src else it.path
        ex = Execution(
            project_id=release.project_id,
            release_id=release.id,
            suite_id=None, source_item_id=it.source_item_id,
            source_sha=(src.sha if src else ""),
            outcome=Outcome.NONE,
            snapshot_json=json.dumps({
                "source_target": {"kind": it.kind, "path": path,
                                  "binding_id": (src.binding_id
                                                 if src else "")}}),
            config_json=json.dumps({
                "profile": request.form.get("profile", "default"),
                "browser": request.form.get("browser", ""),
                "runner_id": request.form.get("runner_id", ""),
                "runtime_id": request.form.get("runtime_id", ""),
                "timeout_seconds": 3600}),
            created_by=current_user.username)
        db.session.add(ex); n += 1
        db.session.flush()
        db.session.add(OutboxEvent(
            kind="local-dispatch",
            payload_json=json.dumps({"execution_id": ex.id})))
    db.session.commit()
    record_audit(current_user.username, "release.run", release.id)
    flash(f"Queued {n} execution{'s' if n != 1 else ''} for "
          f"{release.name}.", "info")
    return redirect(url_for("portal.release_detail",
                          release_id=release.id))


@portal_bp.route("/releases/<release_id>/edit", methods=["POST"])
@role_required(*EDIT_ROLES)
def edit_release(release_id):
    release = db.session.get(Release, release_id)
    if release is None:
        abort(404)
    _project_or_404(release.project_id)
    name = request.form.get("name", "").strip()
    if name:
        release.name = name
        release.description = request.form.get("description", "")
        sd = _parse_date(request.form.get("start_date"))
        ed = _parse_date(request.form.get("end_date"))
        if sd and ed and ed < sd:
            flash("Target end date must be on or after the "
                  "start date.", "error")
            return redirect(url_for("portal.release_detail",
                                  release_id=release.id))
        release.start_date = sd
        release.end_date = ed
        release.sync_dirty = True
        db.session.commit()
        record_audit(current_user.username, "release.edited",
                     release.id)
    return redirect(url_for("portal.project_detail",
                          project_id=release.project_id))


@portal_bp.route("/suites/<suite_id>/run", methods=["POST"])
@role_required(*RUN_ROLES)
def launch_execution(suite_id):
    suite = db.session.get(Suite, suite_id)
    if suite is None:
        abort(404)
    _project_or_404(suite.project_id)
    PlainForm().validate_on_submit()
    # Submission revalidation: the required subsystem must be
    # operational now — a verified setup does not imply the worker is
    # still connected. Names the missing component (409 semantics are
    # flash + redirect here, consistent with other form rejects).
    from .. import readiness
    missing = readiness.operational_check()
    if missing:
        flash(f"Setup incomplete: {missing}", "error")
        return redirect(url_for("setup.index"))
    binding = GitBinding.query.filter_by(
        project_id=suite.project_id).first()
    sha = binding.last_synced_sha if binding else ""
    kre_options = {}
    try:
        retry_n = int(request.form.get("kre_retry", "0") or 0)
    except ValueError:
        retry_n = 0
    if retry_n > 0:
        kre_options["retry"] = min(3, retry_n)
    run_config = {
        "profile": request.form.get("execution_profile") or "default",
        "browser": request.form.get("browser_type", "").strip(),
        "remote_webdriver_url":
            request.form.get("remote_webdriver_url", "").strip(),
        "remote_webdriver_type":
            request.form.get("remote_webdriver_type", "").strip(),
        "timeout_seconds":
            int(request.form.get("timeout_seconds") or 0),
        "queue_timeout_seconds":
            int(request.form.get("queue_timeout_seconds") or 0),
        "parallel":
            min(max(int(request.form.get("parallel") or 0), 0), 64),
        "parallel_mode": request.form.get("parallel_mode", "").strip(),
        "shard_index": int(request.form.get("shard_index") or 0),
        "shard_total": int(request.form.get("shard_total") or 0),
        # Explicit execution target ("" = auto). Re-validated at
        # dispatch — never falls back to another target.
        "runner_id": request.form.get("runner_id", "").strip(),
        "source_item": request.form.get("source_item", "").strip(),
        "runtime_id": request.form.get("runtime_id", "").strip(),
        "kre_options": kre_options,
        "retry_enabled": ("retry_enabled" not in request.form) or
            ("on" in request.form.getlist("retry_enabled")),
        "max_attempts": int(request.form.get("max_attempts") or 3),
    }
    # Resolve the submitted discovered item SERVER-SIDE: kind comes
    # from the record — never trust a submitted type flag.
    si = run_config.pop("source_item", "")
    if si:
        from ..execution import DiscoveredItem
        item = db.session.get(DiscoveredItem, si)
        if (item is None or item.project_id != suite.project_id
                or item.kind not in ("suite", "collection")):
            flash("Selected source definition is invalid for this "
                  "project.", "error")
            return redirect(url_for("portal.suite_detail",
                                  suite_id=suite_id,
                                  release_id=(request.form.get(
                                      "release_id") or None)))
        run_config["suite_path"] = item.path
        run_config["collection"] = (item.kind == "collection")
    ex = dispatch.create_execution(
        current_user.username, suite, binding=binding, source_sha=sha,
        run_config=run_config)
    record_audit(current_user.username, "execution.queued", ex.id)
    flash(f"Execution {ex.id[:8]} queued.", "info")
    return redirect(url_for("portal.execution_detail", execution_id=ex.id))


@portal_bp.route("/executions/<execution_id>")
@login_required
def execution_detail(execution_id):
    can_edit = current_user.role.value in ("admin", "test_manager")
    ex = _execution_or_404(execution_id)
    counts = {}
    unresolved = 0
    for r in ex.results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
        unresolved += 1 if getattr(r, "unresolved", False) else 0
    from .. import settings as settings_mod
    units = []
    actual_concurrency = 0
    if ex.role == "parent":
        units = sorted(
            Execution.query.filter_by(parent_id=ex.id).all(),
            key=lambda e: e.unit_index or 0)
        from ..execution import ExecutionState as _ES
        active = (_ES.DISPATCHED, _ES.PREPARING, _ES.RUNNING,
                  _ES.COLLECTING, _ES.NORMALIZING)
        actual_concurrency = sum(
            1 for u in units if u.state in active)
    parent = (db.session.get(Execution, ex.parent_id)
              if ex.parent_id else None)
    store_active = ArtifactStore.query.filter_by(
        project_id=ex.project_id, active=True, retired=False
    ).first() is not None
    return render_template(
        "portal/execution_detail.html", ex=ex, counts=counts,
        plain_form=PlainForm(), can_edit=can_edit,
        unresolved=unresolved, units=units, parent=parent,
        actual_concurrency=actual_concurrency,
        store_active=store_active,
        rl_enabled=settings_mod.get("reportinglabs_enabled", True))


@portal_bp.route("/artifacts/<artifact_id>/retry", methods=["POST"])
@role_required(*EDIT_ROLES)
def artifact_retry(artifact_id):
    """Idempotent durable-storage retry for one artifact — re-runs
    the same transfer (same key), never the tests."""
    from ..execution import Artifact
    a = db.session.get(Artifact, artifact_id)
    if a is None:
        abort(404)
    ex = _execution_or_404(a.execution_id)
    PlainForm().validate_on_submit()
    from ..storage import store_execution_artifacts, run_bounded, \
        StoreError
    try:
        out = run_bounded(
            lambda: store_execution_artifacts(
                ex, Path(ex.report_dir or "")), timeout=120)
    except StoreError as exc:
        flash(f"Storage retry could not run: {exc}", "error")
        return redirect(url_for("portal.execution_detail",
                                execution_id=ex.id))
    record_audit(current_user.username, "artifact.store_retry",
                 f"{a.id} -> {out}")
    if out["skipped"]:
        flash(f"{out['skipped']} file(s) are no longer present in "
              "staging — recovery is unavailable for them; only a "
              "new run can regenerate them.", "error")
    flash(f"Storage retry: {out['stored']} stored, "
          f"{out['failed']} failed.", "info" if not out["failed"]
          else "error")
    return redirect(url_for("portal.execution_detail",
                            execution_id=ex.id))


@portal_bp.route("/executions/<execution_id>/cancel", methods=["POST"])
@login_required
def cancel_execution(execution_id):
    ex = _execution_or_404(execution_id)
    PlainForm().validate_on_submit()
    # Tester cancels only their own; Admin/TM cancel any (§16).
    if current_user.role == Role.TESTER and ex.created_by != current_user.username:
        abort(403)
    if current_user.role == Role.PO:
        abort(403)
    if dispatch.request_cancel(ex.id, current_user.username,
                               request.form.get("reason", "")):
        flash("Cancellation requested — pending until the process tree "
              "confirms termination.", "info")
    else:
        flash("Execution is already in a terminal state.", "info")
    return redirect(url_for("portal.execution_detail",
                          execution_id=execution_id))


@portal_bp.route("/executions/<execution_id>/resolve-unknown",
                 methods=["POST"])
@role_required(Role.ADMIN)
def resolve_unknown(execution_id):
    """Operator-confirmed resolution of an UNKNOWN execution.

    UNKNOWN means 'uncertain — original process may still be running'
    and the execution HOLDS its runner slot. This action is the
    operator's recorded confirmation that the original is verified
    stopped — it marks the execution FAILED and releases capacity.
    It never marks a run successful and never auto-retries."""
    ex = _execution_or_404(execution_id)
    PlainForm().validate_on_submit()
    confirm = request.form.get("confirm_stopped") == "yes"
    reason = (request.form.get("reason") or "").strip()
    if not confirm:
        flash("Confirmation required — resolving UNKNOWN does NOT stop "
              "a process; verify the original process and its children "
              "have stopped on the execution host before releasing its "
              "slot.", "error")
        return redirect(url_for("portal.execution_detail",
                              execution_id=execution_id))
    if not reason:
        flash("A confirmation note is required — record how you "
              "verified the original process stopped.", "error")
        return redirect(url_for("portal.execution_detail",
                              execution_id=execution_id))
    # CAS: only an execution still UNKNOWN can be resolved — a
    # concurrent terminal transition or double-resolve cannot
    # overwrite a newer state.
    n = db.session.query(Execution).filter(
        Execution.id == ex.id,
        Execution.state == ExecutionState.UNKNOWN,
    ).update({"state": ExecutionState.FAILED,
              "outcome": Outcome.INCOMPLETE,
              "finished_at": utcnow(),
              "error_text": (db.func.substr(Execution.error_text, 1, 1400) +
                             " | ADMIN-RESOLVED by " +
                             current_user.username + ": " + reason[:500])},
             synchronize_session=False)
    db.session.commit()
    if not n:
        db.session.rollback()
        flash("Execution is no longer UNKNOWN — its state already "
              "resolved elsewhere.", "info")
        return redirect(url_for("portal.execution_detail",
                              execution_id=execution_id))
    record_audit(current_user.username, "execution.unknown_resolved",
                 f"{ex.id}: {reason[:400]}")
    flash("Execution resolved — capacity released. Retry only when "
          "safe.", "info")
    return redirect(url_for("portal.execution_detail",
                          execution_id=execution_id))


@portal_bp.route("/executions/<execution_id>/retry", methods=["POST"])
@role_required(*RUN_ROLES)
def retry_execution(execution_id):
    """Queue the next attempt — a NEW execution linked to this one
    (attempt evidence chain, never a rerun/mutation of the original)."""
    ex = _execution_or_404(execution_id)
    PlainForm().validate_on_submit()
    try:
        new_ex = dispatch.retry_execution(current_user.username, ex)
    except dispatch.DispatchError as exc:
        flash(str(exc), "error")
        return redirect(url_for("portal.execution_detail",
                                execution_id=execution_id))
    return redirect(url_for("portal.execution_detail",
                          execution_id=new_ex.id))


def _retention_context(project) -> dict:
    """Effective retention for display: per-domain days +
    which source (project override vs global default) applies."""
    from .. import retention, settings as _s
    eff = retention.effective_policy(project)
    raw = project.retention()
    return {
        "artifact_days": eff["artifact_days"],
        "metadata_days": eff["metadata_days"],
        "artifact_source": ("project" if raw.get("artifact_days")
                            is not None else "global"),
        "metadata_source": ("project" if raw.get("metadata_days")
                            is not None else "global"),
        "global_artifact_days": int(_s.get(
            "retention_artifact_days", 0) or 0),
        "global_metadata_days": int(_s.get(
            "retention_metadata_days", 0) or 0),
        "project_raw": raw,
        "logs_days": int(_s.get("logs_retention_days", 30) or 30),
    }


_DL_STAGE_SEM = threading.BoundedSemaphore(4)
_DL_STAGE_MAX_AGE_S = 3600


def _dl_staging_dir() -> Path:
    """Staging dir for object-store downloads: lives in the instance
    dir — never under a report dir or an approved storage root, so a
    staged file can neither be collected as an artifact nor reached
    through another project's path space."""
    d = Path(current_app.instance_path) / ".dl-staging"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def _stage_object_download(backend, artifact):
    """Object-store durable copy → bounded temp file for checksum
    verification; returns (path, reader-factory). The reader deletes
    the file on iterator close; error paths unlink eagerly.

    Safeguards (§storage-5): concurrency cap so downloads can't eat
    all worker threads; size cap at the registered artifact size
    (an oversized object is refused, not trusted); ENOSPC maps to a
    clean 503; any staging error removes the partial file; a stale
    sweep removes files abandoned by process termination."""
    import errno
    import time
    if not _DL_STAGE_SEM.acquire(timeout=30):
        abort(503)
    tmp_path = None
    try:
        d = _dl_staging_dir()
        # Crash cleanup: staged files are response-ephemeral; anything
        # older than the bound is abandoned by definition.
        now = time.time()
        for f in d.iterdir():
            try:
                if f.stat().st_mtime < now - _DL_STAGE_MAX_AGE_S:
                    f.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            body = backend.open(artifact.storage_ref)
        except Exception:                                # noqa: BLE001
            abort(404)
        import tempfile
        fd, tmp_path = tempfile.mkstemp(dir=d, prefix=".dl-")
        try:
            with os.fdopen(fd, "wb") as out:
                remaining = (artifact.size or 0) + 1
                while remaining > 0:
                    chunk = body.read(min(65536, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            oversize = bool(body.read(1))
        except OSError as exc:
            Path(tmp_path).unlink(missing_ok=True)
            tmp_path = None
            if exc.errno == errno.ENOSPC:
                abort(503)
            abort(500)
        except Exception:                                # noqa: BLE001
            Path(tmp_path).unlink(missing_ok=True)
            tmp_path = None
            abort(503)
        if oversize:
            # Object exceeds the registered size — refuse, never
            # buffer unbounded content.
            Path(tmp_path).unlink(missing_ok=True)
            abort(409)
        return Path(tmp_path)
    finally:
        _DL_STAGE_SEM.release()


@portal_bp.route("/executions/<execution_id>/artifacts/<artifact_id>")
@login_required
def download_artifact(execution_id, artifact_id):
    """Authorized evidence download (§9). Active content is never served
    inline in the authenticated portal origin — it downloads only."""
    from ..execution import Artifact
    ex = _execution_or_404(execution_id)
    artifact = db.session.get(Artifact, artifact_id)
    if artifact is None or artifact.execution_id != execution_id:
        abort(404)
    root = Path(ex.report_dir or "")
    target = (root / artifact.rel_path).resolve()
    staged_ok = str(target).startswith(
        str(root.resolve()) + "/") and target.is_file()
    staged_temp = None
    st = None
    if not staged_ok:
        # Staging may be gone after cleanup — serve the durable copy
        # when the artifact reached `stored` state (§8 historical
        # access after workspace removal).
        from ..storage import backend_for, StoreError
        from ..execution import ArtifactStore
        st = db.session.get(ArtifactStore, artifact.store_id or "")
        if artifact.storage_state != "stored" or st is None:
            abort(404)
        try:
            backend = backend_for(st)
        except StoreError:
            abort(404)
        try:
            target = backend.path(artifact.storage_ref)
        except AttributeError:
            target = _stage_object_download(backend, artifact)
            staged_temp = target
        # A mounted share can block stat/read uninterruptibly — the
        # verify ops run under the bounded storage-I/O pool so a dead
        # share can't occupy request capacity indefinitely (§storage-4).
        if st.kind == "mounted":
            from ..storage import run_bounded
            try:
                exists_ok = run_bounded(
                    lambda t=target: t.is_file())
            except StoreError:
                abort(503)
        else:
            exists_ok = target.is_file()
        if not exists_ok:
            abort(404)
    # Checksum re-verified on every download — stale evidence is refused.
    from ..results import sha256_file
    if (staged_temp is None and st is not None
            and st.kind == "mounted"):
        from ..storage import run_bounded
        try:
            ok_sum = run_bounded(
                lambda: sha256_file(target) == artifact.sha256)
        except StoreError:
            abort(503)
        if not ok_sum:
            abort(409)
    elif sha256_file(target) != artifact.sha256:
        if staged_temp is not None:
            staged_temp.unlink(missing_ok=True)
        abort(409)
    record_audit(current_user.username, "artifact.download", artifact.id)
    mime = artifact.mime or "application/octet-stream"
    download_name = (artifact.rel_path.replace("\\", "/").rpartition("/")[-1]
                     or artifact.rel_path)
    if staged_temp is not None:
        # Bounded (== verified artifact size): serve from memory and
        # remove the staged copy deterministically — no reliance on
        # iterator-close ordering; the stale sweep stays as the
        # crash path for files abandoned mid-staging.
        data = staged_temp.read_bytes()
        staged_temp.unlink(missing_ok=True)
        return send_file(io.BytesIO(data), mimetype=mime,
                         download_name=download_name,
                         as_attachment=True)
    if artifact.mime in ("text/html", "image/svg+xml"):
        return send_file(target, as_attachment=True,
                         download_name=download_name)
    return send_file(target, mimetype=mime,
                     download_name=download_name, as_attachment=True)


@portal_bp.route("/executions/<execution_id>/report")
@login_required
def view_report(execution_id):
    """Hosted native-KRE report view. The entry HTML is active content:
    it is served inside a CSP sandbox (scripts disabled) so evidence
    can never execute in the authenticated portal origin."""
    ex = _execution_or_404(execution_id)
    from .. import reporting
    if ex.report_status in ("pending", "missing", "partial"):
        reporting.refresh_report_status(ex)
    if ex.report_status != "ready" or not ex.report_path:
        flash(f"No viewable report for this run "
              f"(status: {ex.report_status}).", "info")
        return redirect(url_for("portal.execution_detail",
                                execution_id=execution_id))
    try:
        target = reporting.safe_under(reporting.report_root(ex),
                                      ex.report_path)
    except ValueError:
        abort(404)
    if not target.is_file():
        abort(404)
    record_audit(current_user.username, "report.view", execution_id)
    resp = send_file(target, mimetype="text/html")
    resp.headers["Content-Security-Policy"] = "sandbox"
    return resp


@portal_bp.route("/executions/<execution_id>/report/files/<path:rel>")
@login_required
def report_asset(execution_id, rel):
    """Report assets (css/js/images) — resolved strictly inside the
    entry's own subtree of THIS run's evidence dir."""
    ex = _execution_or_404(execution_id)
    from .. import reporting
    try:
        target = reporting.safe_under(reporting.entry_dir(ex), rel)
    except ValueError:
        abort(404)
    if not target.is_file():
        abort(404)
    mime, _ = mimetypes.guess_type(target.name)
    if mime in ("text/html", "image/svg+xml"):  # active content policy
        return send_file(target, as_attachment=True,
                         download_name=target.name)
    return send_file(target, mimetype=mime or "application/octet-stream")


@portal_bp.route("/executions/<execution_id>/report.zip")
@login_required
def download_report(execution_id):
    """Usable report download: the entry subtree (html + assets) with a
    checksum manifest — not a bare index.html."""
    ex = _execution_or_404(execution_id)
    from .. import reporting
    if ex.report_status != "ready":
        reporting.refresh_report_status(ex)
    if ex.report_status != "ready":
        abort(404)
    record_audit(current_user.username, "report.download", execution_id)
    return send_file(reporting.build_report_zip(ex),
                     mimetype="application/zip", as_attachment=True,
                     download_name=f"report-{execution_id[:8]}.zip")


@portal_bp.route("/executions/<execution_id>/artifacts.zip")
@login_required
def download_artifacts(execution_id):
    """Original evidence download — every recorded artifact as collected."""
    ex = _execution_or_404(execution_id)
    from .. import reporting
    if not ex.artifacts:
        abort(404)
    record_audit(current_user.username, "artifacts.download",
                 execution_id)
    return send_file(reporting.build_artifacts_zip(ex),
                     mimetype="application/zip", as_attachment=True,
                     download_name=f"artifacts-{execution_id[:8]}.zip")


@portal_bp.route("/executions/<execution_id>/rlabs")
@login_required
def view_rlabs(execution_id):
    """Hosted reporting-labs report — a single self-contained index.html
    (scripts embedded), served inside a CSP sandbox.
    A failed regeneration keeps the PREVIOUS usable report viewable —
    the failure is surfaced, never silently hidden."""
    ex = _execution_or_404(execution_id)
    if not ex.rl_path:
        flash(f"No reporting-labs report for this run "
              f"(status: {ex.rl_status}).", "info")
        return redirect(url_for("portal.execution_detail",
                                execution_id=execution_id))
    from .. import reporting
    try:
        target = reporting.safe_under(reporting.report_root(ex),
                                      ex.rl_path)
    except ValueError:
        abort(404)
    if not target.is_file():
        abort(404)
    if ex.rl_status == "failed":
        flash("Last reporting-labs generation failed — showing the "
              "previous usable report.", "error")
    elif ex.rl_status != "ready":
        flash(f"reporting-labs report status: {ex.rl_status}", "info")
    record_audit(current_user.username, "rlabs.view", execution_id)
    # Inject a generation-scoped <base>: the single-file app fetches
    # report.json / assets/* relative to the page URL, so scoping the
    # base to the RECORDED generation means the hosted reader only ever
    # loads files from that same generation — never silently mixed with
    # a newer one. An expired generation's files 404 via rlabs_file.
    gen = target.parent.name
    base = (url_for("portal.view_rlabs", execution_id=ex.id)
            + f"/{gen}/")
    html = target.read_text(encoding="utf-8")
    html = html.replace("<head>", f'<head><base href="{base}">', 1)
    resp = Response(html, mimetype="text/html")
    # reporting-labs is a single-file interactive app — sandboxed.
    resp.headers["Content-Security-Policy"] = \
        "sandbox allow-scripts allow-same-origin"
    return resp


@portal_bp.route("/executions/<execution_id>/rlabs/<gen>/<path:subpath>")
@login_required
def rlabs_file(execution_id, gen, subpath):
    """Generation-scoped reporting-labs files (report.json, assets/*).

    Only exact `gen-<id>` directories under reporting-labs/ are valid
    — no traversal, no `current`/tmp aliases. An expired (pruned)
    generation returns a clear 404 telling the reader to reopen the
    report page, which serves the current generation."""
    ex = _execution_or_404(execution_id)
    import re as _re
    if not _re.fullmatch(r"gen-[0-9a-f]{12}", gen):
        abort(404)
    from .. import reporting
    root = reporting.report_root(ex)
    try:
        target = reporting.safe_under(
            root, f"reporting-labs/{gen}/{subpath}")
    except ValueError:
        abort(404)
    if not target.is_file():
        # expired/pruned generation — give the stale reader a clear
        # reload path instead of a bare 404 or a substituted file
        return Response(
            "This report generation has expired. Reopen the report "
            "page to load the current version.",
            status=404, mimetype="text/plain")
    return send_file(target)


@portal_bp.route("/executions/<execution_id>/rlabs.zip")
@login_required
def download_rlabs(execution_id):
    """Usable reporting-labs download — the self-contained index.html
    plus report.json and a provenance manifest."""
    import io
    import zipfile
    ex = _execution_or_404(execution_id)
    if ex.rl_status not in ("ready", "failed") or not ex.rl_path:
        abort(404)
    from .. import reporting
    target = reporting.safe_under(reporting.report_root(ex), ex.rl_path)
    if not target.is_file():
        abort(404)
    rl_dir = reporting.safe_under(reporting.report_root(ex),
                                  str(Path(ex.rl_path).parent))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(rl_dir.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(rl_dir))
        z.writestr("manifest.json", json.dumps({
            "execution_id": ex.id, "format": "reporting-labs-single-file",
            "rl_version": ex.rl_version,
            "view": "open index.html — fully self-contained"}, indent=2))
    buf.seek(0)
    record_audit(current_user.username, "rlabs.download", execution_id)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True,
                     download_name=f"rlabs-{execution_id[:8]}.zip")


@portal_bp.route("/executions/<execution_id>/rlabs/generate",
                 methods=["POST"])
@login_required
def generate_rlabs(execution_id):
    """Regenerate the reporting-labs report from STORED results — never
    reruns KRE. A failed
    regen preserves any previously usable report (status=failed)."""
    ex = _execution_or_404(execution_id)
    PlainForm().validate_on_submit()
    from ..adapters import reporting_labs as rl_adapter
    res = rl_adapter.generate_for(ex)
    flash(f"reporting-labs generation: {res['status']}"
          + (f" — {res.get('error')}" if res.get("error") else ""),
          "info" if res["status"] == "ready" else "error")
    return redirect(url_for("portal.execution_detail",
                            execution_id=execution_id))


@portal_bp.route("/executions/<execution_id>/report/refresh",
                 methods=["POST"])
@login_required
def refresh_report(execution_id):
    """Safe retry: re-scan the run's evidence dir, register any artifacts
    not yet recorded, re-assess report status. Never reruns KRE, never
    duplicates or overwrites existing rows."""
    ex = _execution_or_404(execution_id)
    PlainForm().validate_on_submit()
    from .. import reporting
    try:
        added = reporting.register_missing_artifacts(ex)
        status = reporting.refresh_report_status(ex)
        flash(f"Report collection refreshed: {added} artifact(s) "
              f"registered, status {status}.", "info")
    except Exception as exc:
        reporting.refresh_failed(ex, exc)
        flash(f"Report collection failed: {exc}", "error")
    return redirect(url_for("portal.execution_detail",
                            execution_id=execution_id))


@portal_bp.route("/executions/<execution_id>/logs/<name>")
@login_required
def view_log(execution_id, name):
    """stdout/stderr served as text/plain — never rendered as HTML."""
    ex = _execution_or_404(execution_id)
    if name not in ("kre-stdout.log", "kre-stderr.log",
                    "kre-invocation.log"):
        abort(404)
    path = Path(ex.workspace_path or "") / "logs" / name
    if not path.is_file():
        # Remote executions: logs arrive as uploaded evidence artifacts.
        path = Path(ex.report_dir or "") / "logs" / name
    if not path.is_file():
        abort(404)
    record_audit(current_user.username, "log.view", f"{execution_id}/{name}")
    return send_file(path, mimetype="text/plain")


# ---------- plans & releases (definition level, §10) ----------



@portal_bp.route("/projects/<project_id>/schedules", methods=["POST"])
@role_required(*EDIT_ROLES)
def create_schedule(project_id):
    from .forms import ScheduleForm
    project = _project_or_404(project_id)
    form = ScheduleForm()
    # Same choices the GET offers: discovered repo items + app suites —
    # a repo:<id> value must be a valid choice or validation rejects it
    # before the target can be persisted.
    form.target_id.choices = [
        (f"repo:{d.id}", f"{d.kind} · {d.path}") for d in
        DiscoveredItem.query.join(GitBinding).filter(
            GitBinding.project_id == project.id).all()] + [
        (s.id, f"Suite: {s.name}") for s in project.suites]
    # runner/runtime pins must be valid choices or SelectField
    # validation rejects the submission silently — same population
    # the GET uses.
    from ..execution import Runner as _R, RuntimeConnection as _RT
    form.runner_id.choices = [("", "Auto")] + [
        (r.id, r.name) for r in _R.query.filter_by(
            enabled=True).all() if not r.draining]
    form.runtime_id.choices = [("", "Auto")] + [
        (x.id, x.name) for x in _RT.query.filter_by(enabled=True).all()]
    if form.validate_on_submit():
        kind = form.kind.data
        run_at = _parse_run_at(form.run_at.data)
        interval = max(5, form.interval_minutes.data or 60)
        if kind == "interval" and run_at is None:
            run_at = utcnow()
        if run_at is None:
            flash("First run time is required (UTC, YYYY-MM-DD HH:MM).",
                  "error")
            return redirect(url_for("portal.project_detail",
                                    project_id=project_id))
        # Discovered-repo targets: the GET form offers repo:<item_id>
        # choices — persist them into targets_json so fire_due_schedules
        # can resolve them. A repo: value that isn't a project item is
        # rejected, never silently coerced to an empty suite_id.
        tid = form.target_id.data or ""
        targets = []
        suite_id = tid
        if tid.startswith("repo:"):
            d = db.session.get(DiscoveredItem, tid[5:])
            if d is None or d.project_id != project.id:
                flash("Selected repository target is unavailable for "
                      "this project.", "error")
                return redirect(url_for("portal.project_detail",
                                        project_id=project_id))
            targets = [{"kind": d.kind, "path": d.path,
                        "source_item_id": d.id,
                        "binding_id": d.binding_id}]
            suite_id = None
        db.session.add(Schedule(
            project_id=project.id, name=form.name.data.strip(),
            description=form.description.data or "",
            target_type="suite", suite_id=suite_id,
            plan_id=None,
            targets_json=json.dumps(targets), kind=kind,
            interval_minutes=interval if kind == "interval" else None,
            next_run_at=run_at, enabled=True,
            overlap_policy=form.overlap_policy.data or "allow",
            misfire_policy=form.misfire_policy.data or "late",
            run_config_json=json.dumps({
                "profile": form.execution_profile.data or "default",
                "browser": form.browser_type.data or "",
                "remote_webdriver_url":
                    (form.remote_webdriver_url.data or "").strip(),
                "remote_webdriver_type":
                    (form.remote_webdriver_type.data or "").strip(),
                "timeout_seconds": form.timeout_seconds.data or 3600,
                "runner_id": form.runner_id.data or "",
                "runtime_id": form.runtime_id.data or "",
            }),
            created_by=current_user.username))
        db.session.commit()
        record_audit(current_user.username, "schedule.created", project.id)
    return redirect(url_for("portal.project_detail",
                          project_id=project_id))


@portal_bp.route("/schedules/<schedule_id>/toggle", methods=["POST"])
@role_required(*EDIT_ROLES)
def toggle_schedule(schedule_id):
    sched = db.session.get(Schedule, schedule_id)
    if sched is None:
        abort(404)
    _project_or_404(sched.project_id)
    PlainForm().validate_on_submit()
    sched.enabled = not sched.enabled
    if sched.enabled and sched.next_run_at is None:
        sched.next_run_at = utcnow()
    db.session.commit()
    record_audit(current_user.username, "schedule.toggled", sched.id)
    return redirect(url_for("portal.project_detail",
                          project_id=sched.project_id))


@portal_bp.route("/schedules/<schedule_id>/edit", methods=["POST"])
@role_required(*EDIT_ROLES)
def edit_schedule(schedule_id):
    """Update timing/config + repository targets — preserves history."""
    sched = db.session.get(Schedule, schedule_id)
    if sched is None:
        abort(404)
    _project_or_404(sched.project_id)
    form = ScheduleForm()
    form.validate_on_submit()
    if request.form.get("name"):
        sched.name = request.form["name"].strip()
    for f in ("run_at", "interval_minutes", "kind",
              "execution_profile", "browser_type",
              "remote_webdriver_url", "remote_webdriver_type",
              "runner_id", "runtime_id", "timeout_seconds"):
        v = request.form.get(f)
        if v is not None and v != "":
            setattr(sched, f if f != "kind" else "kind", v)
    refs = [x for x in request.form.getlist("case_refs")
            if x.startswith("repo:")]
    if refs:
        targets = []
        for ref in refs:
            d = db.session.get(DiscoveredItem, ref[5:])
            if d and d.binding.project_id == sched.project_id:
                targets.append({"kind": d.kind, "path": d.path,
                                "source_item_id": d.id,
                                "binding_id": d.binding_id})
        if targets:
            sched.targets_json = json.dumps(targets)
            sched.target_type = "suite"   # off legacy plan
            sched.plan_id = None
    db.session.commit()
    record_audit(current_user.username, "schedule.edited", sched.id)
    return redirect(url_for("portal.project_detail",
                          project_id=sched.project_id))


@portal_bp.route("/schedules/<schedule_id>/run-now", methods=["POST"])
@role_required(*RUN_ROLES)
def run_schedule_now(schedule_id):
    """Manual trigger of a saved schedule — same config as a scheduled
    firing, new immutable snapshot, actor recorded. Disabled schedules
    cannot be run-now'd (enable first); overlap 'skip' still applies
    when the previous run is active. Does NOT advance next_run_at,
    consume a 'once' schedule, or alter recurrence — the next due fire
    still happens as scheduled."""
    sched = db.session.get(Schedule, schedule_id)
    if sched is None:
        abort(404)
    _project_or_404(sched.project_id)
    PlainForm().validate_on_submit()
    if not sched.enabled:
        flash("Schedule is disabled — enable it before triggering "
              "manually.", "error")
        return redirect(url_for("portal.project_detail",
                              project_id=sched.project_id))
    if (sched.overlap_policy == "skip"
            and db.session.query(Execution).filter(
                Execution.schedule_id == sched.id,
                Execution.state.in_(dispatch._ACTIVE_STATES)).count()):
        flash("A previous run from this schedule is still active — "
              "overlap policy 'skip' refused the manual trigger.",
              "error")
        return redirect(url_for("portal.project_detail",
                              project_id=sched.project_id))
    # Submission idempotency: each form render carries a unique token;
    # a repeated submission of the SAME token maps back to the SAME
    # execution — never a second launch. The unique constraint is the
    # only race-safe barrier (concurrent requests serialize on it).
    from ..execution import SubmitToken
    tok = (request.form.get("submit_token") or "").strip()
    if tok:
        prior = SubmitToken.query.filter_by(
            schedule_id=sched.id, username=current_user.username,
            token=tok).first()
        if prior and prior.execution_id:
            flash("This submission was already processed — showing the "
                  "same execution.", "info")
            return redirect(url_for("portal.execution_detail",
                                  execution_id=prior.execution_id))
    cfg = sched.run_config()
    binding = GitBinding.query.filter_by(
        project_id=sched.project_id).first()
    sha = binding.last_synced_sha if binding else ""
    try:
        if sched.target_type == "suite" and sched.suite_id:
            suite = db.session.get(Suite, sched.suite_id)
            if suite is None:
                raise dispatch.DispatchError("scheduled suite no longer exists")
            ex = dispatch.create_execution(
                current_user.username, suite, binding=binding,
                source_sha=sha, run_config=cfg, schedule_id=sched.id)
        elif sched.target_type == "plan" and sched.plan_id:
            plan = None
            if plan is None:
                raise dispatch.DispatchError("scheduled plan no longer exists")
            _, exs = dispatch.queue_plan_executions(
                current_user.username, plan, binding=binding,
                source_sha=sha, schedule_id=sched.id)
            ex = exs[0] if exs else None
        else:
            raise dispatch.DispatchError(
                f"invalid schedule target {sched.target_type!r}")
    except dispatch.DispatchError as exc:
        flash(str(exc), "error")
        return redirect(url_for("portal.project_detail",
                              project_id=sched.project_id))
    if tok and ex:
        try:
            db.session.add(SubmitToken(
                schedule_id=sched.id, username=current_user.username,
                token=tok, execution_id=ex.id))
            db.session.commit()
        except Exception:
            db.session.rollback()
            # Concurrent identical submission won the unique key — its
            # token row already points at the same new execution.
            prior = SubmitToken.query.filter_by(
                schedule_id=sched.id,
                username=current_user.username, token=tok).first()
            if prior and prior.execution_id != ex.id:
                # Lost to a DIFFERENT execution — report the winner.
                return redirect(url_for(
                    "portal.execution_detail",
                    execution_id=prior.execution_id))
    record_audit(current_user.username, "schedule.run_now", sched.id)
    flash("Schedule triggered manually — execution queued. The next "
          "scheduled fire is unchanged.", "info")
    return redirect(url_for("portal.execution_detail",
                          execution_id=ex.id if ex else ""))


@portal_bp.route("/schedules/<schedule_id>/delete", methods=["POST"])
@role_required(*EDIT_ROLES)
def delete_schedule(schedule_id):
    sched = db.session.get(Schedule, schedule_id)
    if sched is None:
        abort(404)
    _project_or_404(sched.project_id)
    PlainForm().validate_on_submit()
    project_id = sched.project_id
    db.session.delete(sched)
    db.session.commit()
    record_audit(current_user.username, "schedule.deleted", schedule_id)
    return redirect(url_for("portal.project_detail",
                          project_id=project_id))


def _discovery_summary(project_id: str) -> dict:
    """Typed discovered-inventory summary for the project page."""
    from ..execution import DiscoveredItem, GitBinding
    b = (GitBinding.query.filter_by(project_id=project_id)
         .order_by(GitBinding.id.desc()).first())
    if b is None:
        return {}
    items = (DiscoveredItem.query.filter_by(binding_id=b.id)
             .order_by(DiscoveredItem.parent, DiscoveredItem.path).all())
    counts = {}
    for i in items:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    warns = [i for i in items if i.warnings]
    return {"binding": b, "counts": counts, "rows": items,
            "warnings": warns}


# ---------- repository-result import ----------

@portal_bp.route("/projects/<project_id>/imports/new")
@role_required(*EDIT_ROLES)
def import_new(project_id):
    project = _project_or_404(project_id)
    bindings = [b for b in project.bindings if b.worktree_path]
    return render_template("portal/import_new.html", project=project,
                           bindings=bindings, form=PlainForm())


@portal_bp.route("/projects/<project_id>/imports/preview",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def import_preview(project_id):
    project = _project_or_404(project_id)
    PlainForm().validate_on_submit()
    from .. import importer
    binding = db.session.get(GitBinding,
                             request.form.get("binding_id", ""))
    if binding is None or binding.project_id != project.id:
        flash("Unknown binding for this project.", "error")
        return redirect(url_for("portal.import_new",
                                project_id=project.id))
    try:
        session = importer.create_preview(
            project, binding,
            request.form.get("revision", "").strip(),
            request.form.get("result_dir", "").strip(),
            current_user.username)
    except importer.ImportError_ as exc:
        flash(str(exc), "error")
        return redirect(url_for("portal.import_new",
                                project_id=project.id))
    record_audit(current_user.username, "import.preview", session.id)
    return redirect(url_for("portal.import_session",
                            project_id=project.id, session_id=session.id))


@portal_bp.route("/projects/<project_id>/imports/<session_id>")
@role_required(*EDIT_ROLES)
def import_session(project_id, session_id):
    project = _project_or_404(project_id)
    from ..execution import ImportSession
    session = db.session.get(ImportSession, session_id)
    if session is None or session.project_id != project.id:
        abort(404)
    matched = {c.match_execution_id: db.session.get(
        Execution, c.match_execution_id)
        for c in session.candidates if c.match_execution_id}
    return render_template("portal/import_preview.html",
                           project=project, session=session,
                           matched=matched, form=PlainForm())


@portal_bp.route("/projects/<project_id>/imports/<session_id>/confirm",
                 methods=["POST"])
@role_required(*EDIT_ROLES)
def import_confirm(project_id, session_id):
    project = _project_or_404(project_id)
    from ..execution import ImportSession
    PlainForm().validate_on_submit()
    session = db.session.get(ImportSession, session_id)
    if session is None or session.project_id != project.id:
        abort(404)
    selected = request.form.getlist("cand")
    force = request.form.getlist("force_new")
    from .. import importer
    try:
        summary = importer.confirm_import(
            session, selected, force, current_user.username)
    except importer.ImportError_ as exc:
        flash(str(exc), "error")
        return redirect(url_for("portal.import_session",
                                project_id=project.id,
                                session_id=session.id))
    record_audit(current_user.username, "import.confirm",
                 f"{session.id}: "
                 f"{len(summary['imported'])} imported, "
                 f"{len(summary['skipped'])} duplicates")
    return render_template("portal/import_summary.html",
                           project=project, session=session,
                           summary=summary,
                           resolved={eid: db.session.get(Execution, eid)
                                     for _c, eid in
                                     summary["imported"] +
                                     summary["skipped"] +
                                     [(c, e) for c, e, _f in
                                      summary["supplemented"]]})
