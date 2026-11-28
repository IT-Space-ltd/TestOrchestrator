import json
from datetime import datetime, timedelta, timezone

from testorchestrator.execution import (CaseStatus, Execution, ExecutionState,
                                        Outcome, Project, TestResult)
from testorchestrator.extensions import db
from testorchestrator.models import User


def _mk_exec(project, outcome=Outcome.PASSED, created_by="tester"):
    e = Execution(project_id=project.id, outcome=outcome, created_by=created_by,
                  created_at=datetime.now(timezone.utc))
    db.session.add(e)
    db.session.commit()
    return e


def test_reports_menu_page_and_csv_are_project_scoped(app, client, login_as):
    with app.app_context():
        p1 = Project(name="Visible")
        p2 = Project(name="Hidden")
        db.session.add_all([p1, p2]); db.session.commit()
        p2id = p2.id
        e1 = _mk_exec(p1, Outcome.PASSED).id
        e2 = _mk_exec(p2, Outcome.FAILED).id
        po = User.query.filter_by(username="po").one()
        po.set_assigned_projects([p1.id]); db.session.commit()
    login_as("po")
    resp = client.get("/reports")
    body = resp.data.decode()
    assert resp.status_code == 200
    assert e1[:8] in body
    assert e2[:8] not in body
    assert "Hidden" not in body
    # Even an explicit client filter for the hidden project cannot widen scope.
    resp = client.get(f"/reports?project_id={p2id}&format=csv")
    assert resp.status_code == 200
    text = resp.data.decode()
    assert e1 not in text and e2 not in text
    assert "execution_id,project_id" in text


def test_reports_menu_shows_admin_rows_and_audit_csv(app, client, login_as):
    with app.app_context():
        p = Project(name="ReportsProject")
        db.session.add(p); db.session.commit()
        e = _mk_exec(p, Outcome.PASSED).id
    login_as("admin")
    resp = client.get("/reports")
    assert resp.status_code == 200
    assert e[:8] in resp.data.decode()
    resp = client.get("/reports?format=csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert e in resp.data.decode()
    filtered = client.get("/reports?outcome=failed")
    assert e[:8] not in filtered.data.decode()
    filtered = client.get("/reports?outcome=passed")
    assert e[:8] in filtered.data.decode()


def test_reports_csv_neutralizes_spreadsheet_formulas(app, client, login_as):
    with app.app_context():
        p = Project(name="CsvSafety")
        db.session.add(p); db.session.commit()
        e = Execution(project_id=p.id, outcome=Outcome.PASSED,
                      created_at=datetime.now(timezone.utc),
                      created_by="=cmd", environment="+prod")
        db.session.add(e); db.session.commit()
    login_as("admin")
    resp = client.get("/reports?format=csv")
    text = resp.data.decode()
    assert "'=cmd" in text and "'+prod" in text


def test_reports_trend_type_charts_table_csv(app, client, login_as):
    with app.app_context():
        p = Project(name="TrendProject")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        e = Execution(project_id=p.id, outcome=Outcome.PASSED,
                      state=ExecutionState.COMPLETED, created_at=now,
                      started_at=now, finished_at=now, created_by="tester")
        db.session.add(e); db.session.flush()
        db.session.add_all([
            TestResult(execution_id=e.id, case_name="passing", status=CaseStatus.PASSED),
            TestResult(execution_id=e.id, case_name="failing", status=CaseStatus.FAILED),
        ])
        db.session.commit()
    login_as("admin")
    resp = client.get("/reports?report_type=trends")
    body = resp.data.decode()
    assert resp.status_code == 200
    assert "Pass-rate and duration trends" in body
    assert "data-plotly-fig" in body
    assert "plotly.min.js" in body
    import html
    import re
    match = re.search(r'data-plotly-fig="([^"]+)"', body)
    assert match and json.loads(html.unescape(match.group(1)))["data"]
    assert "50.0" in body  # one passed of two non-skipped cases
    csv_resp = client.get("/reports?report_type=trends&format=csv")
    text = csv_resp.data.decode()
    assert csv_resp.status_code == 200
    assert "day,logical_runs,passed_runs" in text
    assert ",1,1,0" in text
    assert "50.0" in text
    assert ",UTC," in text


def _terminal(project, outcome, when, attempt=1, retry_of="", role="",
              parent_id=None):
    e = Execution(project_id=project.id, outcome=outcome,
                  state=ExecutionState.COMPLETED, created_at=when,
                  started_at=when - timedelta(seconds=10), finished_at=when,
                  role=role, parent_id=parent_id)
    e.snapshot_json = json.dumps({"attempt": attempt, "retry_of": retry_of})
    db.session.add(e); db.session.flush()
    return e


def test_trend_report_counts_retry_chain_once_by_final_outcome(app):
    from testorchestrator.reporting.queries import trend_report
    with app.app_context():
        p = Project(name="RetryTrend")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        head = _terminal(p, Outcome.FAILED, now - timedelta(hours=2))
        retry = _terminal(p, Outcome.PASSED, now, attempt=2, retry_of=head.id)
        db.session.add(TestResult(execution_id=head.id, case_name="case",
                                  status=CaseStatus.FAILED))
        db.session.add(TestResult(execution_id=retry.id, case_name="case",
                                  status=CaseStatus.PASSED))
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        report = trend_report(user, {"days": "30"})
        assert report["total"] == 1
        row = report["rows"][0]
        assert row["logical_runs"] == 1
        assert row["passed_runs"] == 1 and row["failed_runs"] == 0
        assert row["case_passed"] == 1 and row["case_failed"] == 0
        assert row["case_pass_rate"] == 100.0
        assert trend_report(user, {"days": "30", "outcome": "failed"})["total"] == 0
        assert trend_report(user, {"days": "30", "outcome": "passed"})["total"] == 1


def test_trend_report_resolves_retry_when_head_finished_before_window(app):
    from testorchestrator.reporting.queries import trend_report
    with app.app_context():
        p = Project(name="OldHeadTrend")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        head = _terminal(p, Outcome.FAILED, now - timedelta(days=40))
        retry = _terminal(p, Outcome.PASSED, now, attempt=2, retry_of=head.id)
        db.session.add(TestResult(execution_id=retry.id, case_name="case",
                                  status=CaseStatus.PASSED))
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        report = trend_report(user, {"days": "30"})
        assert report["total"] == 1
        assert report["rows"][0]["passed_runs"] == 1
        assert report["rows"][0]["case_pass_rate"] == 100.0


def test_trend_report_includes_partitioned_unit_results_once(app):
    from testorchestrator.reporting.queries import trend_report
    with app.app_context():
        p = Project(name="PartitionTrend")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        parent = _terminal(p, Outcome.PASSED, now, role="parent")
        u1 = _terminal(p, Outcome.PASSED, now, role="unit", parent_id=parent.id)
        u2 = _terminal(p, Outcome.PASSED, now, role="unit", parent_id=parent.id)
        db.session.add(TestResult(execution_id=u1.id, case_name="ok",
                                  status=CaseStatus.PASSED))
        db.session.add(TestResult(execution_id=u2.id, case_name="bad",
                                  status=CaseStatus.FAILED))
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        report = trend_report(user, {"days": "30"})
        assert report["total"] == 1       # units never become logical runs
        row = report["rows"][0]
        assert row["logical_runs"] == 1
        assert row["case_passed"] == 1 and row["case_failed"] == 1
        assert row["case_pass_rate"] == 50.0


def test_trend_report_project_scoping_is_enforced(app, client, login_as):
    import csv
    import io
    with app.app_context():
        visible = Project(name="TrendVisible")
        hidden = Project(name="TrendHidden")
        db.session.add_all([visible, hidden]); db.session.flush()
        now = datetime.now(timezone.utc)
        _terminal(visible, Outcome.PASSED, now)
        _terminal(hidden, Outcome.FAILED, now)
        po = User.query.filter_by(username="po").one()
        po.set_assigned_projects([visible.id])
        db.session.commit()
    login_as("po")
    resp = client.get("/reports?report_type=trends&format=csv")
    rows = list(csv.DictReader(io.StringIO(resp.data.decode())))
    assert len(rows) == 1
    assert rows[0]["logical_runs"] == "1"
    assert rows[0]["passed_runs"] == "1"
    assert rows[0]["failed_runs"] == "0"


def test_trend_report_buckets_days_in_viewer_timezone(app):
    from testorchestrator import usertz
    from testorchestrator.reporting.queries import trend_report
    with app.app_context():
        p = Project(name="ZoneTrend")
        db.session.add(p); db.session.flush()
        finish = (datetime.now(timezone.utc).replace(hour=0, minute=0,
                                                     second=0, microsecond=0)
                  - timedelta(minutes=30))
        _terminal(p, Outcome.PASSED, finish)
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        zone = usertz.coerce_zone("Europe/Budapest")
        report = trend_report(user, {"days": "30"}, tz=zone)
        assert report["timezone"] == "Europe/Budapest"
        assert report["rows"][0]["day"] == finish.astimezone(zone).date().isoformat()
        assert report["rows"][0]["day"] != finish.date().isoformat()


def test_logical_outcome_trend_serializes_execution_outcome_categories():
    from testorchestrator.charts import logical_outcome_trend
    fig = json.loads(logical_outcome_trend([
        {"day": "2026-01-01", "passed": 1, "failed": 2,
         "incomplete": 3, "none": 4}]))
    assert [t["name"] for t in fig["data"]] == [
        "passed", "failed", "incomplete", "no outcome"]
    assert fig["layout"]["yaxis"]["title"] == "Logical runs"


def test_execution_summary_period_window_excludes_old_rows(app):
    from testorchestrator.reporting.queries import execution_summary
    with app.app_context():
        p = Project(name="WindowSummary")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        db.session.add(Execution(project_id=p.id, created_at=now,
                                 outcome=Outcome.PASSED))
        db.session.add(Execution(project_id=p.id,
                                 created_at=now - timedelta(days=40),
                                 outcome=Outcome.PASSED))
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        assert execution_summary(user, {"days": "30"})["total"] == 1


def test_execution_summary_avg_duration_covers_all_matching_rows(app, monkeypatch):
    from testorchestrator.reporting import queries
    monkeypatch.setattr(queries, "MAX_REPORT_ROWS", 1)
    with app.app_context():
        p = Project(name="DurationSummary")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        for minutes, seconds in ((3, 10), (2, 30)):
            finished = now - timedelta(minutes=minutes)
            db.session.add(Execution(
                project_id=p.id, outcome=Outcome.PASSED,
                state=ExecutionState.COMPLETED,
                created_at=finished - timedelta(seconds=seconds + 5),
                started_at=finished - timedelta(seconds=seconds),
                finished_at=finished))
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        report = queries.execution_summary(user, {"days": "30"})
        assert report["total"] == 2
        assert len(report["rows"]) == 1
        assert report["avg_duration_s"] == 20.0


def test_trend_report_truncation_is_disclosed_in_preview_data_and_csv(app, monkeypatch):
    import csv
    import io
    from testorchestrator.reporting import queries
    monkeypatch.setattr(queries, "MAX_REPORT_ROWS", 1)
    with app.app_context():
        p = Project(name="TruncatedTrend")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        for i in range(3):
            _terminal(p, Outcome.PASSED, now - timedelta(minutes=i))
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        report = queries.trend_report(user, {"days": "30"})
        assert report["total"] == 3
        assert report["truncated"] is True
        rows = list(csv.DictReader(io.StringIO(queries.trend_csv(report))))
        assert rows[0]["total_logical_runs"] == "3"
        assert rows[0]["truncated"] == "true"
        assert rows[0]["max_rows"] == "1"


def test_trend_report_does_not_nplus1_results(app):
    from sqlalchemy import event
    from testorchestrator.reporting.queries import trend_report
    with app.app_context():
        p = Project(name="NplusOne")
        db.session.add(p); db.session.flush()
        now = datetime.now(timezone.utc)
        for i in range(4):
            e = Execution(project_id=p.id, outcome=Outcome.PASSED,
                          state=ExecutionState.COMPLETED, created_at=now,
                          started_at=now, finished_at=now)
            db.session.add(e); db.session.flush()
            db.session.add(TestResult(execution_id=e.id, case_name=f"c{i}",
                                      status=CaseStatus.PASSED))
        db.session.commit()
        user = User.query.filter_by(username="admin").one()
        queries = []
        engine = db.session.get_bind()
        def count(*a, **k): queries.append(1)
        event.listen(engine, "before_cursor_execute", count)
        try:
            report = trend_report(user, {"days": "30"})
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert report["total"] == 4
        # project scope + execution rows + one batched results query; never one per run
        assert len(queries) <= 4, queries


def test_reports_invalid_days_falls_back_instead_of_500(app, client, login_as):
    login_as("admin")
    assert client.get("/reports?days=not-a-number").status_code == 200
    assert client.get("/reports?report_type=trends&days=not-a-number").status_code == 200
