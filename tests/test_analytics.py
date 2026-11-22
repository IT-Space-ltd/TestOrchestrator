"""Advanced-analytics aggregation — fixture-verified calculations,
membership scoping, endpoint auth, and empty/sparse datasets
(docs/analytics-counting.md)."""

import json
from datetime import timedelta

from testorchestrator import analytics
from testorchestrator.extensions import db
from testorchestrator.execution import (CaseStatus, Execution,
                                        ExecutionState, Outcome,
                                        Project, Suite, TestResult,
                                        utcnow)
from testorchestrator.models import User
from tests.conftest import login


def _seed(name="P1"):
    p = Project(name=name, description="d")
    db.session.add(p)
    db.session.flush()
    s = Suite(project_id=p.id, name=f"{name}-suite")
    db.session.add(s)
    db.session.flush()
    return p, s


def _ex(p, s, state, outcome, days_ago=0, wait_s=60, run_s=120,
        attempt=1, retry_of="", role="", env=None):
    e = Execution(project_id=p.id, suite_id=s.id if s else None,
                  state=state, outcome=outcome, created_by="t",
                  role=role, environment=env)
    e.snapshot_json = json.dumps(
        {"suite_name": s.name if s else "",
         "attempt": attempt, "retry_of": retry_of})
    e.created_at = utcnow() - timedelta(days=days_ago,
                                       seconds=wait_s + run_s)
    e.started_at = e.created_at + timedelta(seconds=wait_s)
    e.finished_at = e.started_at + timedelta(seconds=run_s)
    db.session.add(e)
    db.session.flush()
    return e


def _result(ex, name, status, ref="", duration=1.0):
    r = TestResult(execution_id=ex.id, case_name=name,
                   case_ref=ref or name, status=status,
                   duration_s=duration)
    db.session.add(r)
    return r


class _AllProjects:
    def project_allowed(self, _):
        return True


class _NoProjects:
    def project_allowed(self, _):
        return False


# ----------------------------------------------------------- resolution


class TestLogicalRunResolution:
    def test_retry_chain_resolves_to_final_attempt(self, app):
        with app.app_context():
            p, s = _seed()
            head = _ex(p, s, ExecutionState.COMPLETED, Outcome.FAILED,
                       attempt=1)
            retry = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                        attempt=2, retry_of=head.id)
            db.session.commit()
            runs = analytics.resolve_logical_runs(
                Execution.query.all())
            assert len(runs) == 1
            assert runs[0]["head"].id == head.id
            assert runs[0]["final"].id == retry.id
            assert runs[0]["retries"] == 1

    def test_units_never_count_as_logical_runs(self, app):
        with app.app_context():
            p, s = _seed()
            parent = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                         role="parent")
            u1 = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                     role="unit")
            u1.parent_id = parent.id
            u2 = _ex(p, s, ExecutionState.COMPLETED, Outcome.FAILED,
                     role="unit")
            u2.parent_id = parent.id
            db.session.commit()
            runs = analytics.resolve_logical_runs(
                Execution.query.all())
            assert len(runs) == 1
            assert runs[0]["head"].id == parent.id

    def test_inflight_chain_resolves_to_last_terminal(self, app):
        with app.app_context():
            p, s = _seed()
            head = _ex(p, s, ExecutionState.COMPLETED, Outcome.FAILED)
            r2 = _ex(p, s, ExecutionState.RUNNING, Outcome.NONE,
                     attempt=2, retry_of=head.id)
            r2.finished_at = None
            db.session.commit()
            runs = analytics.resolve_logical_runs(
                Execution.query.all())
            assert len(runs) == 1
            assert runs[0]["final"].id == head.id


# ------------------------------------------------------------- main agg


class TestMainAnalytics:
    def test_project_outcome_comparison_final_outcome(self, app):
        with app.app_context():
            p1, s1 = _seed("A")
            p2, s2 = _seed("B")
            _ex(p1, s1, ExecutionState.COMPLETED, Outcome.PASSED)
            head = _ex(p1, s1, ExecutionState.COMPLETED,
                       Outcome.FAILED)
            _ex(p1, s1, ExecutionState.COMPLETED, Outcome.PASSED,
                attempt=2, retry_of=head.id)   # chain → 1 passed run
            _ex(p2, s2, ExecutionState.FAILED, Outcome.NONE)
            db.session.commit()
            d = analytics.main_analytics(_AllProjects(), 30)
            rows = {r["project"]: r for r in d["project_outcomes"]}
            assert rows["A"]["passed"] == 2
            assert rows["A"]["failed"] == 0   # resolved, not counted
            assert rows["B"]["none"] == 1

    def test_first_vs_final_same_cohort(self, app):
        with app.app_context():
            p, s = _seed()
            _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED)
            head = _ex(p, s, ExecutionState.COMPLETED, Outcome.FAILED)
            _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                attempt=2, retry_of=head.id)
            db.session.commit()
            d = analytics.main_analytics(_AllProjects(), 30)
            assert len(d["first_final"]) == 1
            row = d["first_final"][0]
            assert row["total"] == 2
            assert row["first_passed"] == 1   # one head passed
            assert row["final_passed"] == 2   # both resolve passed
            assert row["retried"] == 1

    def test_queue_wait_median_and_p95(self, app):
        with app.app_context():
            p, s = _seed()
            _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                wait_s=60)
            _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                wait_s=120)
            _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                wait_s=300)
            db.session.commit()
            d = analytics.main_analytics(_AllProjects(), 30)
            assert len(d["queue_wait"]) == 1
            row = d["queue_wait"][0]
            assert row["n"] == 3
            assert row["median"] == 120.0
            assert row["p95"] == 300.0
            assert d["turnaround"][0]["median"] == 240.0

    def test_membership_empty_means_empty_not_all(self, app):
        with app.app_context():
            p, s = _seed()
            _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED)
            db.session.commit()
            d = analytics.main_analytics(_NoProjects(), 30)
            assert d["project_outcomes"] == []
            assert d["first_final"] == []
            assert d["queue_wait"] == []


# ---------------------------------------------------------- project agg


class TestProjectAnalytics:
    def test_history_cells_case_by_run(self, app):
        with app.app_context():
            p, s = _seed()
            e1 = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                     days_ago=1)
            e2 = _ex(p, s, ExecutionState.COMPLETED, Outcome.FAILED)
            _result(e1, "CaseA", CaseStatus.PASSED)
            _result(e2, "CaseA", CaseStatus.FAILED)
            _result(e2, "CaseB", CaseStatus.PASSED)
            db.session.commit()
            d = analytics.project_analytics(p.id, 30, suite=s.id)
            h = d["history"]
            assert len(h["runs"]) == 2
            assert set(h["cases"]) == {"CaseA", "CaseB"}
            assert h["cells"]["CaseA|" + e1.id]["status"] == "passed"
            assert h["cells"]["CaseA|" + e2.id]["status"] == "failed"
            assert "CaseB|" + e1.id not in h["cells"]  # absent, not skipped

    def test_history_case_prefix_without_suite_filter(self, app):
        with app.app_context():
            p, s = _seed()
            e = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED)
            _result(e, "CaseA", CaseStatus.PASSED)
            db.session.commit()
            d = analytics.project_analytics(p.id, 30, suite="")
            assert d["history"]["cases"] == [s.name + ":CaseA"]
            d2 = analytics.project_analytics(p.id, 30, suite=s.id)
            assert d2["history"]["cases"] == ["CaseA"]

    def test_env_comparison_metrics(self, app):
        with app.app_context():
            p, s = _seed()
            e1 = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                     env="linux", run_s=100)
            e2 = _ex(p, s, ExecutionState.COMPLETED, Outcome.FAILED,
                     env="windows", run_s=300)
            _result(e1, "A", CaseStatus.PASSED)
            _result(e2, "A", CaseStatus.FAILED)
            _result(e2, "B", CaseStatus.SKIPPED)   # excluded denominator
            db.session.commit()
            d = analytics.project_analytics(p.id, 30)
            cells = {(c["suite"], c["env"]): c
                     for c in d["env_cells"]}
            lin = cells[(s.name, "linux")]
            win = cells[(s.name, "windows")]
            assert lin["run_pass_rate"] == 100.0
            assert win["run_pass_rate"] == 0.0
            assert lin["case_pass_rate"] == 100.0
            assert win["case_pass_rate"] == 0.0  # skipped excluded
            assert lin["median_duration"] == 100.0
            assert win["median_duration"] == 300.0
            assert "(unset)" not in d["env_envs"]

    def test_unset_environment_labeled(self, app):
        with app.app_context():
            p, s = _seed()
            e = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED)
            _result(e, "A", CaseStatus.PASSED)
            db.session.commit()
            d = analytics.project_analytics(p.id, 30)
            assert "(unset)" in d["env_envs"]

    def test_suite_duration_logical_runs(self, app):
        with app.app_context():
            p, s = _seed()
            parent = _ex(p, s, ExecutionState.COMPLETED,
                         Outcome.PASSED, role="parent", run_s=400)
            u = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED,
                    role="unit", run_s=100)
            u.parent_id = parent.id
            db.session.commit()
            d = analytics.project_analytics(p.id, 30)
            assert len(d["suite_durations"]) == 1
            assert d["suite_durations"][0]["durations"] == [400.0]
            # the unit shard is not a second sample
            assert len(d["suite_durations"][0]["durations"]) == 1

    def test_empty_dataset(self, app):
        with app.app_context():
            p, s = _seed()
            db.session.commit()
            d = analytics.project_analytics(p.id, 30)
            assert d["history"]["cases"] == []
            assert d["suite_durations"] == []
            assert d["env_cells"] == []
            m = analytics.main_analytics(_AllProjects(), 30)
            assert m["project_outcomes"] == []


# ------------------------------------------------------------- endpoints


class TestAnalyticsEndpoints:
    def test_main_analytics_json_and_csv(self, app, client):
        with app.app_context():
            p, s = _seed()
            _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED)
            db.session.commit()
        login(client, "admin")
        r = client.get("/dashboard/analytics")
        assert r.status_code == 200
        payload = r.get_json()
        assert payload["charts"]["comparison"]["data"]
        assert payload["tables"]["project_outcomes"][0]["passed"] == 1
        r = client.get("/dashboard/analytics?format=csv"
                       "&chart=first_final")
        assert r.status_code == 200
        assert "text/csv" in r.content_type
        assert b"first_passed" in r.data
        r = client.get("/dashboard/analytics?format=csv&chart=bogus")
        assert r.status_code == 404

    def test_project_analytics_scoped_by_membership(self, app, client):
        with app.app_context():
            p, s = _seed()
            e = _ex(p, s, ExecutionState.COMPLETED, Outcome.PASSED)
            _result(e, "A", CaseStatus.PASSED)
            other = Project(name="Other")
            db.session.add(other)
            tester = User.query.filter_by(username="tester").first()
            tester.set_assigned_projects([p.id])
            pid, oid = p.id, other.id
            db.session.commit()
        login(client, "tester")
        r = client.get(f"/projects/{pid}/analytics")
        assert r.status_code == 200
        assert r.get_json()["charts"]["history"]["data"]
        # a project the tester is NOT a member of → not authorized
        r = client.get(f"/projects/{oid}/analytics")
        assert r.status_code in (403, 404)

    def test_analytics_requires_login(self, app, client):
        r = client.get("/dashboard/analytics")
        assert r.status_code in (302, 401, 403)
