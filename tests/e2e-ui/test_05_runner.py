"""Flow 5 — runner + worker: add runner via UI, issue its PB password
via UI, download the shipped installer via UI, then run it (the one
shell step the plan allows) and confirm the worker shows online."""
import re
import subprocess
import pytest
from playwright.sync_api import expect

PB_PORT = 9989


def test_add_runner_and_license_slots(admin_page):
    page = admin_page
    page.goto("/system/infrastructure")
    expect(page.locator("h1")).to_contain_text("KRE installations")
    if "ui-bb-worker" in page.inner_text("body"):
        return  # idempotent across suite reruns
    page.locator("summary", has_text="Add execution target").click()
    form = page.locator(
        "details.block-details:has(summary:text('Add execution "
        "target'))")
    form.locator("input[name=name]").fill("ui-bb-worker")
    form.locator(
        "input[name=target_type][value=buildbot-worker]").check()
    form.locator("input[name=os_arch]").fill("linux/amd64")
    slots = form.locator("input[name=max_slots]")
    if slots.count():
        slots.fill("2")
    lic = form.locator("input[name=license_slots]")
    if lic.count():
        lic.fill("1")
    form.locator("button[type=submit]").click()
    expect(page.locator("body")).to_contain_text("ui-bb-worker")


def test_issue_password_download_and_install(admin_page):
    """New-admin path: UI issues the one-time PB password, UI downloads
    the shipped Linux worker bundle; install itself is a shell step."""
    page = admin_page
    page.goto("/system/infrastructure")

    row = page.locator("tr", has_text="ui-bb-worker").first
    # already-attached: a reissued password invalidates the running
    # worker's credentials — skip issuance on reruns
    if "ok" in row.inner_text() or "connected" in row.inner_text():
        return
    # Issue the PB password — plaintext shown once in the flash banner
    row.locator("summary", has_text="Manage").click()
    with page.expect_response("**/issue-bb-secret"):
        row.locator("button", has_text="Issue password").click()
    m = re.search(r"copy now: (\S+)", page.inner_text("body"))
    assert m, "issued PB password not visible in flash"
    open("/tmp/ui-worker-pw", "w").write(m.group(1) + "\n")
    # workername must come from THIS row — other rows show their own
    worker = re.search(r"workername:\s*(\S+)", row.inner_text())
    assert worker, "workername not shown on runner row"
    open("/tmp/ui-worker-name", "w").write(worker.group(1))

    # Download the shipped Linux worker installer through the portal
    with page.expect_download() as dl:
        page.locator("a", has_text="Download").nth(1).click()
    dl.value.save_as("/tmp/to-linux-worker.tar.gz")

    # install — shell step per instructions. The interpreter must be a
    # standalone tree under /opt: a uv-managed python inside a user's
    # private $HOME leaves the worker service user unable to traverse
    # it (Permission denied on venv/bin/python).
    # a stale service carries a baked-in workername/password from an
    # earlier runner — always reinstall with the freshly issued creds
    subprocess.run(["sudo", "systemctl", "stop",
                    "to-buildbot-worker"], check=False)
    subprocess.run(["sudo", "rm", "-rf", "/opt/to-buildbot-worker",
                    "/etc/systemd/system/to-buildbot-worker.service",
                    "/var/lib/to-buildbot-worker"],
                   check=False)
    subprocess.run(["sudo", "systemctl", "daemon-reload"],
                   check=False)
    r = subprocess.run(
        ["sudo", "env",
         "PATH=/opt/py312-standalone/bin:/usr/local/sbin:"
         "/usr/local/bin:/usr/bin:/usr/sbin:/sbin:/bin",
         "bash", "-c",
         "cd /tmp && tar xzf to-linux-worker.tar.gz && "
         "bash install_linux_worker.sh --master 127.0.0.1:%d "
         "--name $(cat /tmp/ui-worker-name) "
         "--passwd-file /tmp/ui-worker-pw" % PB_PORT],
        capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]


def test_worker_shows_online(admin_page):
    """Admin connection check on the row — the real path that flips a
    worker's health once its PB session is attached."""
    page = admin_page
    page.goto("/system/infrastructure")
    row = page.locator("tr", has_text="ui-bb-worker").first
    row.locator("button", has_text="Test").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text("connected")
    expect(page.locator("tr", has_text="ui-bb-worker").first
           ).to_contain_text("ok")
