"""Flow 7 — failure paths: license-kind failure, UNKNOWN reconciliation
releasing capacity, offline worker."""
import re
from playwright.sync_api import expect
from conftest import wait_for_text_after_reload
from test_06_execution import wait_for_table_state


def test_unknown_reconciliation_releases_capacity(admin_page):
    """UNKNOWN executions hold runner slots by design — resolve each
    through the UI (confirm stopped + note), the operator path."""
    page = admin_page
    page.goto("/executions")
    for _ in range(6):
        row = page.locator("tr", has_text=re.compile(
            r"unknown", re.I)).first
        if row.count() == 0:
            break
        row.locator("a[href*='/executions/']").first.click()
        if "unknown" not in page.inner_text("body").lower():
            break
        # confirm_stopped is a hidden "yes" already carried by the form
        page.locator("input[name=reason], textarea[name=reason]"
                     ).fill("ui-acceptance: verified process stopped")
        page.locator("button[type=submit]", has_text=re.compile(
            r"Resolve UNKNOWN", re.I)).click()
        page.wait_for_load_state("load")
        page.goto("/executions")


def test_license_failure_kind(admin_page):
    """The seeded fake-KRE run must classify as a license failure —
    the run was queued behind UNKNOWN capacity holds until they were
    resolved."""
    page = admin_page
    page.goto("/executions")
    assert wait_for_table_state(page, 240, "FAILED"), \
        "license-fail run never terminated"
    failed = page.locator("tr", has_text=re.compile("failed", re.I)
                          ).first
    failed.locator("a[href*='/executions/']").first.click()
    expect(page.locator("body")).to_contain_text(
        re.compile(r"licen[cs]e", re.I))


def test_offline_worker_shows_offline(admin_page):
    """Seeded never-attached worker: Test marks it unreachable — the
    offline signal a new administrator sees."""
    page = admin_page
    page.goto("/system/infrastructure")
    expect(page.locator("body")).to_contain_text("ui-offline-worker")
    row = page.locator("tr", has_text="ui-offline-worker").first
    row.locator("button", has_text="Test").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text(
        re.compile(r"not connected|unreachable", re.I))
    expect(row).to_contain_text(re.compile(
        r"awaiting registration|unreachable", re.I))
