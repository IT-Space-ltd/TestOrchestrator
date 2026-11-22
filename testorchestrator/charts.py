"""Shared Plotly figure construction + theme — Python-side only.
Figures serialize to JSON; templates render via vendored plotly.js.
Aggregation stays in queries, NOT inside figures."""
import json

_PALETTE = {"passed": "#2e7d32", "failed": "#c62828",
            "error": "#ef6c00", "skipped": "#757575",
            "running": "#1565c0", "queued": "#90a4ae",
            "unknown": "#616161", "canceled": "#8d6e63"}
_BASE = dict(font=dict(family="system-ui,sans-serif", size=11),
             height=215, autosize=True,
             margin=dict(l=40, r=10, t=8, b=30),
             paper_bgcolor="rgba(0,0,0,0)",
             plot_bgcolor="rgba(0,0,0,0)", showlegend=True,
             legend=dict(orientation="h", y=-0.34,
                         font=dict(size=10)),
             xaxis=dict(tickangle=0))


def _fig(traces, layout=None):
    lay = dict(_BASE)
    lay.update(layout or {})
    return json.dumps({"data": traces, "layout": lay})


def outcome_trend(rows) -> str:
    """rows: [{day, passed, failed, error, skipped}]"""
    days = [r["day"] for r in rows]
    out = []
    for k in ("passed", "failed", "error", "skipped"):
        if any(r.get(k) for r in rows):
            out.append({"type": "bar", "name": k.capitalize(),
                        "x": days, "y": [r.get(k, 0) for r in rows],
                        "marker": {"color": _PALETTE[k]}})
    if not out:                      # all-zero period — no trace spam
        return "null"
    return _fig(out, {"barmode": "stack",
                      "yaxis": {"title": "Test cases"}})


def pass_rate_trend(rows) -> str:
    """rows: [{day, passed, failed, error}] — denominator
    passed+failed+error, skips excluded."""
    pts = []
    for r in rows:
        denom = r["passed"] + r["failed"] + r["error"]
        if denom == 0:
            continue        # skips-only day: no executed results
        pts.append({"x": r["day"], "y": 100 * r["passed"] / denom})
    if not pts:
        return "null"
    tr = [{"type": "scatter", "mode": "lines+markers",
           "name": "Pass rate %",
           "x": [p["x"] for p in pts], "y": [p["y"] for p in pts],
           "line": {"color": _PALETTE["passed"]}}]
    return _fig(tr, {"yaxis": {"title": "Pass rate %",
                               "range": [0, 105]}})


def duration_trend(rows) -> str:
    """rows: [{day, seconds}] completed executions only."""
    if not rows:
        return "null"
    tr = [{"type": "scatter", "mode": "lines+markers",
           "name": "Duration (s)",
           "x": [r["day"] for r in rows],
           "y": [r["seconds"] for r in rows],
           "line": {"color": _PALETTE["running"]}}]
    return _fig(tr, {"yaxis": {"title": "Duration (s)"}})


def failure_breakdown(rows) -> str:
    """rows: [{case, count}]"""
    if not rows:
        return "null"
    tr = [{"type": "bar", "orientation": "h",
           "name": "Failures",
           "x": [r["count"] for r in rows],
           "y": [r["case"] for r in rows],
           "marker": {"color": _PALETTE["failed"]}}]
    return _fig(tr, {"xaxis": {"title": "Occurrences"}})


def palette(key):
    return _PALETTE.get(key, _PALETTE["unknown"])


# ---------------------------------------------------------------------
# Advanced analytics builders (docs/analytics-counting.md).
# Outcome categories reuse _PALETTE; magnitude heatmaps use a sequential
# scale so they can never be read as pass/fail.

_OUTCOME_ORDER = ("passed", "failed", "incomplete", "none")
_OUTCOME_LABEL = {"passed": "passed", "failed": "failed",
                  "incomplete": "incomplete", "none": "no outcome"}
_OUTCOME_COLOR = {"passed": _PALETTE["passed"],
                  "failed": _PALETTE["failed"],
                  "incomplete": _PALETTE["error"],
                  "none": _PALETTE["unknown"]}
_SEQ_SCALE = [[0.0, "#eef3ff"], [0.25, "#c9d9f8"], [0.5, "#8fb0ee"],
              [0.75, "#4a78dd"], [1.0, "#1a56db"]]

_EXEC_LIST = "/executions"


def _exec_url(**params) -> str:
    from urllib.parse import urlencode
    return _EXEC_LIST + "?" + urlencode(
        {k: v for k, v in params.items() if v not in (None, "")})


def project_outcome_bars(rows, mode: str = "count",
                         from_date: str = "", to_date: str = "") -> str:
    """rows: [{project, project_id, passed, failed, incomplete, none}]
    Horizontal stacked bars of terminal LOGICAL RUNS per project."""
    if not rows:
        return "null"
    pct = mode == "percent"
    names = [r["project"] for r in rows]
    traces = []
    for key in _OUTCOME_ORDER:
        vals, custom = [], []
        for r in rows:
            tot = (r["passed"] + r["failed"] + r["incomplete"]
                   + r["none"])
            v = r[key]
            vals.append(round(100 * v / tot, 1) if (pct and tot) else v)
            custom.append(_exec_url(project_id=r["project_id"],
                                    outcome=key if key != "none" else
                                    "none",
                                    from_date=from_date,
                                    to_date=to_date))
        traces.append({"type": "bar", "orientation": "h",
                       "name": _OUTCOME_LABEL[key],
                       "x": vals, "y": names,
                       "customdata": custom,
                       "marker": {"color": _OUTCOME_COLOR[key]}})
    return _fig(traces, {"barmode": "stack",
                         "xaxis": {"title": "% of terminal runs"
                                   if pct else "terminal runs"},
                         "yaxis": {"automargin": True,
                                   "categoryorder": "total ascending"},
                         "height": max(215, 30 * len(rows) + 90),
                         "uirevision": "adv-cmp"})


def first_final_trend(rows) -> str:
    """rows: [{day,total,first_passed,final_passed,retried}]
    Two run-level pass-rate lines over the same logical-run cohort."""
    if not rows:
        return "null"
    days = [r["day"] for r in rows]

    def _series(field, name, color):
        y, cd = [], []
        for r in rows:
            y.append(round(100 * r[field] / r["total"], 1)
                     if r["total"] else None)
            cd.append({"num": r[field], "den": r["total"],
                       "retried": r["retried"]})
        return {"type": "scatter", "mode": "lines+markers",
                "name": name, "x": days, "y": y, "customdata": cd,
                "line": {"color": color},
                "hovertemplate":
                    "%{y}%  (%{customdata.num}/%{customdata.den}"
                    " logical runs, %{customdata.retried} retried)"
                    "<extra>" + name + "</extra>"}

    return _fig([_series("first_passed", "First attempt",
                         _PALETTE["running"]),
                 _series("final_passed", "Final attempt",
                         _PALETTE["passed"])],
                {"yaxis": {"title": "Pass rate % (logical runs)",
                           "range": [0, 105]},
                 "uirevision": "adv-ff"})


def queue_wait_trend(wait_rows, turnaround_rows) -> str:
    """Median + p95 per day for queue wait (enqueue→started) and
    turnaround (enqueue→finished — no dedicated results-ready
    timestamp; see docs/analytics-counting.md)."""
    if not wait_rows and not turnaround_rows:
        return "null"
    traces = []
    for rows, label, color in (
            (wait_rows, "queue wait (enqueue→started)",
             _PALETTE["error"]),
            (turnaround_rows, "turnaround (enqueue→finished)",
             _PALETTE["running"])):
        for stat, dash_ in (("median", "solid"), ("p95", "dot")):
            if not rows:
                continue
            traces.append({
                "type": "scatter", "mode": "lines+markers",
                "name": f"{label} · {stat}",
                "x": [r["day"] for r in rows],
                "y": [r[stat] for r in rows],
                "customdata": [r["n"] for r in rows],
                "line": {"color": color, "dash": dash_},
                "hovertemplate":
                    "%{y}s  (n=%{customdata})<extra>" + label +
                    " " + stat + "</extra>"})
    return _fig(traces, {"yaxis": {"title": "Seconds"},
                         "uirevision": "adv-queue"})


def result_history(history) -> str:
    """history: {cases, runs, cells{'case|run_id':{status,duration}}}.
    Categorical heatmap — color AND a letter per cell, never color
    alone; empty cell = case not present in that run."""
    cases, runs, cells = (history["cases"], history["runs"],
                          history["cells"])
    if not cases or not runs:
        return "null"
    code = {"passed": 1, "failed": 2, "error": 3, "skipped": 4}
    letter = {1: "P", 2: "F", 3: "E", 4: "S"}
    z, txt, hov, cd = [], [], [], []
    for c in cases:
        zr, tr, hr, cr = [], [], [], []
        for run in runs:
            cell = cells.get(c + "|" + run["id"])
            if cell is None:
                zr.append(0)
                tr.append("")
                hr.append(f"{c}<br>not present in this run")
                cr.append("")
            else:
                v = code[cell["status"]]
                zr.append(v)
                tr.append(letter[v])
                hr.append(f"{cell['case']}<br>"
                          f"{run['label']} · attempt {run['attempt']} · "
                          f"rev {run['sha'] or '—'} · env {run['env']}"
                          f"<br>{cell['status']} · "
                          f"{cell['duration']}s")
                cr.append("/executions/" + run["id"])
        z.append(zr); txt.append(tr); hov.append(hr); cd.append(cr)
    trace = {
        "type": "heatmap", "z": z,
        "x": [r["label"] for r in runs], "y": cases,
        "text": txt, "texttemplate": "%{text}",
        "hovertext": hov, "hovertemplate": "%{hovertext}<extra></extra>",
        "customdata": cd,
        "zmin": 0, "zmax": 4, "showscale": False,
        "colorscale": [
            [0.0, "#f4f5f7"], [0.24, "#f4f5f7"],
            [0.25, _PALETTE["passed"]], [0.49, _PALETTE["passed"]],
            [0.5, _PALETTE["failed"]], [0.74, _PALETTE["failed"]],
            [0.75, _PALETTE["error"]], [0.99, _PALETTE["error"]],
            [1.0, _PALETTE["skipped"]]],
        "xgap": 2, "ygap": 2}
    return _fig([trace],
                {"showlegend": False,
                 "xaxis": {"title": "run (finished day · id)",
                           "tickangle": -45, "automargin": True},
                 "yaxis": {"automargin": True,
                           "categoryorder": "array",
                           "categoryarray": cases},
                 "height": max(240, 22 * len(cases) + 90),
                 "uirevision": "adv-hist"})


def suite_duration_box(rows) -> str:
    """rows: [{suite, durations:[...], executions:[ids]}].
    One box trace per suite (logical-run durations)."""
    if not rows:
        return "null"
    traces = []
    for r in rows:
        traces.append({
            "type": "box", "name": r["suite"], "y": r["durations"],
            "customdata": r["executions"],
            "boxpoints": "outliers",
            "marker": {"color": _PALETTE["running"]},
            "line": {"color": _PALETTE["running"]},
            "hovertemplate": "%{y}s<extra>" + r["suite"] + "</extra>"})
    return _fig(traces, {"showlegend": False,
                         "yaxis": {"title": "Duration (s)"},
                         "xaxis": {"automargin": True},
                         "uirevision": "adv-box"})


def env_comparison(cells, suites, envs, metric: str) -> str:
    """cells: [{suite,env,run_pass_rate,case_pass_rate,
    median_duration,runs,case_total}]. Sequential-scale heatmap —
    magnitudes, not outcomes."""
    label = {"case_pass_rate": "case pass rate %",
             "run_pass_rate": "run pass rate %",
             "median_duration": "median duration (s)"}[metric]
    if not cells or not suites or not envs:
        return "null"
    by = {(c["suite"], c["env"]): c for c in cells}
    z, txt, hov, cd = [], [], [], []
    for s in suites:
        zr, tr, hr, cr = [], [], [], []
        for e in envs:
            c = by.get((s, e))
            if c is None or c[metric] is None:
                zr.append(None)
                tr.append("")
                hr.append(f"{s} × {e}<br>no data")
                cr.append("")
            else:
                zr.append(c[metric])
                tr.append(str(c[metric]))
                hr.append(f"{s} × {e}<br>{label}: {c[metric]}<br>"
                          f"{c['runs']} run(s), "
                          f"{c['case_total']} case result(s)")
                cr.append(_exec_url(project_id=c["project_id"],
                                    suite_id=c["suite_id"],
                                    environment=(
                                        "__none__"
                                        if c["env"] == "(unset)"
                                        else c["env"])))
        z.append(zr); txt.append(tr); hov.append(hr); cd.append(cr)
    trace = {"type": "heatmap", "z": z, "x": envs, "y": suites,
             "text": txt, "texttemplate": "%{text}",
             "hovertext": hov,
             "hovertemplate": "%{hovertext}<extra></extra>",
             "customdata": cd,
             "colorscale": _SEQ_SCALE, "showscale": True,
             "colorbar": {"title": label}, "xgap": 2, "ygap": 2}
    return _fig([trace],
                {"xaxis": {"title": "environment"},
                 "yaxis": {"automargin": True,
                           "categoryorder": "array",
                           "categoryarray": suites},
                 "height": max(215, 40 * len(suites) + 90),
                 "uirevision": "adv-env"})
