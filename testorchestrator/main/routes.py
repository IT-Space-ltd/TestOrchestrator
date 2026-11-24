"""Main blueprint: dashboard, About (v1.7), notices, admin System pages."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from flask import (Response, current_app, flash, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user, login_required

from .. import settings as settings_mod
from ..config import BASE_DIR
from ..extensions import db
from ..models import AuditEvent, Role, record_audit
from ..network import access_links
from ..security import role_required
from . import main_bp

# Owner-provided, authoritative company text (v1.7). Do not add registration
# numbers, addresses, legal claims, or copyright wording without approval.
COMPANY_NAME = "IT-Space Kft."
COMPANY_HOMEPAGE = "https://it-space.info"
APP_NAME = "TestOrchestrator"

# assets/branding/README.md tracks approval status. The official
# owner-supplied logo (iT-space-logo-400x400.png, RGBA, transparency
# preserved) replaces the development placeholder (AB07 resolved).
LOGO_APPROVED = True
LOGO_STATIC_PATH = "branding/iT-space-logo.png"


@main_bp.app_context_processor
def inject_about_context():
    """Make About content available in every authenticated template so the
    in-app About dialog renders server-side with no extra request (AB03)."""

    if not current_user.is_authenticated:
        return {}
    return {"about": about_context()}


def about_context():
    return {
        "app_name": APP_NAME,
        "company_name": COMPANY_NAME,
        "company_homepage": COMPANY_HOMEPAGE,
        "logo_path": LOGO_STATIC_PATH,
        "logo_approved": LOGO_APPROVED,
        "release": current_app.config["RELEASE_METADATA"],
        "is_admin": current_user.role == Role.ADMIN,
    }


@main_bp.route("/")
@login_required
def dashboard():
    # Approved navigation links are visible to every role; internal bind
    # details (Waitress host/port) are not exposed here (v1.8 §6).
    from .. import dashboard as dash
    from ..charts import outcome_trend, duration_trend
    period = request.args.get("days", type=int) or 30
    data = dash.snapshot(current_user, period_days=period)
    return render_template(
        "main/dashboard.html",
        links=access_links(settings_mod.all_settings()),
        data=data,
        period=period,
        outcome_fig=outcome_trend(data.get("chart_outcomes", [])),
        duration_fig=duration_trend(data.get("chart_duration", [])),
        adv=_main_adv(current_user, request.args),
    )


def _main_adv(user, args):
    """Advanced-analytics payload for the dashboard (docs/
    analytics-counting.md). Rendered server-side for first paint;
    /dashboard/analytics serves the same payload as JSON/CSV."""
    from .. import analytics
    from ..charts import (project_outcome_bars, first_final_trend,
                          queue_wait_trend, activity_heatmap)
    days = max(1, min(int(args.get("days", 30, type=int) or 30),
                      analytics.MAX_PERIOD_DAYS))
    from .. import usertz as _utz
    tz = _utz.user_zone(user)
    data = analytics.main_analytics(user, days, tz=tz)
    cmp_mode = (args.get("cmp_mode") or "count")
    cmp_mode = "percent" if cmp_mode == "percent" else "count"
    queue_mode = (args.get("queue") or "both")
    if queue_mode not in ("wait", "turnaround", "both"):
        queue_mode = "both"
    act_mode = (args.get("activity") or "submitted")
    if act_mode not in ("submitted", "started"):
        act_mode = "submitted"
    w = data["queue_wait"] if queue_mode in ("wait", "both") else []
    t = data["turnaround"] if queue_mode in ("turnaround", "both") else []
    act_rows = (data["activity_submitted"] if act_mode == "submitted"
                else data["activity_started"])
    # Activity drill bounds are LOCAL-day dates (interpreted back in
    # the viewer's zone by the executions route — never server-local).
    from datetime import datetime as _dt, timedelta as _td, \
        timezone as _tz
    _today_l = _dt.now(_tz.utc).astimezone(tz).date()
    to_d = _today_l.isoformat()
    from_d = (_today_l - _td(days=days)).isoformat()
    merged = dict(data)
    merged["activity_rows"] = act_rows
    return {
        "data": merged,
        "cmp_mode": cmp_mode, "queue_mode": queue_mode,
        "act_mode": act_mode,
        "fig_comparison": project_outcome_bars(
            data["project_outcomes"], cmp_mode, from_d, to_d),
        "fig_first_final": first_final_trend(data["first_final"]),
        "fig_queue": queue_wait_trend(w, t),
        "fig_activity": activity_heatmap(act_rows, act_mode,
                                       from_d, to_d,
                                       zone=data["timezone"]),
        "activity_rows": act_rows,
    }


@main_bp.route("/dashboard/analytics")
@login_required
def dashboard_analytics():
    """Advanced-analytics JSON (or ?format=csv&chart=<key>) — fetched
    separately from the 5 s live poll; same project_allowed scope."""
    import csv
    import io
    from flask import jsonify
    adv = _main_adv(current_user, request.args)
    if request.args.get("format") == "csv":
        name = request.args.get("chart", "")
        d = adv["data"]
        rows_map = {
            "project_outcomes": (
                ["project", "project_id", "passed", "failed",
                 "incomplete", "none"],
                d["project_outcomes"]),
            "first_final": (
                ["day", "total", "first_passed", "final_passed",
                 "retried", "excluded"],
                d["first_final"]),
            "queue_wait": (["day", "n", "median", "p95"],
                           d["queue_wait"]),
            "turnaround": (["day", "n", "median", "p95"],
                           d["turnaround"]),
            "activity": (["dow", "hour", "count"],
                         adv["activity_rows"]),
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
                    "charts": {"comparison": json.loads(
                                   adv["fig_comparison"]),
                               "first_final": json.loads(
                                   adv["fig_first_final"]),
                               "queue": json.loads(adv["fig_queue"]),
                               "activity": json.loads(
                                   adv["fig_activity"])},
                    "cmp_mode": adv["cmp_mode"],
                    "queue_mode": adv["queue_mode"],
                    "act_mode": adv["act_mode"]})


@main_bp.route("/dashboard/data")
@login_required
def dashboard_data():
    """JSON snapshot for the dashboard's ~5 s near-real-time poll.

    Same visibility scope as the page — project_allowed() applies."""
    from flask import jsonify
    from .. import dashboard as dash
    period = request.args.get("days", type=int) or 30
    return jsonify(dash.snapshot(current_user, period_days=period))


@main_bp.route("/about")
@login_required
def about():
    """Dedicated About page — same content as the in-app About dialog.

    Reachable by every authenticated role (AB01). Rendering it performs no
    network access of its own (AB03).
    """

    return render_template("main/about.html")


@main_bp.route("/about/notices")
@login_required
def notices():
    """Locally bundled third-party notices/licences (AB05)."""

    licenses_dir = Path(BASE_DIR) / "3rdparty" / "licenses"
    license_files = sorted(p.name for p in licenses_dir.glob("*") if p.is_file())
    return render_template(
        "main/notices.html", license_files=license_files
    )


@main_bp.route("/3rdparty/<path:filename>")
@login_required
def thirdparty_file(filename):
    """Serve a single bundled third-party notice/licence file locally."""

    return send_from_directory(
        Path(BASE_DIR) / "3rdparty" / "licenses", filename
    )


@main_bp.route("/system/changelog")
@role_required(Role.ADMIN)
def changelog():
    """Admin-only: System -> Changelog (v1.7: may be linked from About for
    Admin, must not be exposed to other roles)."""

    record_audit(current_user.username, "page.changelog", request.path)
    changelog_path = Path(BASE_DIR) / "CHANGELOG.md"
    try:
        changelog_text = changelog_path.read_text(encoding="utf-8")
    except OSError:
        changelog_text = ""
    return render_template("system/changelog.html",
                           changelog_html=_md_to_html(changelog_text))


def _md_to_html(text: str) -> str:
    """Minimal escape-then-convert renderer for the bundled CHANGELOG:
    headings, bullets, code spans, bold, links, horizontal rules.
    Content is escaped FIRST so raw HTML in the file can't inject."""
    import re
    from markupsafe import escape
    if not text:
        return ""
    out, in_list, para, li = [], False, [], None

    def _inline(line: str) -> str:
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", line)
        line = re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            r'<a href="\2" rel="noopener noreferrer">\1</a>', line)
        return line

    def _flush_li():
        nonlocal li
        if li is not None:
            subs = "".join(
                f"<li>{_inline(' '.join(s))}</li>" for s in li["subs"])
            nested = f"<ul>{subs}</ul>" if subs else ""
            out.append(f"<li>{_inline(li['text'])}{nested}</li>")
            li = None

    def _flush_para():
        nonlocal para
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para = []

    def _flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in text.splitlines():
        line = escape(raw)
        if not line.strip():
            _flush_li(); _flush_para(); _flush_list()
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            _flush_li(); _flush_para(); _flush_list()
            lvl = len(m.group(1)) + 1
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        if re.match(r"^---+\s*$", line):
            _flush_li(); _flush_para(); _flush_list()
            out.append("<hr>")
            continue
        bm = re.match(r"^(\s*)[-*]\s+(.*)", line)
        if bm:
            indent = len(bm.group(1).expandtabs(4))
            if indent >= 2 and li is not None:
                # nested bullet inside the open item (one level —
                # enough for the changelog's grouped sub-points)
                _flush_para()
                li["subs"].append([bm.group(2).strip()])
                continue
            _flush_li(); _flush_para()
            if not in_list:
                out.append("<ul>"); in_list = True
            li = {"text": bm.group(2).strip(), "subs": []}
            continue
        # Continuation: soft-wrapped text joins the open bullet item if
        # one is open, otherwise accumulates into the paragraph — a
        # blank line (or new block) is what ends either. str() keeps
        # Markup.__radd__ from re-escaping the already-escaped left
        # operand (& -> &amp; -> &amp;amp;).
        if li is not None:
            lead = len(raw) - len(raw.lstrip(" \t"))
            if li["subs"] and lead >= 4:
                li["subs"][-1].append(str(line).strip())
            else:
                li["text"] += " " + str(line).strip()
        else:
            para.append(str(line).strip())
    _flush_li(); _flush_para(); _flush_list()
    return "".join(out)


AUDIT_PAGE_SIZE = 50


@main_bp.route("/system/audit")
@role_required(Role.ADMIN)
def audit():
    """Admin-only audit page — server-side search/filter/pagination over
    the stored safe fields (username, event, detail, occurred_at).
    Free-text search never touches stored secrets (none are stored in
    audit rows by design)."""

    record_audit(current_user.username, "page.audit", request.path)
    filters = _audit_filters()
    # Same query object contract as the export — the page count and the
    # export count can never disagree.
    from .. import logexport
    q = logexport.audit_query(filters)
    page = max(1, request.args.get("page", 1, type=int) or 1)
    total = q.count()
    # Deterministic ordering: time then id tiebreak.
    events = (q.order_by(AuditEvent.occurred_at.desc(),
                         AuditEvent.id.desc())
               .offset((page - 1) * AUDIT_PAGE_SIZE)
               .limit(AUDIT_PAGE_SIZE).all())
    pages = max(1, -(-total // AUDIT_PAGE_SIZE))
    event_types = [r[0] for r in db.session.query(
        AuditEvent.event).distinct().order_by(AuditEvent.event).all()]
    actors = [r[0] for r in db.session.query(
        AuditEvent.username).distinct().order_by(
        AuditEvent.username).all()]
    return render_template(
        "system/audit.html", events=events, filters=filters,
        page=page, pages=pages, total=total,
        event_types=event_types, actors=actors)


def _audit_filters() -> dict:
    """Current Audit Trail filters — shared by the page and export.

    Date-only bounds are the viewer's local calendar days; they're
    converted to naive-UTC instant strings here so the shared query
    + the stored job filters bound the same instants."""
    from .. import usertz as _utz
    tz = _utz.request_tz()
    out = {
        "q": request.args.get("q", "").strip(),
        "event": request.args.get("event", "").strip(),
        "actor": request.args.get("actor", "").strip(),
        "related": request.args.get("related", "").strip(),
        "from": request.args.get("from", "").strip(),
        "to": request.args.get("to", "").strip(),
    }
    for bound in ("from", "to"):
        raw = out[bound]
        if len(raw) == 10:
            try:
                lo, hi = _utz.local_day_bounds(raw, raw, tz)
            except ValueError:
                continue
            inst = lo if bound == "from" else hi
            out[bound] = inst.replace(tzinfo=None).isoformat()
    return out


@main_bp.route("/system/audit/export")
@role_required(Role.ADMIN)
def audit_export():
    """Export ALL audit rows matching the current filters — inline CSV
    when bounded, background job above the inline cap. Audited with
    filters + count (never content); never silently truncated."""
    from .. import logexport
    filters = _audit_filters()
    try:
        from .. import usertz as _utz
        mode, job, count, cutoff, max_id = logexport.request_export(
            "audit", filters, current_user.username,
            tz_name=_utz.request_tz_name())
    except logexport.TooManyRowsError as exc:
        record_audit(current_user.username, "logs.export.denied",
                     f"audit export refused: {exc}")
        flash(f"Export refused: {exc}. Narrow the filters.", "error")
        return redirect(url_for("main.audit", **request.args))
    except logexport.BusyError:
        flash("Another large export is still running — retry shortly.",
              "error")
        return redirect(url_for("main.audit", **request.args))
    record_audit(
        current_user.username, "logs.export",
        f"audit csv export: {count} rows, cutoff "
        f"{cutoff.isoformat()}, filters {json.dumps(filters)}"
        + (f", job {job.id}" if job else ""))
    if mode == "job":
        return redirect(url_for("system.log_export_status",
                                job_id=job.id))
    fname = logexport.export_filename("audit", "inline", cutoff)
    app = current_app._get_current_object()
    from .. import usertz as _utz
    return Response(logexport.stream_csv(app, "audit", filters, cutoff,
                                         max_id,
                                         tz_name=_utz.request_tz_name()),
                    mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f"attachment; filename={fname}"})
@main_bp.app_errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403,
                           message="You do not have access to this page."), 403


@main_bp.app_errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404,
                           message="Page not found."), 404
