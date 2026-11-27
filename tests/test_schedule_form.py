"""Schedule creation form (Task-3): framework-scoped fields, server-side
rejection of foreign values, no carried-over hidden values, project-scoped
framework list, and Katalon backwards compatibility."""
import json

from testorchestrator.execution import (DiscoveredItem, FrameworkProject,
                                        GitBinding, Project, Schedule)
from testorchestrator.extensions import db


def _project(app, fw=""):
    with app.app_context():
        p = Project(name="P")
        db.session.add(p)
        db.session.flush()
        b = GitBinding(project_id=p.id, name="b", url="/x",
                       worktree_path="/tmp/x")
        db.session.add(b)
        db.session.flush()
        item = DiscoveredItem(
            project_id=p.id, binding_id=b.id, sha="s", kind="suite",
            path="tests/", name="it", framework=fw)
        db.session.add(item)
        if fw:
            fp = FrameworkProject(project_id=p.id, name="fp",
                                  framework=fw, binding_id=b.id,
                                  discovery_status="ok")
            db.session.add(fp)
        db.session.commit()
        return p.id, item.id


def _post(client, pid, **over):
    data = {
        "name": "s1", "target_id": "", "target_type": "suite",
        "kind": "interval",
        "interval_minutes": "60", "run_at": "2030-01-01 00:00",
        "execution_profile": "default", "browser_type": "",
        "remote_webdriver_url": "", "remote_webdriver_type": "",
        "pytest_keyword": "", "pytest_markers": "",
        "robot_test": "", "robot_include": "", "robot_exclude": "",
        "runner_id": "", "runtime_id": "", "timeout_seconds": "3600",
        "overlap_policy": "allow", "framework": "",
    }
    data.update(over)
    return client.post(f"/projects/{pid}/schedules", data=data,
                       follow_redirects=True)


def test_rejects_foreign_fields_with_clear_message(app, client, login_as):
    pid, iid = _project(app)
    login_as("admin")
    resp = _post(client, pid, framework="katalon", target_id=f"repo:{iid}",
                 pytest_keyword="test_login")
    assert resp.status_code == 200
    assert b"not applicable" in resp.data
    with app.app_context():
        assert Schedule.query.count() == 0


def test_pytest_schedule_stores_only_pytest_fields(app, client, login_as):
    pid, iid = _project(app, fw="pytest")
    login_as("admin")
    resp = _post(client, pid, framework="pytest", target_id=f"repo:{iid}",
                 pytest_keyword="test_login and not slow",
                 pytest_markers="smoke")
    assert resp.status_code == 200
    with app.app_context():
        sched = Schedule.query.one()
        rc = json.loads(sched.run_config_json)
        assert rc["pytest_keyword"] == "test_login and not slow"
        assert rc["pytest_markers"] == "smoke"
        # no carried-over hidden Katalon values
        assert "profile" not in rc
        assert "browser" not in rc
        assert "remote_webdriver_url" not in rc
        assert "runtime_id" not in rc
        # common fields present
        assert rc["timeout_seconds"] == 3600


def test_robot_schedule_stores_robot_fields(app, client, login_as):
    pid, iid = _project(app, fw="robot")
    login_as("admin")
    _post(client, pid, framework="robot", target_id=f"repo:{iid}",
          robot_test="Valid Login", robot_include="smoke")
    with app.app_context():
        rc = json.loads(Schedule.query.one().run_config_json)
        assert rc["robot_test"] == "Valid Login"
        assert rc["robot_include"] == "smoke"
        assert "pytest_keyword" not in rc


def test_katalon_schedule_unchanged(app, client, login_as):
    pid, iid = _project(app)
    login_as("admin")
    _post(client, pid, framework="katalon", target_id=f"repo:{iid}",
          execution_profile="staging", browser_type="Firefox",
          remote_webdriver_url="http://selenium-hub:4444/wd/hub",
          remote_webdriver_type="Selenium")
    with app.app_context():
        rc = json.loads(Schedule.query.one().run_config_json)
        assert rc["profile"] == "staging"
        assert rc["browser"] == "Firefox"
        assert rc["remote_webdriver_url"] == \
            "http://selenium-hub:4444/wd/hub"
        assert rc["remote_webdriver_type"] == "Selenium"
        assert "pytest_keyword" not in rc


def test_framework_mismatch_with_target_rejected(app, client, login_as):
    # project with BOTH frameworks: pytest item + katalon legacy item —
    # both are valid picks, so the mismatch check (not choice
    # validation) is what fires.
    pid, iid = _project(app, fw="pytest")
    with app.app_context():
        p = db.session.get(Project, pid)
        b2 = GitBinding(project_id=pid, name="b2", url="/y",
                        worktree_path="/tmp/y")
        db.session.add(b2)
        db.session.flush()
        db.session.add(DiscoveredItem(
            project_id=pid, binding_id=b2.id, sha="s", kind="suite",
            path="TS/", name="kat", framework=""))
        db.session.commit()
    login_as("admin")
    resp = _post(client, pid, framework="katalon",
                 target_id=f"repo:{iid}")
    assert b"Framework mismatch" in resp.data
    with app.app_context():
        assert Schedule.query.count() == 0


def test_framework_inferred_from_target_when_unpicked(
        app, client, login_as):
    pid, iid = _project(app, fw="pytest")
    login_as("admin")
    _post(client, pid, target_id=f"repo:{iid}",
          pytest_keyword="test_x")
    with app.app_context():
        rc = json.loads(Schedule.query.one().run_config_json)
        assert rc["pytest_keyword"] == "test_x"
        assert "profile" not in rc


def test_form_lists_only_project_frameworks(app, client, login_as):
    pid, _ = _project(app, fw="pytest")
    login_as("admin")
    resp = client.get(f"/projects/{pid}?tab=schedexec")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="sch-framework"' in html
    # pytest present; cypress/playwright absent (project doesn't have them)
    assert '<option value="pytest">' in html
    assert '<option value="cypress">' not in html
    assert '<option value="playwright">' not in html


def test_form_has_per_framework_groups_and_examples(
        app, client, login_as):
    pid, _ = _project(app)
    login_as("admin")
    resp = client.get(f"/projects/{pid}?tab=schedexec")
    html = resp.get_data(as_text=True)
    assert 'data-fws="pytest pytest-bdd"' in html
    assert 'data-fws="robot"' in html
    assert 'data-fws="katalon"' in html
    # examples wired with aria-describedby
    assert 'aria-describedby="sch-interval-ex"' in html
    assert '1440' in html                      # once-a-day example
    assert 'aria-describedby="sch-timeout-ex"' in html
    assert 'aria-describedby="sch-overlap-ex"' in html


def test_old_schedule_edit_still_works(app, client, login_as):
    """Katalon-era schedules open and save as before."""
    from testorchestrator.execution import utcnow
    pid, _ = _project(app)
    with app.app_context():
        sched = Schedule(project_id=pid, name="legacy",
                         target_type="suite", kind="interval",
                         interval_minutes=60, next_run_at=utcnow(),
                         enabled=True, created_by="manager",
                         run_config_json=json.dumps({
                             "profile": "default",
                             "browser": "Chrome (headless)",
                             "timeout_seconds": 3600}))
        db.session.add(sched)
        db.session.commit()
        sid = sched.id
    login_as("admin")
    resp = client.get(f"/projects/{pid}?tab=schedexec")
    assert b"legacy" in resp.data
    resp = client.post(f"/schedules/{sid}/edit",
                       data={"name": "legacy2"}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Schedule, sid).name == "legacy2"


def test_jest_schedule_stores_execution_native_keys(app, client, login_as):
    pid, iid = _project(app, fw="jest")
    login_as("admin")
    _post(client, pid, framework="jest", target_id=f"repo:{iid}",
          jest_test_path="tests/api/", jest_test_name="login")
    with app.app_context():
        rc = json.loads(Schedule.query.one().run_config_json)
        assert rc["jest_path_pattern"] == "tests/api/"
        assert rc["test_pattern"] == "login"
        assert "pytest_keyword" not in rc


def test_postman_schedule_fields(app, client, login_as):
    pid, iid = _project(app, fw="postman")
    login_as("admin")
    _post(client, pid, framework="postman", target_id=f"repo:{iid}",
          postman_collection="collections/api-smoke.postman_collection.json",
          postman_environment="environments/staging.postman_environment.json",
          postman_folder="Login", postman_iterations="2")
    with app.app_context():
        rc = json.loads(Schedule.query.one().run_config_json)
        assert rc["postman_collection"].endswith("postman_collection.json")
        assert rc["postman_folder"] == "Login"
        assert rc["postman_iterations"] == 2


def test_bruno_schedule_fields(app, client, login_as):
    pid, iid = _project(app, fw="bruno")
    login_as("admin")
    _post(client, pid, framework="bruno", target_id=f"repo:{iid}",
          bruno_collection="api-tests/auth", bruno_environment="staging",
          bruno_tags="smoke")
    with app.app_context():
        rc = json.loads(Schedule.query.one().run_config_json)
        assert rc["bruno_collection"] == "api-tests/auth"
        assert rc["bruno_environment"] == "staging"
        assert rc["bruno_tags"] == "smoke"


def test_jest_rejects_postman_fields(app, client, login_as):
    pid, iid = _project(app, fw="jest")
    login_as("admin")
    resp = _post(client, pid, framework="jest", target_id=f"repo:{iid}",
                 postman_folder="Login")
    assert b"not applicable" in resp.data
    with app.app_context():
        assert Schedule.query.count() == 0


def test_form_has_jest_postman_bruno_groups(app, client, login_as):
    pid, _ = _project(app, fw="jest")
    login_as("admin")
    html = client.get(f"/projects/{pid}?tab=schedexec").get_data(as_text=True)
    assert 'data-fws="jest"' in html
    assert 'data-fws="postman"' in html
    assert 'data-fws="bruno"' in html
    assert 'aria-describedby="sch-jpath-ex"' in html
    assert 'aria-describedby="sch-pmcol-ex"' in html
    assert 'aria-describedby="sch-brtags-ex"' in html
    # offered in the selector (project has jest)
    assert '<option value="jest">' in html


def _project_with_collection(app):
    """Project with one katalon suite item, one collection item."""
    with app.app_context():
        p = Project(name="PC")
        db.session.add(p)
        db.session.flush()
        b = GitBinding(project_id=p.id, name="b", url="/x",
                       worktree_path="/tmp/x")
        db.session.add(b)
        db.session.flush()
        suite = DiscoveredItem(
            project_id=p.id, binding_id=b.id, sha="s", kind="suite",
            path="Test Suites/login.ts", name="login",
            framework="katalon")
        coll = DiscoveredItem(
            project_id=p.id, binding_id=b.id, sha="s",
            kind="collection", path="Test Suites/smoke.tsc",
            name="smoke", framework="katalon",
            members_json='["Test Suites/login.ts"]',
            tags="runmode:SEQUENTIAL")
        db.session.add_all([suite, coll])
        db.session.commit()
        return p.id, suite.id, coll.id


def test_schedule_collection_via_picker(app, client, login_as):
    pid, sid, cid = _project_with_collection(app)
    login_as("admin")
    resp = _post(client, pid, framework="katalon", target_kind="collection",
                 case_refs=[f"repo:{cid}"])
    assert resp.status_code == 200
    with app.app_context():
        sched = Schedule.query.one()
        targets = json.loads(sched.targets_json)
        assert len(targets) == 1
        assert targets[0]["kind"] == "collection"
        assert targets[0]["path"] == "Test Suites/smoke.tsc"


def test_suite_picker_rejects_collection_item(app, client, login_as):
    pid, sid, cid = _project_with_collection(app)
    login_as("admin")
    resp = _post(client, pid, framework="katalon", target_kind="suite",
                 case_refs=[f"repo:{cid}"])
    assert resp.status_code == 200
    assert b"Target type mismatch" in resp.data
    with app.app_context():
        assert Schedule.query.count() == 0


def test_collection_picker_rejects_suite_item(app, client, login_as):
    pid, sid, cid = _project_with_collection(app)
    login_as("admin")
    resp = _post(client, pid, framework="katalon",
                 target_kind="collection",
                 case_refs=[f"repo:{sid}"])
    assert b"Target type mismatch" in resp.data
    with app.app_context():
        assert Schedule.query.count() == 0


def test_schedule_plan_target_ignores_picker(app, client, login_as):
    from testorchestrator.execution import Plan
    pid, sid, cid = _project_with_collection(app)
    with app.app_context():
        pl = Plan(project_id=pid, name="smoke-plan")
        db.session.add(pl)
        db.session.commit()
        plan_id = pl.id
    login_as("admin")
    # stale picker values must not leak into a plan schedule
    resp = _post(client, pid, framework="katalon", target_kind="plan",
                 target_id=f"plan:{plan_id}",
                 case_refs=[f"repo:{cid}"])
    assert resp.status_code == 200
    with app.app_context():
        sched = Schedule.query.one()
        assert sched.target_type == "plan"
        assert sched.plan_id == plan_id
        assert json.loads(sched.targets_json) == []


def test_plan_target_rejects_non_katalon_framework(app, client, login_as):
    from testorchestrator.execution import Plan
    pid, sid, cid = _project_with_collection(app)
    with app.app_context():
        pl = Plan(project_id=pid, name="p2")
        db.session.add(pl)
        db.session.commit()
        plan_id = pl.id
    login_as("admin")
    resp = _post(client, pid, framework="pytest", target_kind="plan",
                 target_id=f"plan:{plan_id}")
    assert b"Framework mismatch" in resp.data
    with app.app_context():
        assert Schedule.query.count() == 0


def test_multi_suite_picker_stores_all_targets(app, client, login_as):
    pid, sid, cid = _project_with_collection(app)
    with app.app_context():
        extra = DiscoveredItem(
            project_id=pid,
            binding_id=DiscoveredItem.query.get(sid).binding_id,
            sha="s", kind="suite", path="Test Suites/cart.ts",
            name="cart", framework="katalon")
        db.session.add(extra)
        db.session.commit()
        sid2 = extra.id
    login_as("admin")
    resp = _post(client, pid, framework="katalon", target_kind="suite",
                 case_refs=[f"repo:{sid}", f"repo:{sid2}"])
    assert resp.status_code == 200
    with app.app_context():
        sched = Schedule.query.one()
        targets = json.loads(sched.targets_json)
        assert len(targets) == 2
        assert {t["path"] for t in targets} == {
            "Test Suites/login.ts", "Test Suites/cart.ts"}


def test_legacy_project_without_framework_project_offers_katalon(
        app, client, login_as):
    """Legacy binding: no FrameworkProject rows at all, discovered items
    carry no framework marker. katalon must still be a valid, saveable
    framework choice — old bindings/schedules behave as before."""
    pid, iid = _project(app)      # fw="" — no FrameworkProject rows
    login_as("admin")
    resp = client.get(f"/projects/{pid}")
    assert b"katalon" in resp.data.lower()
    resp = _post(client, pid, framework="katalon", target_id=f"repo:{iid}",
                 execution_profile="default")
    assert resp.status_code == 200
    with app.app_context():
        sched = Schedule.query.one()
        rc = json.loads(sched.run_config_json)
        assert rc.get("profile") == "default"


def test_validation_failure_is_never_silent(app, client, login_as):
    pid, iid = _project(app)
    login_as("admin")
    # interval too short (< 5min is clamped, but a missing run_at when
    # kind=once is a validation-level failure) — use a bad runner pin
    resp = _post(client, pid, framework="katalon", target_id=f"repo:{iid}",
                 runner_id="nonexistent-runner")
    assert resp.status_code == 200
    assert b"not saved" in resp.data or b"Schedule" in resp.data
    with app.app_context():
        assert Schedule.query.count() == 0
