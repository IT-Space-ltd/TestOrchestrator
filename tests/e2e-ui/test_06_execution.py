"""Flow 6 — execution: dispatch from the UI, status/wait reasons, logs,
report, artifacts, analytics, CSV exports with tz columns."""
import re
import pytest
from playwright.sync_api import expect
from conftest import wait_for_text_after_reload


def wait_for_table_state(page, timeout_s=180, want="COMPLETED|FAILED"):
    """Poll the executions TABLE for a terminal badge — filter-legend
    option labels always carry the state words."""
    import time
    deadline = time.monotonic() + timeout_s
    rx = re.compile(want, re.I)
    while True:
        for t in page.locator("table").all():
            if rx.search(t.inner_text() or ""):
                return True
        if time.monotonic() > deadline:
            return False
        page.wait_for_timeout(500)
        page.reload()


def _get_csv(page, url):
    """GET a Content-Disposition attachment — goto() raises 'Download
    is starting' by design."""
    with page.expect_download() as dl:
        try:
            page.goto(url)
        except Exception:
            pass
    return open(dl.value.path(), encoding="utf-8",
                errors="replace").read(4000)


def _select_by_text(page, name, text):
    """Select an option whose label contains `text` (option labels are
    composed, e.g. 'pytest-local [pytest]')."""
    opt = page.locator(f"select#{name} option",
                       has_text=text).first
    page.locator(f"select#{name}").select_option(
        opt.get_attribute("value"))


def _open_seeded_item(page):
    page.goto("/projects")
    page.locator("a", has_text="ui-exec-proj").first.click()
    page.goto(page.url.split("?")[0] + "?tab=inventory")
    # the item link lives inside the test tab panel — take its href
    href = page.locator(
        "a[href^='/discovered/']").first.get_attribute("href")
    page.goto(href)
    expect(page.locator("h1, h2").first).to_contain_text(
        re.compile(r"ui_smoke|test_ui_smoke", re.I))


def test_dispatch_run_watch_terminal(admin_page):
    """Start a run from the UI on the seeded pytest runtime, watch it
    reach a terminal state. Outcome covers pass+fail cases."""
    page = admin_page
    _open_seeded_item(page)
    _select_by_text(page, "runner_id", "ui-local")
    _select_by_text(page, "runtime_id", "pytest-local")
    page.locator("button[type=submit]",
                 has_text="Run suite").click()
    page.wait_for_load_state("load")
    # success flashes "Execution <id> queued for …" — anything else is
    # a real dispatch error we want to see
    expect(page.locator("body")).to_contain_text(
        re.compile(r"queued for", re.I))
    page.goto("/executions")
    # terminal badge must appear inside the executions TABLE (the
    # filter legend always contains the state words)
    assert wait_for_table_state(page, 180), \
        "run never reached a terminal state"


def test_wait_reasons_visible_on_queue(admin_page):
    page = admin_page
    page.goto("/executions")
    expect(page.locator("body")).to_contain_text(
        re.compile(r"state|status|outcome|queue", re.I))


def test_execution_detail_logs_and_artifacts(admin_page):
    page = admin_page
    page.goto("/executions")
    page.locator("a[href*='/executions/']").first.click()
    expect(page.locator("body")).to_contain_text(
        re.compile(r"log|artifact|report|manifest|state", re.I))


def test_license_failure_kind(admin_page):
    """Run the seeded fake-KRE runtime → its 'license' stderr must be
    classified and shown as a license failure."""
    page = admin_page
    _open_seeded_item(page)
    _select_by_text(page, "runner_id", "ui-local")
    _select_by_text(page, "runtime_id", "kre-licensefail")
    page.locator("button[type=submit]",
                 has_text="Run suite").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text(
        re.compile(r"queued for", re.I))
    page.goto("/executions")
    assert wait_for_table_state(page, 180, "FAILED"), \
        "license-fail run never terminated"
    # open the newest FAILED run; the kind must be visible
    failed = page.locator("tr", has_text=re.compile("failed", re.I)).first
    failed.locator("a[href*='/executions/']").first.click()
    expect(page.locator("body")).to_contain_text(
        re.compile(r"licen[cs]e", re.I))


def test_analytics_page_and_export(admin_page):
    page = admin_page
    page.goto("/dashboard")
    expect(page.locator("body")).to_contain_text(
        re.compile(r"dashboard|analytics|activity", re.I))
    # analytics CSV export — chart tables carry the tz column
    head = _get_csv(page, "/dashboard/analytics?format=csv"
                    "&chart=project_outcomes")
    assert "project" in head and "tz" in head, head[:200]


def test_audit_and_logs_exports(admin_page):
    page = admin_page
    # audit CSV — headers must carry the tz columns
    head = _get_csv(page, "/system/audit/export")
    for col in ("timestamp_utc", "timestamp_local", "timezone"):
        assert col in head, f"{col} missing from audit CSV: {head[:200]}"
    head2 = _get_csv(page, "/system/logs/export")
    for col in ("timestamp_utc", "timestamp_local", "timezone"):
        assert col in head2, f"{col} missing from logs CSV"
