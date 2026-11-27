""".tsc collection discovery — genuine defect found in matrix batch 3:
scan filters matched only .ts, so legacy-format collections never
surfaced even though execution accepts them."""
import os

from testorchestrator.discovery import katalon


def _write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


TSC = """<?xml version="1.0"?>
<TestSuiteCollectionEntity><name>smoke</name>
<runMode>SEQUENTIAL</runMode>
<testSuiteRunConfigurations>
<TestSuiteRunConfiguration>
<testSuiteEntity>Test Suites/TS1</testSuiteEntity>
</TestSuiteRunConfiguration>
<TestSuiteRunConfiguration>
<testSuiteEntity>Test Suites/TS2</testSuiteEntity>
</TestSuiteRunConfiguration>
</testSuiteRunConfigurations>
</TestSuiteCollectionEntity>"""

TS = """<?xml version="1.0"?>
<TestSuiteEntity><name>TS1</name></TestSuiteEntity>"""


def test_tsc_collection_discovered(tmp_path):
    _write(tmp_path / "fixture.prj", "<Project></Project>")
    _write(tmp_path / "Test Suites" / "TS1.ts", TS)
    _write(tmp_path / "Test Suites" / "smoke.tsc", TSC)
    from types import SimpleNamespace
    ctx = SimpleNamespace(base=tmp_path,
                          fp=SimpleNamespace(project_root=""))
    res = katalon.parse(ctx)
    colls = [i for i in res.items if i.kind == "collection"]
    assert any(c.path.endswith("smoke.tsc") for c in colls), \
        f".tsc not discovered: {[(i.kind, i.path) for i in res.items]}"
    coll = next(c for c in colls if c.path.endswith("smoke.tsc"))
    assert len(coll.members) == 2
    assert "runmode:SEQUENTIAL" in (coll.tags or "")


def test_real_ts_suite_not_misclassified(tmp_path):
    """Genuine Katalon projects save BOTH suites and collections as .ts —
    the entity tag, never the extension, decides. A TestSuiteEntity in a
    .ts file must stay a suite even with .tsc scanning enabled, and a
    TestSuiteCollectionEntity in a .ts file is a collection (the
    Katalon-cert repo format: 'Test Suite Collection v1.ts')."""
    suite_ts = """<?xml version="1.0"?>
<TestSuiteEntity><name>API-TS</name></TestSuiteEntity>"""
    coll_ts = TSC.replace("<name>smoke</name>",
                          "<name>Test Suite Collection v1</name>")
    _write(tmp_path / "fixture.prj", "<Project></Project>")
    _write(tmp_path / "Test Suites" / "API-TS.ts", suite_ts)
    _write(tmp_path / "Test Suites" / "Test Suite Collection v1.ts",
           coll_ts)
    from types import SimpleNamespace
    ctx = SimpleNamespace(base=tmp_path,
                          fp=SimpleNamespace(project_root=""))
    res = katalon.parse(ctx)
    by_path = {i.path: i for i in res.items}
    suite = by_path.get("Test Suites/API-TS.ts")
    coll = by_path.get("Test Suites/Test Suite Collection v1.ts")
    assert suite is not None and suite.kind == "suite", \
        f"suite misclassified: {suite and suite.kind}"
    assert coll is not None and coll.kind == "collection", \
        f"collection misclassified: {coll and coll.kind}"
    assert len(coll.members) == 2
