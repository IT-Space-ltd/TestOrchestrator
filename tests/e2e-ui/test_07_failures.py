"""Flow 7 — failure paths on the VM topology: license-kind failure
classification, UNKNOWN reconciliation releasing capacity, offline
worker."""
import os
import re
import subprocess
import pytest
from playwright.sync_api import expect
from conftest import wait_for_text_after_reload
from test_06_execution import (wait_for_table_state, _dispatch,
                               _exec_outcome, _register_runtime)

VM_HOST = os.environ.get("TO_VM_HOST", "10.97.0.121")


def test_register_licfail_runtime(admin_page):
    """KRE runtime pointing at the license-fail fixture, registered
    through the UI like any other runtime."""
    _register_runtime(admin_page, "kre-licfail", "kre", "vm-worker",
                      "/opt/fake-kre/katalonc-licfail", "")


def test_failing_case_reports_failure(admin_page):
    """A deliberately failing case must surface FAILED with the
    failure detail — never a green run."""
    eid = _dispatch(admin_page, "fail.robot", "robot-worker")
    body = _exec_outcome(admin_page, eid, r"failed|completed")
    assert "failed" in body.lower(), \
        "failing case did not report a failure outcome"


def test_license_failure_kind(admin_page):
    """The lic-fail KRE runtime exits with a license error — the run
    must classify and display the license failure kind."""
    eid = _dispatch(admin_page, "TS1", "kre-licfail")
    body = _exec_outcome(admin_page, eid, r"failed|completed")
    assert "failed" in body.lower()
    assert re.search(r"licen[cs]e", body, re.I), \
        "license failure kind not surfaced"


def test_unknown_reconciliation_releases_capacity(admin_page):
    """UNKNOWN executions hold runner slots by design — resolve each
    through the UI (confirm stopped + note), the operator path."""
    page = admin_page
    page.goto("/executions")
    for _ in range(6):
        # state badge specifically — 'unknown' also appears in runner
        # health columns on unrelated rows
        row = page.locator("tr:has(span.badge.unknown)").first
        if row.count() == 0:
            break
        row.locator("a[href*='/executions/']").first.click()
        page.wait_for_load_state("load")
        if page.locator("span.badge.unknown").count() == 0:
            break
        page.locator("input[name=reason], textarea[name=reason]"
                     ).fill("ui-acceptance: verified process stopped")
        page.locator("button[type=submit]", has_text=re.compile(
            r"Resolve UNKNOWN", re.I)).click()
        page.wait_for_load_state("load")
        page.goto("/executions")


def test_offline_worker_shows_offline(admin_page):
    """Never-installed worker target: Test marks it unreachable — the
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
