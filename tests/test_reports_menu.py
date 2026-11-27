from datetime import datetime, timezone

from testorchestrator.execution import Execution, Outcome, Project
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
