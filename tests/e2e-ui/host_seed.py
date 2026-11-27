"""Seed the non-.prj discovered items + framework projects for the
VM-E2E project — runs under sudo with PYTHONPATH=/opt/testorchestrator.
Katalon items arrive via real binding Sync; this seeds only the
framework-project inventory the suite dispatches (documented boundary:
the e2e suite does not ship framework projects through the UI).
"""
import sys

sys.path.insert(0, "/opt/testorchestrator")
from testorchestrator import create_app  # noqa: E402
from testorchestrator.extensions import db  # noqa: E402
from testorchestrator.execution import (  # noqa: E402
    Project, GitBinding, DiscoveredItem, FrameworkProject)

ITEMS = [
    ("pytest-pass", "pytest/test_smoke.py", "pytest"),
    ("pytest-fail", "pytest/test_fail.py", "pytest"),
    ("smoke.robot", "tests/smoke.robot", "robot"),
    ("fail.robot", "tests/fail.robot", "robot"),
    ("pw.spec.js", "tests/pw.spec.js", "playwright"),
    ("cy.cy.js", "cypress/e2e/cy.cy.js", "cypress"),
]

app = create_app()
with app.app_context():
    p = Project.query.filter_by(name="VM-E2E").first()
    assert p, "VM-E2E project missing"
    b = GitBinding.query.filter_by(project_id=p.id,
                                   name="vm-bind").first()
    assert b, "vm-bind binding missing"
    sha = b.last_synced_sha or "seed"

    fps = {}
    for fw in ("pytest", "robot", "playwright", "cypress"):
        fp = FrameworkProject.query.filter_by(
            binding_id=b.id, framework=fw).first()
        if fp is None:
            fp = FrameworkProject(binding_id=b.id, project_id=p.id,
                                  name=f"vm-e2e-{fw}", framework=fw)
            db.session.add(fp)
        # honesty note: discovery_status=ok is seeded, not run — the
        # adapter discovery path for non-.prj kinds is validated
        # separately; dispatch requires the validated flag.
        fp.discovery_status = "ok"
        fp.discovered_sha = sha
        fps[fw] = fp
    db.session.flush()

    for name, path, fw in ITEMS:
        it = DiscoveredItem.query.filter_by(
            binding_id=b.id, name=name).first()
        if it is None:
            it = DiscoveredItem(binding_id=b.id, project_id=p.id,
                                name=name)
            db.session.add(it)
        it.framework_project_id = fps[fw].id
        it.sha = sha
        it.kind = "case"
        it.path = path
        it.framework = fw
        it.node_id = path
        it.granularity = "file"
        it.selectable = True
    db.session.commit()
    print("SEEDED-ITEMS", len(ITEMS), "sha", sha[:12])
