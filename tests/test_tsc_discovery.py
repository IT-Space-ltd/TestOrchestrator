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
