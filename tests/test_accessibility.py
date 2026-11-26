"""Regression: every form control on the operator-facing forms must
have an accessible name — an associated <label for>, a wrapping
<label>, or an aria-label. Guarded pages: runtime/target management
(manual + guided), secret scope, storage destinations, licence,
users, and the project tabs that host schedule/storage forms.

Catches the SonarLint InputWithoutLabelCheck / S6853 class that the
2.7.0 quality gate cleared (165 findings -> 0).
"""
from html.parser import HTMLParser

from testorchestrator.execution import Project
from testorchestrator.extensions import db
from tests.conftest import login


class _Controls(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls = []      # (tag, attrs dict, inside_label)
        self.label_fors = set()
        self._label_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_fors.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            if a.get("type") == "hidden" or "disabled" in a:
                return
            self.controls.append((tag, a, self._label_depth > 0))

    def handle_endtag(self, tag):
        if tag == "label" and self._label_depth:
            self._label_depth -= 1

    def unlabeled(self):
        bad = []
        for tag, a, wrapped in self.controls:
            if wrapped or a.get("aria-label"):
                continue
            if a.get("id") and a["id"] in self.label_fors:
                continue
            bad.append((tag, a.get("name") or a.get("id") or "?"))
        return bad


def _assert_labeled(html, page):
    p = _Controls()
    p.feed(html)
    bad = p.unlabeled()
    assert not bad, f"{page}: unlabeled controls {bad}"


def test_infrastructure_page_all_controls_labeled(app, client, login_as):
    """Workers + runtime tables, edit forms, manual add-runtime —
    the KRE/manual runtime surface."""
    login_as("admin")
    r = client.get("/system/infrastructure")
    assert r.status_code == 200
    _assert_labeled(r.get_data(as_text=True), "infrastructure")


def test_runtime_wizard_controls_labeled(app, client, login_as):
    """Guided add-runtime — engine/profile fields."""
    login_as("admin")
    r = client.get("/system/infrastructure/add-runtime")
    assert r.status_code == 200
    _assert_labeled(r.get_data(as_text=True), "runtime-wizard")


def test_secrets_page_controls_labeled(app, client, login_as):
    """Secrets + scope-grant editors."""
    login_as("admin")
    r = client.get("/system/secrets")
    assert r.status_code == 200
    _assert_labeled(r.get_data(as_text=True), "secrets")


def test_project_storage_form_controls_labeled(app, client, login_as):
    """Storage destinations + schedule/binding/suite forms on the
    project detail tabs."""
    login_as("admin")
    with app.app_context():
        db.session.add(Project(name="P"))
        db.session.commit()
        pid = Project.query.one().id
    r = client.get(f"/projects/{pid}?tab=storage")
    assert r.status_code == 200
    _assert_labeled(r.get_data(as_text=True), "project-storage")
    r = client.get(f"/projects/{pid}")
    _assert_labeled(r.get_data(as_text=True), "project-detail")


def test_admin_pages_controls_labeled(app, client, login_as):
    """Licence + users + reporting + network admin surfaces."""
    login_as("admin")
    for url in ("/system/licence", "/system/users", "/system/reporting",
                "/system/network"):
        r = client.get(url)
        assert r.status_code == 200, url
        _assert_labeled(r.get_data(as_text=True), url)
