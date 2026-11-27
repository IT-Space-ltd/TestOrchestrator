"""2.7.0 framework-aware discovery — adapter behavior, persistence,
dispatch gates, and migration correctness (fixture trees only;
discovery never executes repository code)."""

import json
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa

from testorchestrator import dispatch, gitsync
from testorchestrator.discovery import discover, fingerprint
from testorchestrator.discovery.base import glob_match
from testorchestrator.extensions import db
from testorchestrator.execution import (DiscoveredItem, FrameworkProject,
                                        GitBinding, Project, Runner,
                                        RuntimeConnection)

MIGRATIONS = str(Path(__file__).resolve().parent.parent / "migrations")


# ---------- fixtures ----------

def _write(root: Path, files: dict):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def _fp(fw, **kw):
    fp = FrameworkProject(name="t", framework=fw, binding_id="",
                          project_id="")
    fp.project_root = kw.get("project_root", "")
    fp.workdir = kw.get("workdir", "")
    fp.config_file = kw.get("config_file", "")
    fp.test_roots_json = json.dumps(kw.get("test_roots", []))
    fp.include_json = json.dumps(kw.get("include", []))
    fp.exclude_json = json.dumps(kw.get("exclude", []))
    fp.feature_roots_json = json.dumps(kw.get("feature_roots", []))
    fp.stepdef_roots_json = json.dumps(kw.get("stepdef_roots", []))
    return fp


class _B:
    def __init__(self, wt, sub=""):
        self.worktree_path = str(wt)
        self.subdirectory = sub


PYTREE = {
    "pytest.ini": "[pytest]\ntestpaths = tests\n"
                  "python_files = test_*.py\n",
    "tests/test_math.py": (
        "import pytest\n"
        "def test_add(): pass\n"
        "@pytest.mark.slow\n"
        "def test_slow(): pass\n"
        "@pytest.mark.parametrize('x', [1,2])\n"
        "def test_param(x): pass\n"
        "class TestGroup:\n"
        "    def test_in_class(self): pass\n"),
    "tests/conftest.py": "import pytest\n",
}

FEATURE = ("@auth\nFeature: Login\n"
           "  Scenario: valid login\n    Given a user\n"
           "  @smoke\n  Scenario Outline: bad passwords\n"
           "    Given a user\n    When I try <pw>\n"
           "    Examples:\n      | pw |\n      | 1 |\n")


# ---------- glob semantics ----------

def test_glob_doublestar_and_braces():
    assert glob_match("a/b/c/t.spec.ts", ["**/*.spec.ts"])
    assert glob_match("t.spec.ts", ["**/*.spec.ts"])
    assert glob_match("x.cy.ts", ["**/*.cy.{js,ts}"])
    assert glob_match("d/x.cy.ts", ["**/*.cy.{js,ts}"])
    assert not glob_match("x.py", ["**/*.cy.{js,ts}"])
    assert not glob_match("a/b.txt", ["a/**/*.py"])
    assert glob_match("a/b/c.py", ["a/**/*.py"])


def test_glob_minimatch_extglobs():
    # playwright's default testMatch — previously never matched
    pat = ["**/*.@(spec|test).?(c|m)[jt]s?(x)"]
    assert glob_match("pw.spec.js", pat)
    assert glob_match("tests/pw.spec.ts", pat)
    assert glob_match("x.test.mjs", pat)
    assert glob_match("x.spec.cts", pat)
    assert not glob_match("x.spec.py", pat)
    assert not glob_match("x.other.js", pat)
    # jest's default testMatch
    jp = ["**/__tests__/**/*.[jt]s?(x)",
          "**/?(*.)+(spec|test).[jt]s?(x)"]
    assert glob_match("smoke.test.js", jp)
    assert glob_match("src/x.test.tsx", jp)
    assert glob_match("__tests__/unit/a.js", jp)
    assert not glob_match("src/helper.js", jp)


def test_probe_scripts_emit_summarize_markers():
    """_summarize reads node/npx/<kind> markers — the per-adapter
    probe scripts must emit all three or readiness can never turn
    ready (regression: postman/bruno emitted engine markers under
    other names and could never pass)."""
    from testorchestrator.adapters import brunofw, postmanfw
    pm = postmanfw.probe_scripts()["probe.sh"]
    assert 'p "npx=' in pm and 'p "postman=' in pm and 'p "node=' in pm
    br = brunofw.probe_scripts()["probe.sh"]
    assert 'p "npx=' in br and 'p "bruno=' in br and 'p "node=' in br


# ---------- pytest adapter ----------

def test_pytest_ast_discovery(tmp_path):
    wt = _write(tmp_path, PYTREE)
    res = discover(_fp("pytest", test_roots=["tests"]), _B(wt))
    by_name = {i.name: i for i in res.items}
    assert by_name["test_add"].node_id == \
        "tests/test_math.py::test_add"
    assert by_name["test_add"].selectable
    assert by_name["test_in_class"].node_id == \
        "tests/test_math.py::TestGroup::test_in_class"
    # parametrized → candidate, needs native collection
    assert not by_name["test_param"].selectable
    assert res.needs_native
    # markers recorded
    assert "slow" in by_name["test_slow"].tags
    # conftest.py is support, not a test item
    assert "conftest" not in by_name
    # effective settings carry their source
    assert res.effective["python_files"]["source"] == "config"
    assert res.effective["config_file"]["value"] == "pytest.ini"


def test_pytest_missing_root_warns(tmp_path):
    wt = _write(tmp_path, PYTREE)
    res = discover(_fp("pytest", test_roots=["nope"]), _B(wt))
    assert not res.items
    assert any("not found" in w for w in res.warnings)


# ---------- behave adapter ----------

def test_behave_line_selectors(tmp_path):
    wt = _write(tmp_path, {
        "features/login.feature": FEATURE,
        "features/steps/steps.py":
            "from behave import given\n@given('a user')\ndef u(c): pass\n",
    })
    res = discover(_fp("behave", feature_roots=["features"],
                       stepdef_roots=["features/steps"]), _B(wt))
    scen = {i.name: i for i in res.items if i.kind == "scenario"}
    assert scen["valid login"].node_id == "features/login.feature:3"
    assert scen["valid login"].selectable
    assert scen["bad passwords"].node_id == "features/login.feature:6"
    assert res.needs_native          # outline expansion is native
    feat = [i for i in res.items if i.kind == "suite"]
    assert feat[0].node_id == "features/login.feature"


def test_behave_localized_keywords_warn(tmp_path):
    wt = _write(tmp_path, {
        "features/x.feature":
            "Fonctionnalité: X\n  Scénario: a\n    Soit b\n"})
    res = discover(_fp("behave", feature_roots=["features"]), _B(wt))
    assert any("localized" in w or "unrecognised" in w
               for w in res.warnings)


# ---------- pytest-bdd adapter ----------

def test_pytestbdd_binding_kinds(tmp_path):
    wt = _write(tmp_path, {
        "features/login.feature": FEATURE,
        "tests/test_bdd.py": (
            "from pytest_bdd import scenario, scenarios\n"
            "scenarios('../features')\n"
            "@scenario('../features/login.feature', 'valid login')\n"
            "def test_login(): pass\n"),
    })
    res = discover(_fp("pytest-bdd", feature_roots=["features"],
                       test_roots=["tests"]), _B(wt))
    scen = {i.name: i for i in res.items if i.kind == "scenario"}
    # explicit @scenario → exact pytest nodeid
    assert scen["valid login"].node_id == \
        "tests/test_bdd.py::test_login"
    assert scen["valid login"].selectable
    # wildcard scenarios() → bound but node ID needs native collect
    assert not scen["bad passwords"].selectable
    assert "scenarios()" in scen["bad passwords"].warnings
    assert res.needs_native


def test_pytestbdd_unbound_scenario_is_candidate(tmp_path):
    wt = _write(tmp_path, {
        "features/x.feature": "Feature: X\n  Scenario: a\n    Given b\n",
        "tests/test_nothing.py": "def test_x(): pass\n"})
    res = discover(_fp("pytest-bdd", feature_roots=["features"],
                       test_roots=["tests"]), _B(wt))
    scen = [i for i in res.items if i.kind == "scenario"]
    assert not scen[0].selectable
    assert "binding" in scen[0].warnings


def test_pytestbdd_unbound_feature_not_selectable(tmp_path):
    """ISS-026: pytest never collects a bare .feature positional, so a
    feature with no exact @scenario binding can never execute — the
    suite item is marked not selectable with the reason."""
    wt = _write(tmp_path, {
        "features/x.feature": "Feature: X\n  Scenario: a\n    Given b\n",
        "tests/test_nothing.py": "def test_x(): pass\n"})
    res = discover(_fp("pytest-bdd", feature_roots=["features"],
                       test_roots=["tests"]), _B(wt))
    suite = [i for i in res.items if i.kind == "suite"]
    assert len(suite) == 1
    assert not suite[0].selectable
    assert "no exact @scenario binding" in suite[0].warnings


def test_pytestbdd_bound_feature_stays_selectable(tmp_path):
    wt = _write(tmp_path, {
        "features/login.feature": FEATURE,
        "tests/test_bdd.py": (
            "from pytest_bdd import scenario\n"
            "@scenario('../features/login.feature', 'valid login')\n"
            "def test_login(): pass\n")})
    res = discover(_fp("pytest-bdd", feature_roots=["features"],
                       test_roots=["tests"]), _B(wt))
    suite = [i for i in res.items if i.kind == "suite"]
    assert suite[0].selectable


# ---------- robot adapter ----------

def test_robot_tests_tags_templates(tmp_path):
    wt = _write(tmp_path, {
        "suites/login.robot": (
            "*** Test Cases ***\n"
            "Valid Login\n    [Tags]    smoke\n"
            "    Given a user\n    When logged in\n"
            "Template Case\n    [Template]    My kw\n    a    b\n")})
    res = discover(_fp("robot", test_roots=["suites"]), _B(wt))
    tests = {i.name: i for i in res.items if i.kind == "test"}
    assert tests["Valid Login"].node_id == "Valid Login"
    assert "smoke" in tests["Valid Login"].tags
    assert "GWT-style" in tests["Valid Login"].tags
    assert "Template" in tests["Template Case"].warnings
    assert res.needs_native


# ---------- cypress / playwright adapters ----------

def test_cypress_literal_config_and_file_only(tmp_path):
    wt = _write(tmp_path, {
        "cypress.config.js":
            "module.exports = { e2e: { specPattern: "
            "'specs/**/*.cy.js' } }\n",
        "specs/login.cy.js": "describe('l', () => {})\n",
        "specs/helper.js": "// support — never a spec\n",
    })
    res = discover(_fp("cypress"), _B(wt))
    assert [i.path for i in res.items] == ["specs/login.cy.js"]
    assert res.items[0].granularity == "file"
    assert res.items[0].selectable
    assert res.effective["specPattern"]["source"] == "config"


def test_cypress_dynamic_config_unresolved(tmp_path):
    wt = _write(tmp_path, {
        "cypress.config.js":
            "const p = require('./cfg')\n"
            "module.exports = { e2e: { specPattern: p.pat } }\n",
        "cypress/e2e/a.cy.js": "//\n"})
    res = discover(_fp("cypress"), _B(wt))
    assert any("unresolved statically" in w for w in res.warnings)
    # defaults must not silently substitute — specPattern reports
    # the default source it actually used
    assert res.effective["specPattern"]["source"] in ("override",
                                                    "default")


def test_playwright_config_and_projects(tmp_path):
    wt = _write(tmp_path, {
        "playwright.config.ts":
            "export default { testDir: 'e2e',\n"
            "  testMatch: '**/*.spec.ts',\n"
            "  projects: [{name: 'chromium'}, {name: 'firefox'}] }\n",
        "e2e/login.spec.ts": "test('x', async()=>{})\n",
        "e2e/util.ts": "// helper — not a spec\n"})
    res = discover(_fp("playwright"), _B(wt))
    assert [i.path for i in res.items] == ["e2e/login.spec.ts"]
    assert res.items[0].members == ["chromium", "firefox"]
    assert res.effective["projects"]["source"] == "config"


# ---------- katalon parity ----------

KAT_TREE = {
    "P.prj": "<ProjectEntity/>",
    "Test Cases/API/tc1.tc": "<TestCaseEntity><name>tc1</name>"
                             "</TestCaseEntity>",
    "Test Suites/S1.ts": (
        "<TestSuiteEntity><name>S1</name><testCaseLink>"
        "<testCaseId>Test Cases/API/tc1</testCaseId></testCaseLink>"
        "</TestSuiteEntity>"),
    "Test Suites/C1.ts": (
        "<TestSuiteCollectionEntity><testSuiteRunConfigurations>"
        "<TestSuiteRunConfiguration><testSuiteEntity>Test Suites/S1"
        "</testSuiteEntity></TestSuiteRunConfiguration>"
        "</testSuiteRunConfigurations></TestSuiteCollectionEntity>"),
    "Profiles/default.glbl": "<GlobalVariableEntity/>",
}


def test_katalon_parity_items(tmp_path):
    wt = _write(tmp_path, KAT_TREE)
    res = discover(_fp("katalon"), _B(wt))
    kinds = {i.kind for i in res.items}
    assert {"case", "suite", "collection", "profile"} <= kinds
    suite = [i for i in res.items if i.kind == "suite"][0]
    assert suite.members == ["Test Cases/API/tc1"]
    assert suite.selectable


def test_katalon_multiple_prj_warns(tmp_path):
    wt = _write(tmp_path, {**KAT_TREE, "Sub/Q.prj": "<P/>"})
    res = discover(_fp("katalon"), _B(wt))
    assert not res.items
    assert any("multiple .prj" in w for w in res.warnings)


# ---------- persistence + refresh ----------

def _mk(app_db, wt, fw="pytest", **kw):
    p = Project(name="P", description="d")
    db.session.add(p); db.session.flush()
    b = GitBinding(project_id=p.id, name="b", url="x",
                   worktree_path=str(wt), subdirectory="",
                   last_synced_sha="sha1", status="synced")
    db.session.add(b); db.session.flush()
    fp = _fp(fw, **kw)
    fp.binding_id, fp.project_id = b.id, p.id
    db.session.add(fp); db.session.commit()
    return p, b, fp


def test_sync_persists_and_diffs(app, tmp_path):
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, test_roots=["tests"])
        r1 = gitsync.sync_framework_project(fp, b)
        assert fp.discovery_status == "ok"
        assert r1["items"] == 5 and r1["added"] == 5
        ids = {i.node_id: i.id for i in DiscoveredItem.query.filter_by(
            framework_project_id=fp.id)}
        # add a file → +2 items (file + test), others keep ids
        (wt / "tests/test_new.py").write_text("def test_x(): pass\n")
        r2 = gitsync.sync_framework_project(fp, b)
        assert r2["added"] == 2 and r2["kept"] == 5
        ids2 = {i.node_id: i.id for i in DiscoveredItem.query.filter_by(
            framework_project_id=fp.id)}
        for k in ids:
            assert ids[k] == ids2[k]          # stable identities
        # remove → stale-selection warning
        (wt / "tests/test_new.py").unlink()
        r3 = gitsync.sync_framework_project(fp, b)
        assert r3["removed"] == 2
        assert any("stale" in w for w in r3["warnings"])


def test_failed_discovery_keeps_inventory(app, tmp_path):
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, test_roots=["tests"])
        gitsync.sync_framework_project(fp, b)
        assert fp.discovery_status == "ok"
        fp.test_roots_json = '["missing"]'
        db.session.commit()
        out = gitsync.sync_framework_project(fp, b)
        # missing roots produce warnings + zero items → failed; the
        # last good inventory is preserved (not destroyed)
        assert fp.discovery_status in ("failed", "none")
        assert DiscoveredItem.query.filter_by(
            framework_project_id=fp.id).count() >= 1


def test_config_fingerprint_changes(app, tmp_path):
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, test_roots=["tests"])
        f1 = fingerprint(fp)
        fp.test_roots_json = '["other"]'
        assert fingerprint(fp) != f1


# ---------- dispatch gates ----------

def _runtime(app, kind="pytest"):
    """A runtime with positive TOOLCHAIN evidence (ready-discovery)
    — models a passed probe. Execution dispatch additionally needs
    per-project validation (execution_readiness.validate_project);
    discovery/collection ops need only this state."""
    import uuid
    r = Runner(name="w-" + uuid.uuid4().hex[:8], target_type="local",
               os_arch="linux", enabled=True)
    db.session.add(r); db.session.flush()
    rt = RuntimeConnection(name=kind + uuid.uuid4().hex[:4],
                           runner_id=r.id, runtime_kind=kind,
                           executable_path="python3", enabled=True,
                           readiness_state=(
                               "ready-discovery"
                               if kind != "kre" else "not-checked"))
    db.session.add(rt); db.session.commit()
    return rt


def test_dispatch_gates(app, tmp_path):
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, test_roots=["tests"])
        rt = _runtime(app, "pytest")
        item = DiscoveredItem(
            binding_id=b.id, project_id=p.id, framework_project_id=fp.id,
            sha="sha1", kind="test", path="tests/test_math.py",
            name="test_add", node_id="tests/test_math.py::test_add",
            granularity="test", selectable=True, framework="pytest")
        db.session.add(item); db.session.commit()

        # draft project → rejected
        with pytest.raises(dispatch.DispatchError, match="draft"):
            dispatch.create_execution("u", binding=b, source_item=item,
                                      run_config={"runtime_id": rt.id})
        gitsync.sync_framework_project(fp, b)
        # Execution additionally requires the (runtime, project) pair
        # validated to ready-execution (M16 — toolchain readiness
        # alone never authorizes a run).
        from testorchestrator import execution_readiness
        assert execution_readiness.validate_project(rt, p) == []
        # item sha matches binding sha → dispatch ok
        ex = dispatch.create_execution("u", binding=b, source_item=item,
                                       run_config={"runtime_id": rt.id})
        rc = ex.snapshot()["run_config"]
        assert rc["node_ids"] == ["tests/test_math.py::test_add"]
        st = ex.snapshot()["source_target"]
        assert st["framework"] == "pytest"
        assert st["node_id"] == "tests/test_math.py::test_add"

        # wrong runtime kind → rejected
        rt_kre = _runtime(app, "kre")
        with pytest.raises(dispatch.DispatchError, match="pytest"):
            dispatch.create_execution("u", binding=b, source_item=item,
                                      run_config={"runtime_id": rt_kre.id})

        # candidate (parametrized) → rejected
        cand = DiscoveredItem(
            binding_id=b.id, project_id=p.id, framework_project_id=fp.id,
            sha="sha1", kind="test", path="tests/test_math.py",
            name="test_param", node_id="tests/test_math.py::test_param",
            granularity="test", selectable=False, framework="pytest")
        db.session.add(cand); db.session.commit()
        with pytest.raises(dispatch.DispatchError, match="candidate"):
            dispatch.create_execution("u", binding=b, source_item=cand,
                                      run_config={"runtime_id": rt.id})

        # sha moved → stale validation rejected
        b.last_synced_sha = "other"
        db.session.commit()
        with pytest.raises(dispatch.DispatchError, match="revision"):
            dispatch.create_execution("u", binding=b, source_item=item,
                                      run_config={"runtime_id": rt.id})


def test_exact_selection_snapshot_map(app, tmp_path):
    with app.app_context():
        """Robot + behave + cypress selector mapping."""
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, fw="robot", test_roots=["x"])
        fp.discovery_status = "ok"; fp.discovered_sha = "sha1"
        db.session.commit()
        rt = _runtime(app, "robot")
        from testorchestrator import execution_readiness
        assert execution_readiness.validate_project(rt, p) == []
        it = DiscoveredItem(
            binding_id=b.id, project_id=p.id, framework_project_id=fp.id,
            sha="sha1", kind="test", path="s/x.robot", name="T",
            node_id="T", granularity="test", selectable=True,
            framework="robot")
        db.session.add(it); db.session.commit()
        ex = dispatch.create_execution("u", binding=b, source_item=it,
                                       run_config={"runtime_id": rt.id})
        rc = ex.snapshot()["run_config"]
        assert rc["robot_test"] == "T"
        assert rc["suite_path"] == "s/x.robot"

        # behave scenario → path:LINE target
        fp2 = _fp("behave"); fp2.binding_id, fp2.project_id = b.id, p.id
        fp2.name = "b"; fp2.discovery_status = "ok"
        fp2.discovered_sha = "sha1"
        db.session.add(fp2); db.session.commit()
        rtb = _runtime(app, "behave")
        assert execution_readiness.validate_project(rtb, p) == []
        it2 = DiscoveredItem(
            binding_id=b.id, project_id=p.id,
            framework_project_id=fp2.id, sha="sha1", kind="scenario",
            path="f/a.feature", name="s", node_id="f/a.feature:3",
            granularity="scenario", selectable=True, framework="behave")
        db.session.add(it2); db.session.commit()
        ex2 = dispatch.create_execution("u", binding=b, source_item=it2,
                                        run_config={"runtime_id": rtb.id})
        assert ex2.snapshot()["run_config"]["behave_targets"] == \
            ["f/a.feature:3"]


# ---------- URL auth ----------

def test_url_password_rejected():
    from testorchestrator.portal.forms import reject_url_password
    assert reject_url_password("https://u:p%40ss@h/r.git")
    assert reject_url_password("https://u:pw@h/r.git")
    assert not reject_url_password("git@h:r.git")
    assert not reject_url_password("ssh://git@h/r.git")
    assert not reject_url_password("https://h/r.git")
    assert not reject_url_password("https://u@h/r.git")  # userinfo
                                                    # without pass


# ---------- migration backfill ----------

def _upgrade(app, rev="head"):
    with app.app_context():
        from flask_migrate import upgrade
        upgrade(directory=MIGRATIONS, revision=rev)


def _binding_row(subdir, prj):
    return {"id": "b1", "project_id": "p1", "name": "b", "url": "u",
            "ref": "main", "subdirectory": subdir, "prj_path": prj,
            "credential_ref": "", "worktree_path": "/w",
            "last_synced_sha": "", "status": "synced",
            "last_error": "", "discovery_error": "",
            "project_root": ""}


def _seed_binding(c, **over):
    row = _binding_row("", "")
    row.update(over)
    cols = ", ".join(row)
    vals = ", ".join(f":{k}" for k in row)
    c.execute(sa.text(
        f"INSERT INTO git_bindings ({cols}) VALUES ({vals})"), row)


def test_backfill_derives_effective_behavior(tmp_path):
    """The backfill must NOT activate prj_path (it was never read):
    project_root stays binding-scope (''), prj_path only lands in
    informational config_file."""
    from tests.conftest import make_app
    app = make_app(tmp_path, "upgrade.db")
    _upgrade(app, "a2b3c4d5e6f7")
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO projects (id, name, description) "
            "VALUES ('p1', 'L', '')"))
        _seed_binding(c, subdirectory="sub", prj_path="")
    _upgrade(app, "head")
    with eng.begin() as c:
        fp = c.execute(sa.text(
            "SELECT project_root, workdir, config_file, framework, "
            "discovery_status FROM framework_projects")).one()
        # subdirectory stays on the binding — project_root must NOT
        # re-embed it (effective base is worktree+subdirectory).
        assert fp[0] == ""
        assert fp[3] == "katalon"
        assert fp[4] in ("ok", "draft")
        # conflicting prj_path never re-roots — informational only
        c.execute(sa.text(
            "UPDATE git_bindings SET prj_path='X/P.prj' "
            "WHERE id='b1'"))
    app2 = make_app(tmp_path, "upgrade2.db")
    _upgrade(app2, "a2b3c4d5e6f7")
    eng2 = sa.create_engine(f"sqlite:///{tmp_path / 'upgrade2.db'}")
    with eng2.begin() as c:
        c.execute(sa.text(
            "INSERT INTO projects (id, name, description) "
            "VALUES ('p1', 'L', '')"))
        _seed_binding(c, subdirectory="", prj_path="X/P.prj")
    _upgrade(app2, "head")
    with eng2.begin() as c:
        fp = c.execute(sa.text(
            "SELECT project_root, config_file FROM "
            "framework_projects")).one()
        assert fp[0] == ""                    # not 'X'
        assert fp[1] == "X/P.prj"             # informational only


# ---------- gtest / jest adapters ----------

GTREE = {
    "CMakeLists.txt": "project(t)",
    "tests/math_test.cc": (
        "#include <gtest/gtest.h>\n"
        "TEST(MathSuite, Adds) {}\n"
        "TEST(MathSuite, DISABLED_Skipped) {}\n"
        "TEST_P(ParamSuite, Cases) {}\n"
        "INSTANTIATE_TEST_SUITE_P(MyInst, ParamSuite, ::testing::Values(1));\n"),
}

JTREE = {
    "package.json": '{"name":"t","jest":{"testMatch":["**/*.test.js"]}}',
    "src/a.test.js": "test('adds',()=>{}); describe('grp',()=>{"
                     "it('works',()=>{})});\n",
    "src/b.test.js": "test('adds',()=>{}); test.todo('later');\n",
}


def test_gtest_static_candidates(tmp_path):
    """gtest static discovery: executables → file-level selectable;
    TEST() names → candidates (identity needs --gtest_list_tests)."""
    wt = _write(tmp_path, GTREE)
    (wt / "build").mkdir()
    (wt / "build/tests").write_text("bin")
    (wt / "build/tests").chmod(0o755)
    fp = _fp("gtest", test_roots=["tests"])
    fp.settings_json = json.dumps(
        {"build_dir": "build", "executables": ["build/tests"]})
    res = discover(fp, _B(wt))
    exes = [i for i in res.items if i.tags == "executable"]
    assert exes and exes[0].selectable
    tests = {i.name: i for i in res.items if i.kind == "test"}
    assert tests["MathSuite.Adds"].node_id == "MathSuite.Adds"
    assert not tests["MathSuite.Adds"].selectable    # candidate
    assert tests["MathSuite.DISABLED_Skipped"].tags == "disabled"
    assert tests["ParamSuite.Cases"].tags == "typed/param"
    assert tests["MyInst/*"].node_id == ""           # instantiation
    assert res.needs_native


def test_jest_file_level_and_candidates(tmp_path):
    wt = _write(tmp_path, JTREE)
    fp = _fp("jest", config_file="package.json")
    res = discover(fp, _B(wt))
    files = [i for i in res.items if i.granularity == "file"]
    assert len(files) == 2
    assert all(i.selectable for i in files)
    # test names are candidates — duplicate 'adds' across files
    # proves why file identity is required for selection
    names = [i.name for i in res.items if i.kind == "test"]
    assert names.count("adds") == 2
    assert all(not i.selectable for i in res.items
               if i.kind == "test")
    assert res.needs_native
    assert res.effective["testMatch"]["source"] == "config"


def test_gtestfw_driver_script():
    """POSIX driver: missing binary → exit 4, single-quoted argv,
    provenance manifest written."""
    from testorchestrator.adapters import gtestfw
    s = gtestfw.build_script(
        [("b/t's", "S.*", "x1")], build="cmake --build b",
        list_tests=True, timeout_s=60)
    assert "sh -c 'cmake --build b'" in s
    assert "'b/t'\\''s'" in s                     # quote escape
    assert "exit 4" in s and "--gtest_filter=S.*" in s
    assert "--gtest_list_tests" in s
    assert "sha256sum" in s
    # flag-guard: unsupported --gtest_fail_if_no_test_selected must
    # never reach the binary (help text + exit 0 = silent zero-run)
    s2 = gtestfw.build_script([("b/t", "", "x1")], fail_if_no_test=True)
    assert "--gtest_help" in s2 and "$NZFLAG" in s2
    assert "NO RESULT XML" in s2
    kinds = dict((rc, kind) for rc, (kind, _) in
                 ((0, gtestfw.classify_exit(0)),
                  (2, gtestfw.classify_exit(2)),
                  (3, gtestfw.classify_exit(3)),
                  (4, gtestfw.classify_exit(4))))
    assert kinds == {0: "ok", 2: "config", 3: "config",
                     4: "infrastructure"}


def test_collectors_cover_native_frameworks():
    """Every framework with native collection has a staged script;
    node-kind frameworks get .js (no python on the target)."""
    from testorchestrator import collectors
    assert set(collectors.COLLECT_SCRIPTS) >= {
        "pytest", "pytest-bdd", "playwright-pytest", "robot",
        "behave", "gtest", "jest", "playwright", "cypress"}
    for f in collectors.NODE_SCRIPTS:
        assert "(function" in collectors.COLLECT_SCRIPTS[f] or \
            "require(" in collectors.COLLECT_SCRIPTS[f]


def test_node_collectors_windows_safe_spawn():
    """ISS-017: staged node collectors must not exec a bare ``npx`` —
    on Windows that misses ``npx.cmd`` (ENOENT), batch exec without
    ``shell: true`` is EINVAL on Node >=20.12, and collect skips the
    deps step so npx bin resolution can fall back to PATH and hit an
    unrelated binary (a Python ``playwright.exe`` has no ``test``
    command). The scripts resolve the staged node_modules CLI via
    ``node`` first and use ``npx.cmd`` + ``shell: true`` on win32
    only as a fallback."""
    import re
    from testorchestrator import collectors
    for f in ("playwright", "jest"):
        s = collectors.COLLECT_SCRIPTS[f]
        assert 'process.platform === "win32"' in s
        assert "npx.cmd" in s
        assert re.search(r"cli\.js|jest\.js", s), \
            f"{f}: no staged node_modules CLI resolution"
        assert re.search(r"shell:\s*SHELL", s)
        # no execFileSync with a literal "npx" as the program remains
        assert not re.search(r'execFileSync\(\s*\n?\s*"npx"', s)


def test_gtest_collect_globs_and_strips_param_annotations(tmp_path):
    """ISS-018: gtest collect must expand executables glob patterns
    (build/*) in the staged checkout — a literal pattern or a "."
    root was exec'd as a binary and produced zero items — and must
    surface parameterized instances under their canonical
    filterable identity (AddsUp/0), not the listing's
    '# GetParam() = …' annotation."""
    import os, stat, subprocess, sys
    from testorchestrator import collectors
    stub = tmp_path / "build" / "to_gtest_param.exe"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "#!/bin/sh\n"
        'printf "Smoke.\\n  Passes\\nArith/ParamAdd.\\n"\n'
        'printf "  AddsUp/0  # GetParam() = 1\\n"\n'
        'printf "  AddsUp/1  # GetParam() = 2\\n"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    script = tmp_path / ".to_collect.py"
    script.write_text(collectors.COLLECT_SCRIPTS["gtest"])
    subprocess.run([sys.executable, str(script), "build/*", "none/*"],
                   cwd=tmp_path, check=True)
    doc = json.loads((tmp_path / "Reports" / "collect.json")
                     .read_text())
    ids = [i["node_id"] for i in doc["items"]]
    assert "build/to_gtest_param.exe||Arith/ParamAdd.AddsUp/0" in ids
    assert "build/to_gtest_param.exe||Arith/ParamAdd.AddsUp/1" in ids
    assert not any("#" in i for i in ids)
    assert doc["warnings"] == ["none/*: no executable matched"]


# ---------- native collection reconcile ----------

def _ex_for(fp, b, sha="sha1"):
    return dispatch.create_execution(
        "u", binding=b, source_sha=sha,
        run_config={"native_collect": True, "fp_id": fp.id})


def test_apply_native_inventory_reconciles(app, tmp_path):
    """collect.json upgrades static candidates to validated
    identities and adds native-only items — static preview rows not
    seen natively are kept (never destroyed)."""
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, test_roots=["tests"])
        gitsync.sync_framework_project(fp, b)
        cand = DiscoveredItem.query.filter_by(
            framework_project_id=fp.id,
            name="test_param").one()
        assert not cand.selectable
        ex = _ex_for(fp, b)
        cj = tmp_path / "collect.json"
        cj.write_text(json.dumps({"items": [
            {"kind": "test", "path": "tests/test_math.py",
             "name": "test_param", "parent": "",
             "node_id": "tests/test_math.py::test_param[1]",
             "granularity": "test", "tags": []},
            {"kind": "test", "path": "tests/test_math.py",
             "name": "test_param[2]", "parent": "",
             "node_id": "tests/test_math.py::test_param[2]",
             "granularity": "test", "tags": []}]}))
        out = gitsync.apply_native_inventory(ex, cj)
        assert not out.get("error")
        cand = db.session.get(DiscoveredItem, cand.id)
        assert cand.selectable
        assert cand.node_id == "tests/test_math.py::test_param[1]"
        assert cand.item_type == "native"
        new = DiscoveredItem.query.filter_by(
            framework_project_id=fp.id,
            name="test_param[2]").one()
        assert new.item_type == "native" and new.selectable
        assert fp.discovery_status == "ok"
        assert fp.discovered_sha == "sha1"


def test_apply_native_inventory_monorepo_prefix(app, tmp_path):
    """Regression: collectors emit paths relative to the framework
    project root (their cwd) — ingestion must re-prefix the root so
    native rows merge with static rows instead of duplicating them
    with rootless or absolute worker paths (matrix wave: jest collect
    ingested '/opt/.../build/src/jest/x.js' as-is)."""
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, test_roots=["tests"])
        gitsync.sync_framework_project(fp, b)
        before = {(i.kind, i.path, i.name) for i in
                  DiscoveredItem.query.filter_by(
                      framework_project_id=fp.id)}
        ex = _ex_for(fp, b)
        cj = tmp_path / "collect.json"
        cj.write_text(json.dumps({"items": [
            {"kind": "test", "path": "test_math.py",
             "name": "test_param", "parent": "",
             "node_id": "tests/test_math.py::test_param[1]",
             "granularity": "test", "tags": [],
             "parent2": "test_math.py"}]}))
        out = gitsync.apply_native_inventory(ex, cj)
        assert not out.get("error")
        rows = DiscoveredItem.query.filter_by(
            framework_project_id=fp.id).all()
        paths = {r.path for r in rows}
        # no rootless or absolute junk paths
        assert "test_math.py" not in paths
        assert not any(pth.startswith("/") for pth in paths)
        # merged: the static row upgraded in place, not duplicated
        match = [r for r in rows
                 if r.path == "tests/test_math.py"
                 and r.name == "test_param"]
        assert len(match) == 1, [(r.path, r.name) for r in rows]
        assert match[0].selectable


def test_native_collect_runtime_gate(app, tmp_path):
    """request_native_collection rejects a runtime whose kind can't
    host the framework's collector (server-side gate)."""
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, test_roots=["tests"])
        rt = _runtime(app, "kre")
        with pytest.raises(ValueError, match="pytest"):
            gitsync.request_native_collection(fp, b, rt, "u")
        rt2 = _runtime(app, "pytest")
        ex = gitsync.request_native_collection(fp, b, rt2, "u")
        rc = ex.snapshot()["run_config"]
        assert rc["native_collect"] and rc["fp_id"] == fp.id
        assert rc["requested_runtime"] == rt2.id


def test_native_collect_snapshots_fp_settings(app, tmp_path):
    """ISS-018: the collect run must carry the project's framework
    settings — without them gtest collect receives no executables
    patterns and lists "." as a binary."""
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, fw="gtest", test_roots=["."])
        fp.settings_json = json.dumps(
            {"build_dir": "build", "executables": ["build/*"]})
        db.session.commit()
        rt = _runtime(app, "gtest")
        ex = gitsync.request_native_collection(fp, b, rt, "u")
        rc = ex.snapshot()["run_config"]
        assert rc["gtest"]["executables"] == ["build/*"]


def test_gtest_native_node_id_sets_filter(app, tmp_path):
    """ISS-018: selecting a collected gtest test item
    (<exe>||Suite.Test) must produce spec + exact --gtest_filter —
    parameterized instances included — instead of silently running
    the whole binary."""
    with app.app_context():
        wt = _write(tmp_path, PYTREE)
        p, b, fp = _mk(app, wt, fw="gtest", test_roots=["."])
        fp.settings_json = json.dumps({"build_dir": "build"})
        fp.discovery_status = "ok"
        fp.discovery_fingerprint = fingerprint(fp)
        db.session.commit()
        rt = _runtime(app, "gtest")
        it = DiscoveredItem(
            binding_id=b.id, project_id=p.id,
            framework_project_id=fp.id, sha="sha1", kind="test",
            path="build/to_gtest_param.exe",
            name="Arith/ParamAdd.AddsUp/0",
            node_id="build\\to_gtest_param.exe||"
                    "Arith/ParamAdd.AddsUp/0",
            granularity="test", selectable=True,
            framework="gtest",
            fingerprint=fp.discovery_fingerprint)
        db.session.add(it); db.session.commit()
        from testorchestrator import execution_readiness
        assert execution_readiness.validate_project(rt, p) == []
        ex = dispatch.create_execution(
            "u", binding=b, source_item=it,
            run_config={"runtime_id": rt.id})
        rc = ex.snapshot()["run_config"]
        assert rc["spec"] == "build\\to_gtest_param.exe"
        assert rc["suite_path"] == "build\\to_gtest_param.exe"
        assert rc["gtest_filter"] == "Arith/ParamAdd.AddsUp/0"


# ---------- postman / bruno adapters ----------

PM_V21 = {
    "api/collections/login.postman_collection.json": json.dumps({
        "info": {"name": "Login", "schema":
                 "https://schema.getpostman.com/json/collection/"
                 "v2.1.0/collection.json"},
        "variable": [{"key": "base_url", "value": "http://x"}],
        "item": [
            {"name": "auth", "item": [
                {"name": "token", "request": {"method": "POST",
                                              "url": "{{base_url}}"},
                 "event": [{"listen": "test",
                            "script": {"exec": ["pm.test()"]}}]},
                {"name": "me", "request": {"method": "GET"}}]},
            {"name": "ping", "request": {"method": "GET"}}]}),
    "api/env/local.postman_environment.json": "{}",
    "api/other.json": '{"not":"a collection"}',
}

PM_V3 = {
    "colls/orders/definition.yaml": "name: Orders\n",
    "colls/orders/requests/list.yaml": "name: list\nmethod: GET\n",
    "colls/orders/admin/definition.yaml": "name: admin\n",
    "colls/orders/admin/create.yaml": "name: create\nmethod: POST\n",
    "colls/orders/resources/schema.yaml": "openapi: 3\n",
}

BRUNO_TREE = {
    "api/bruno.json": '{"version":"1","name":"api","type":'
                      '"collection"}',
    "api/ping.bru": "meta {\n  name: ping\n  type: http\n}\n"
                    "get { url: http://x }\n",
    "api/admin/create.bru": "meta {\n  name: create\n  type: http\n}"
                            "\ntests { assert(res.status, 200) }\n",
    "api/environments/local.bru": "vars { host: x }\n",
    "nested/opencollection.yml": "name: nested\n",
    "nested/get-user.yaml": "name: get-user\ntype: request\n",
    "nested/notes.yaml": "just: data\n",
}


def test_postman_v21_collection(tmp_path):
    wt = _write(tmp_path, PM_V21)
    fp = _fp("postman", test_roots=["api"])
    res = discover(fp, _B(wt))
    col = [i for i in res.items if i.kind == "collection"]
    assert len(col) == 1 and col[0].selectable
    assert "format:v2.1" in col[0].tags
    folders = [i for i in res.items if i.kind == "folder"]
    assert folders[0].selectable                 # newman --folder
    reqs = [i for i in res.items if i.kind == "test"]
    assert len(reqs) == 3
    assert all(not r.selectable for r in reqs)   # requests candidate
    assert any("vars:base_url" in (c.tags or "") for c in col)
    assert any("script" in w for w in res.warnings)


def test_postman_v3_cli_only(tmp_path):
    """v3 YAML collections are postman-cli only — newman can't
    execute them (unmaintained, v2.1 only)."""
    wt = _write(tmp_path, PM_V3)
    fp = _fp("postman", test_roots=["colls"])
    fp.settings_json = json.dumps({"engine": "newman"})
    res = discover(fp, _B(wt))
    col = [i for i in res.items if i.kind == "collection"]
    assert len(col) == 1
    assert not col[0].selectable                 # engine mismatch
    assert "postman-cli" in col[0].warnings
    fp2 = _fp("postman", test_roots=["colls"])
    fp2.settings_json = json.dumps({"engine": "postman-cli"})
    res2 = discover(fp2, _B(wt))
    col2 = [i for i in res2.items if i.kind == "collection"]
    assert col2[0].selectable
    reqs = [i for i in res2.items if i.kind == "test"]
    assert all(r.selectable for r in reqs)       # v3 path selectors
    assert {r.node_id for r in reqs} == {
        "colls/orders/requests/list.yaml",
        "colls/orders/admin/create.yaml"}


def test_bruno_collection_and_paths(tmp_path):
    wt = _write(tmp_path, BRUNO_TREE)
    fp = _fp("bruno")
    res = discover(fp, _B(wt))
    cols = [i for i in res.items if i.kind == "collection"]
    assert len(cols) == 2                        # both layouts
    reqs = [i for i in res.items if i.kind == "test"]
    nodes = {r.node_id for r in reqs}
    assert "ping.bru" in nodes and "admin/create.bru" in nodes
    assert "get-user.yaml" in nodes              # yaml request
    assert all(r.selectable for r in reqs)       # path selectors
    folders = [i for i in res.items if i.kind == "folder"]
    assert folders[0].node_id == "admin"
    assert "recursion" in folders[0].warnings
    env = [i for i in res.items if i.tags == "environment"]
    assert env and not env[0].selectable
    # notes.yaml isn't a request — never an item
    assert not any(i.path.endswith("notes.yaml") for i in res.items)


def test_bruno_and_postmanfw_args():
    from testorchestrator.adapters import brunofw, postmanfw
    a = brunofw.build_args("api", paths=["admin", "ping.bru"],
                           recurse=True, environment="local",
                           include_tags=["smoke"], iterations=3,
                           developer_mode=False)
    assert a[:4] == ["run", "admin", "ping.bru", "-r"]
    assert "--sandbox" in a and a[a.index("--sandbox") + 1] == "safe"
    assert "--env" in a and "--tags-include" in a
    a2 = brunofw.build_args("api", developer_mode=True)
    assert a2[a2.index("--sandbox") + 1] == "developer"
    p = postmanfw.build_args("newman", "c.json", folder="auth",
                             environment="e.json")
    assert "--folder" in p and "--reporter-json-no-body" in p
    p3 = postmanfw.build_args("postman-cli", "colls/orders",
                              paths=["colls/orders/requests/list.yaml"],
                              collection_format="v3")
    assert "--output" in p3 and "--reporters" not in p3


# ---------- ISS-015: playwright --list schema drift ----------

def test_playwright_collect_parses_15x_schema(tmp_path):
    """playwright 1.4x+ --list --reporter=json puts `file` on suite /
    spec entries, not suite.location.file — collected items must keep
    their file path or selection/dispatch breaks (ISS-015)."""
    import os, shutil, subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed — collector executes under node")
    from testorchestrator import collectors
    # Canned --list output matching the 1.65 schema observed on the
    # acceptance guest (suite.file / spec.file, no .location).
    doc = {"suites": [{
        "title": "smoke.spec.js", "file": "smoke.spec.js",
        "specs": [{"title": "smoke", "file": "smoke.spec.js",
                   "line": 2, "column": 1,
                   "tests": [{"projectId": "", "projectName": "",
                              "status": "skipped"}]}]},
        {"title": "nest", "suites": [{
            "title": "deep.spec.js", "file": "deep.spec.js",
            "specs": [{"title": "deep", "file": "deep.spec.js",
                       "tests": [{"projectId": "", "projectName": "chromium",
                                  "status": "skipped"}]}]}]}]}
    fake_npx = tmp_path / "bin" / "npx"
    fake_npx.parent.mkdir()
    fake_npx.write_text("#!/bin/sh\n"
                        "cat <<'JSON'\n" + json.dumps(doc) + "\nJSON\n")
    fake_npx.chmod(0o755)
    script = tmp_path / "collect.js"
    script.write_text(collectors.COLLECT_SCRIPTS["playwright"])
    env = dict(os.environ, PATH=f"{fake_npx.parent}:{os.environ['PATH']}")
    subprocess.run([node, str(script)], cwd=tmp_path, env=env,
                   check=True, timeout=60)
    out = json.loads((tmp_path / "Reports" / "collect.json").read_text())
    by_name = {i["name"]: i for i in out["items"]}
    assert by_name["smoke"]["path"] == "smoke.spec.js"
    assert by_name["smoke"]["node_id"].startswith("t:smoke.spec.js")
    assert by_name["deep"]["path"] == "deep.spec.js"
    assert by_name["deep"]["tags"] == ["chromium"]


def test_playwright_collect_parses_legacy_location_schema(tmp_path):
    """Older playwright --list put file at suite.location.file."""
    import os, shutil, subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed — collector executes under node")
    from testorchestrator import collectors
    doc = {"suites": [{
        "title": "a.spec.js",
        "location": {"file": "a.spec.js", "line": 0, "column": 0},
        "specs": [{"title": "t1",
                   "location": {"file": "a.spec.js", "line": 1},
                   "tests": [{"projectId": "", "projectName": "",
                              "status": "skipped"}]}]}]}
    fake_npx = tmp_path / "bin" / "npx"
    fake_npx.parent.mkdir()
    fake_npx.write_text("#!/bin/sh\n"
                        "cat <<'JSON'\n" + json.dumps(doc) + "\nJSON\n")
    fake_npx.chmod(0o755)
    script = tmp_path / "collect.js"
    script.write_text(collectors.COLLECT_SCRIPTS["playwright"])
    env = dict(os.environ, PATH=f"{fake_npx.parent}:{os.environ['PATH']}")
    subprocess.run([node, str(script)], cwd=tmp_path, env=env,
                   check=True, timeout=60)
    out = json.loads((tmp_path / "Reports" / "collect.json").read_text())
    assert out["items"][0]["path"] == "a.spec.js"


def test_native_collect_noop_preserves_status(app, tmp_path):
    """ISS-016: a by-design no-op collector (cypress has no native
    list) must not mark discovery failed and poison the dispatch
    gate — status + inventory stay as they were."""
    with app.app_context():
        wt = _write(tmp_path, {
            "cypress.config.js": "module.exports={e2e:{specPattern:"
                                 "'e2e/**/*.cy.js'}};",
            "e2e/a.cy.js": "describe('a',()=>{it('x',()=>{})});",
        })
        p, b, fp = _mk(app, wt, fw="cypress", test_roots=["e2e"])
        gitsync.sync_framework_project(fp, b)
        assert fp.discovery_status == "ok"
        ex = _ex_for(fp, b)
        cj = tmp_path / "collect.json"
        cj.write_text(json.dumps({
            "framework": "cypress", "items": [], "noop": True,
            "warnings": ["cypress has no native list command"]}))
        out = gitsync.apply_native_inventory(ex, cj)
        assert out.get("noop") and not out.get("error")
        db.session.refresh(fp)
        assert fp.discovery_status == "ok"
