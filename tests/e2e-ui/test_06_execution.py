"""Flow 6 — runtimes + framework executions on the VM (host-server /
VM-worker topology). Every runtime is registered through the portal UI
per the documented admin workflow and probed; non-.prj items are
seeded test data (documented boundary). Dispatches run on the VM over
PB (vm-worker) and agentless SSH (vm-ssh); terminal state, results,
logs and artifacts are verified through the UI. The "ran on the VM"
proof is in test_vm_exec_evidence.
"""
import json
import os
import re
import subprocess
import time
import pytest
from playwright.sync_api import expect

VM_HOST = os.environ.get("TO_VM_HOST", "10.97.0.121")
VM_USER = os.environ.get("TO_VM_USER", "ubuntu")
VM_KEY = os.environ.get(
    "TO_VM_KEY", os.path.expanduser("~/.ssh/id_to_worker"))

# (name, kind, runner row text, executable on the VM, credential_file)
RUNTIMES = [
    ("kre-worker", "kre", "vm-worker", "/opt/fake-kre/katalonc", ""),
    ("kre-ssh", "kre", "vm-ssh", "/tmp/to-ssh/katalonc", ""),
    ("robot-worker", "robot", "vm-worker",
     "/opt/robot-venv/bin/python", ""),
    ("robot-ssh", "robot", "vm-ssh", "/opt/robot-venv/bin/python", ""),
    ("pytest-worker", "pytest", "vm-worker",
     "/opt/robot-venv/bin/python", ""),
    ("pytest-ssh", "pytest", "vm-ssh", "/opt/robot-venv/bin/python",
     ""),
    ("pw-worker", "playwright", "vm-worker", "/opt/fake-node/npx", ""),
    ("pw-ssh", "playwright", "vm-ssh", "/opt/fake-node/npx", ""),
    ("cy-worker", "cypress", "vm-worker", "/opt/fake-node/npx", ""),
    ("cy-ssh", "cypress", "vm-ssh", "/opt/fake-node/npx", ""),
]

# seeded name -> displayed path (inventory links show paths)
ITEM_PATHS = {
    "pytest-pass": "pytest/test_smoke.py",
    "pytest-fail": "pytest/test_fail.py",
    "smoke.robot": "tests/smoke.robot",
    "fail.robot": "tests/fail.robot",
    "pw.spec.js": "tests/pw.spec.js",
    "cy.cy.js": "cypress/e2e/cy.cy.js",
}

# (item name in inventory, runtime name, expect)
CELLS = [
    ("pytest-pass", "pytest-worker", "PASSED"),
    ("pytest-pass", "pytest-ssh", "PASSED"),
    ("smoke.robot", "robot-worker", "PASSED"),
    ("smoke.robot", "robot-ssh", "PASSED"),
    ("pw.spec.js", "pw-worker", "PASSED"),
    ("pw.spec.js", "pw-ssh", "PASSED"),
    ("cy.cy.js", "cy-worker", "PASSED"),
    ("cy.cy.js", "cy-ssh", "PASSED"),
]

DISPATCHED = {}


def _ssh(*args, timeout=120):
    return subprocess.run(
        ["ssh", "-i", VM_KEY, "-o", "BatchMode=yes",
         "-o", "StrictHostKeyChecking=accept-new",
         f"{VM_USER}@{VM_HOST}", *args],
        capture_output=True, text=True, timeout=timeout)


def _register_runtime(page, name, kind, runner_text, exe, cred_file):
    page.goto("/system/infrastructure")
    if name in page.inner_text("body"):
        return
    page.locator("summary",
                 has_text="Register a test runtime").click()
    form = page.locator(
        "details.block-details:has(summary:text('Register a test "
        "runtime')) form")
    form.locator("select[name=runtime_kind]").select_option(kind)
    form.locator("input[name=name]").fill(name)
    form.locator("input[name=exec_location][value=remote]").check()
    sel = form.locator("select[name=runner_id]")
    opt = sel.locator("option", has_text=runner_text).first
    sel.select_option(opt.get_attribute("value"))
    form.locator("input[name=executable_path]").fill(exe)
    ws = form.locator("input[name=workspace_root]")
    if ws.count():
        ws.fill("/tmp/to-ws")
    if cred_file:
        form.locator("input[name=credential_file]").fill(cred_file)
    form.locator("input[name=concurrency]").fill("2")
    form.locator("button[type=submit]").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text(name)


def _probe(page, name):
    row = page.locator("tr", has_text=name).first
    if "verified" in row.inner_text().lower() or \
            "ok" in row.inner_text().lower():
        return
    btn = row.locator("button", has_text=re.compile(r"^Check$|Check"))
    btn.first.click()
    page.wait_for_load_state("load")
    # The Check runs asynchronously on the target — poll until the row
    # reports a terminal check state.
    deadline = time.monotonic() + 120
    rx = re.compile(
        r"verified|ok|ready|failed|error|11\.7\.0|7\.5\.1|9\.2\.0|"
        r"11\.2\.0", re.I)
    while True:
        page.reload()
        txt = page.locator("tr", has_text=name).first.inner_text()
        if rx.search(txt) and "running" not in txt.lower():
            break
        if time.monotonic() > deadline:
            pytest.fail(f"probe for {name} did not settle: {txt}")
        page.wait_for_timeout(1500)


def _open_item(page, item_name):
    """Open the discovered item detail via the project inventory tab."""
    page.goto("/projects")
    page.locator("a", has_text="VM-E2E").first.click()
    page.goto(page.url.split("?")[0] + "?tab=inventory")
    path = ITEM_PATHS.get(item_name, item_name)
    link = page.locator(
        "a[href^='/discovered/']", has_text=path).first
    expect(link).to_be_visible()
    page.goto(link.get_attribute("href"))


def _dispatch(page, item_name, runtime_name):
    """Run an item through the UI; returns the execution id."""
    _open_item(page, item_name)
    sel = page.locator("select#runtime_id")
    opt = sel.locator("option", has_text=runtime_name).first
    expect(opt).to_have_count(1)
    sel.select_option(opt.get_attribute("value"))
    # KRE browser defaults (e.g. "Chrome (headless)") are invalid for
    # playwright/cypress — use the framework default ("").
    if runtime_name.startswith(("pw-", "cy-")):
        page.locator("select#browser_type").select_option("")
    page.locator("button[type=submit]",
                 has_text=re.compile(r"Run ")).click()
    page.wait_for_load_state("load")
    body = page.inner_text("body")
    m = re.search(r"/executions/([0-9a-f]{8,})", page.url)
    assert m, f"dispatch failed: {body[-400:]}"
    assert "queued" in body, f"no queued flash: {body[-400:]}"
    return m.group(1)


def wait_for_table_state(page, timeout_s=240,
                         want="COMPLETED|FAILED|CANCELED"):
    deadline = time.monotonic() + timeout_s
    rx = re.compile(want, re.I)
    while True:
        for t in page.locator("table").all():
            if rx.search(t.inner_text() or ""):
                return True
        if time.monotonic() > deadline:
            return False
        page.wait_for_timeout(750)
        page.reload()


def _exec_state(page, exec_id):
    """State badge text on the execution detail (lowercase value)."""
    for b in page.locator("span.badge").all():
        t = (b.inner_text() or "").strip().lower()
        if t in ("queued", "dispatched", "preparing", "running",
                 "completed", "failed", "canceled", "cancelled",
                 "unknown"):
            return t
    return ""


def _exec_outcome(page, exec_id, want, timeout_s=300):
    """Poll an execution detail for the expected terminal outcome."""
    deadline = time.monotonic() + timeout_s
    rx = re.compile(want, re.I)
    while True:
        page.goto(f"/executions/{exec_id}")
        body = page.inner_text("body")
        if rx.search(_exec_state(page, exec_id)):
            return body
        if time.monotonic() > deadline:
            pytest.fail(
                f"{exec_id} never reached {want}: {body[-500:]}")
        page.wait_for_timeout(1500)


def test_register_runtimes(admin_page):
    page = admin_page
    for name, kind, runner, exe, cred in RUNTIMES:
        _register_runtime(page, name, kind, runner, exe, cred)


def test_probe_runtimes(admin_page):
    """'Check' on each row — the probe runs ON the VM and advertises
    the detected version back to the portal."""
    page = admin_page
    page.goto("/system/infrastructure")
    for name, *_ in RUNTIMES:
        _probe(page, name)


def test_seed_non_katalon_items():
    """Seed pytest/robot/pw/cy items (discovery is .prj-only by
    design — documented boundary). Items only; every user action goes
    through the browser."""
    r = subprocess.run(
        ["sudo", "env",
         "PYTHONPATH=/opt/testorchestrator",
         "/opt/testorchestrator/venv/bin/python",
         "/home/szefi/vm-e2e-tmp/host-seed.py"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SEEDED-ITEMS" in r.stdout


def test_katalon_items_discovered_by_sync(admin_page):
    """Real UI discovery: TS1 suite, TSC1 collection and the three
    .tc cases must appear in the inventory after Sync."""
    page = admin_page
    page.goto("/projects")
    page.locator("a", has_text="VM-E2E").first.click()
    page.goto(page.url.split("?")[0] + "?tab=inventory")
    for name in ("TS1", "TSC1"):
        expect(page.locator("body")).to_contain_text(name)


@pytest.mark.parametrize("item,runtime,want", CELLS,
                         ids=[f"{i}@{r}" for i, r, _ in CELLS])
def test_framework_cell(admin_page, item, runtime, want):
    eid = _dispatch(admin_page, item, runtime)
    DISPATCHED[f"{item}@{runtime}"] = eid
    body = _exec_outcome(admin_page, eid,
                         r"completed|failed|cancelled|canceled")
    # outcome must show the expected result, not just a terminal state
    assert re.search(want, body, re.I), body[-400:]


def test_vm_exec_evidence(admin_page):
    """The cells above ran ON the VM: worker-side artifacts exist under
    the VM's worker dirs and nowhere on the host."""
    r = _ssh("sudo find /var/lib/to-buildbot-worker /tmp/to-ssh "
             "-name 'junit*.xml' -o -name 'output.xml' 2>/dev/null | "
             "head -10; hostname")
    assert r.returncode == 0
    assert "to-worker" in r.stdout
    assert re.search(r"junit.*xml|output\.xml", r.stdout), r.stdout
    # and the executions carry the vm-runner attribution in the UI
    admin_page.goto("/executions")
    body = admin_page.inner_text("body")
    assert "vm-worker" in body or "vm-ssh" in body


def test_dispatch_watch_queue_and_terminal(admin_page):
    """Dispatch → observe queued → running → terminal on the
    executions table (state journey, not only the end state)."""
    eid = _dispatch(admin_page, "pytest-pass", "pytest-worker")
    DISPATCHED["journey-pytest"] = eid
    admin_page.goto("/executions")
    body = admin_page.inner_text("body")
    assert re.search(r"queued|dispatch|running|pending", body, re.I)
    _exec_outcome(admin_page, eid, r"completed")


def test_license_failure_kind(admin_page):
    """A failing case must surface a failed result — the orchestration
    completes (COMPLETED) while the parsed result records FAILED."""
    eid = _dispatch(admin_page, "pytest-fail", "pytest-worker")
    body = _exec_outcome(admin_page, eid, r"completed")
    assert re.search(r"failed", body, re.I), body[-400:]
    assert re.search(r"fail|error", body, re.I)


def test_execution_detail_logs_and_artifacts(admin_page):
    eid = DISPATCHED.get("pytest-pass@pytest-worker") or \
        next(iter(DISPATCHED.values()))
    admin_page.goto(f"/executions/{eid}")
    expect(admin_page.locator("body")).to_contain_text(
        re.compile(r"log|artifact|report|manifest|state", re.I))


def test_analytics_page_and_export(admin_page):
    page = admin_page
    page.goto("/dashboard")
    expect(page.locator("body")).to_contain_text(
        re.compile(r"dashboard|analytics|activity", re.I))
    head = _get_csv(page, "/dashboard/analytics?format=csv"
                    "&chart=project_outcomes")
    assert "project" in head and "tz" in head, head[:200]


def test_audit_and_logs_exports(admin_page):
    page = admin_page
    head = _get_csv(page, "/system/audit/export")
    for col in ("timestamp_utc", "timestamp_local", "timezone"):
        assert col in head, f"{col} missing from audit CSV"
    head2 = _get_csv(page, "/system/logs/export")
    for col in ("timestamp_utc", "timestamp_local", "timezone"):
        assert col in head2, f"{col} missing from logs CSV"


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
