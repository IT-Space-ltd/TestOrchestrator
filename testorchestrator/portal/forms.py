from flask_wtf import FlaskForm
from wtforms import (BooleanField, IntegerField, SelectField,
                     SelectMultipleField, StringField, TextAreaField)
from wtforms.validators import DataRequired, Length, Optional

from ..adapters.kre import SUPPORTED_BROWSERS

BROWSER_CHOICES = ([(m["label"], m["label"])
                    for m in SUPPORTED_BROWSERS.values()]
                   # Node-runtime browsers (Playwright --project /
                   # Cypress --browser) + framework default.
                   + [("", "framework default (Playwright/Cypress)"),
                      ("chromium", "chromium"),
                      ("firefox", "firefox"),
                      ("webkit", "webkit (Playwright)"),
                      ("chrome", "chrome (Cypress)"),
                      ("edge", "edge (Cypress)"),
                      ("electron", "electron (Cypress)")])


class ProjectForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=128)])
    description = TextAreaField("Description", validators=[Optional()])


class BindingForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=128)])
    url = StringField("Repository URL or path",
                      validators=[DataRequired(), Length(max=512)])
    ref = StringField("Ref (branch/tag)", validators=[Optional(), Length(max=128)])
    subdirectory = StringField("Subdirectory", validators=[Optional()])
    prj_path = StringField(".prj path", validators=[Optional()])
    credential_ref = StringField("Credential reference", validators=[Optional()])
    authoring_writable = BooleanField(
        "Source authoring (edit native definitions)", default=True)
    report_writable = BooleanField(
        "Report write-back (publish execution reports to this "
        "repository)", default=False)


class SuiteForm(FlaskForm):
    name = StringField("Suite name", validators=[DataRequired(), Length(max=128)])
    description = TextAreaField("Description", validators=[Optional()])
    binding_id = StringField("Source binding", validators=[Optional()])
    case_refs = SelectMultipleField("Test cases", validators=[Optional()])


class ScheduleForm(FlaskForm):
    name = StringField("Schedule name",
                       validators=[DataRequired(), Length(max=128)])
    description = TextAreaField("Description", validators=[Optional()])
    target_type = SelectField("Target", choices=[("suite", "Suite")])
    target_id = SelectField("Runs", validators=[DataRequired()])
    kind = SelectField("Kind", choices=[("once", "Once"),
                                        ("interval", "Repeating")])
    run_at = StringField("First run (UTC, YYYY-MM-DD HH:MM)",
                         validators=[Optional()])
    interval_minutes = IntegerField("Every N minutes", default=60)
    execution_profile = StringField("Execution profile",
                                    default="default")
    browser_type = SelectField("Browser", choices=BROWSER_CHOICES,
                               default="Chrome (headless)")
    remote_webdriver_url = StringField(
        "Remote WebDriver URL", validators=[Optional(), Length(max=512)])
    remote_webdriver_type = StringField(
        "WebDriver driver type", validators=[Optional(), Length(max=64)])
    timeout_seconds = IntegerField(
        "Timeout (seconds)", validators=[Optional()],
        default=3600)
    runner_id = SelectField("Runner", validators=[Optional()],
                            choices=[])
    runtime_id = SelectField("KRE installation", validators=[Optional()],
                             choices=[])
    overlap_policy = SelectField(
        "Overlap", choices=[("allow", "Allow overlap"),
                            ("skip", "Skip if previous run active")],
        default="allow")
    misfire_policy = SelectField(
        "Missed fire", choices=[("late", "Run once late"),
                                ("skip", "Skip if past interval")],
        default="late")


class FrameworkProjectForm(FlaskForm):
    """Onboard a framework project inside a binding (2.7.0). The
    framework selector picks the discovery adapter — it never
    auto-detects or overrides the user's choice. All paths are
    binding-scope relative."""
    name = StringField("Project display name",
                       validators=[DataRequired(), Length(max=128)])
    framework = SelectField("Framework / runner",
                            validators=[DataRequired()])
    project_root = StringField(
        "Project root (relative to binding scope, '.' allowed)",
        validators=[Optional(), Length(max=512)])
    workdir = StringField("Working directory (default: project root)",
                          validators=[Optional(), Length(max=512)])
    config_file = StringField(
        "Framework config file (pytest.ini / cypress.config.js / "
        "playwright.config.ts / .prj …)",
        validators=[Optional(), Length(max=512)])
    test_roots = TextAreaField(
        "Test roots (one per line; '.' = scope root)",
        validators=[Optional()])
    include = TextAreaField(
        "Include patterns (one per line, e.g. **/*.spec.ts)",
        validators=[Optional()])
    exclude = TextAreaField("Exclude patterns (one per line)",
                            validators=[Optional()])
    feature_roots = TextAreaField(
        "Feature-file roots — BDD only (one per line)",
        validators=[Optional()])
    stepdef_roots = TextAreaField(
        "Step-definition/binding roots — BDD only (one per line)",
        validators=[Optional()])
    support_roots = TextAreaField(
        "Resource/fixture/support roots (informational)",
        validators=[Optional()])


def reject_url_password(url: str) -> str:
    """Reject credentials embedded in the URL (`user:pass@host`).
    Username-only SSH forms (`git@host:`, `ssh://user@host`) stay
    valid. Returns an error string or ''."""
    import re
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^@/]*)@", url)
    if m and ":" in m.group(1):
        return ("URL must not contain an embedded password "
                "(user:pass@host) — use a credential reference")
    return ""


class PlainForm(FlaskForm):
    """CSRF-only submit (sync/cancel/release actions)."""
    pass
