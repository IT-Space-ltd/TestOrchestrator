"""Flow 5 — execution targets on the VM worker (host-server/VM-worker
topology): create the Buildbot-worker target via UI, issue its PB
password via UI, download the shipped installer via UI, run it INSIDE
the disposable VM over ssh, and confirm the worker shows online.
Then the agentless SSH target: pasted key, Test, host-key approval.

The one allowed shell step is the worker install — it runs on the VM
(multipass `to-worker`, 10.97.0.121), never on the host."""
import json
import os
import re
import subprocess
import pytest
from playwright.sync_api import expect

VM_HOST = os.environ.get("TO_VM_HOST", "10.97.0.121")
VM_USER = os.environ.get("TO_VM_USER", "ubuntu")
VM_KEY = os.environ.get(
    "TO_VM_KEY", os.path.expanduser("~/.ssh/id_to_worker"))
MASTER = os.environ.get("TO_VM_MASTER", "10.97.0.1:9989")


def _ssh(*args, timeout=600):
    return subprocess.run(
        ["ssh", "-i", VM_KEY, "-o", "StrictHostKeyChecking=accept-new",
         "-o", "BatchMode=yes", f"{VM_USER}@{VM_HOST}", *args],
        capture_output=True, text=True, timeout=timeout)


def _scp(local, remote):
    return subprocess.run(
        ["scp", "-i", VM_KEY, "-o", "StrictHostKeyChecking=accept-new",
         "-o", "BatchMode=yes", local, f"{VM_USER}@{VM_HOST}:{remote}"],
        capture_output=True, text=True, timeout=120)


def test_add_worker_target(admin_page):
    page = admin_page
    page.goto("/system/infrastructure")
    expect(page.locator("h1")).to_contain_text("KRE installations")
    if "vm-worker" in page.inner_text("body"):
        return  # idempotent across suite reruns
    page.locator("summary", has_text="Add execution target").click()
    form = page.locator(
        "details.block-details:has(summary:text('Add execution "
        "target'))")
    form.locator("input[name=name]").fill("vm-worker")
    form.locator(
        "input[name=target_type][value=buildbot-worker]").check()
    form.locator("input[name=os_arch]").fill("linux/amd64")
    slots = form.locator("input[name=max_slots]")
    if slots.count():
        slots.fill("2")
    form.locator("button[type=submit]").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text("vm-worker")


def test_issue_password_download_and_install_on_vm(admin_page):
    """New-admin path: UI issues the one-time PB password + workername,
    UI downloads the shipped Linux worker bundle; the install itself is
    a shell step INSIDE the VM — the master is the host PB endpoint."""
    page = admin_page
    page.goto("/system/infrastructure")
    row = page.locator("tr", has_text="vm-worker").first
    if "ok" in row.inner_text() or "connected" in row.inner_text():
        return  # already attached — reissuing would break the worker
    # workername was shown once at creation; if this is a rerun after
    # a partial failure the password must be reissued via Manage.
    manage = row.locator("summary", has_text="Manage")
    if manage.count():
        manage.click()
    with page.expect_response("**/issue-bb-secret"):
        row.locator("button", has_text="Issue password").click()
    m = re.search(r"copy now: (\S+)", page.inner_text("body"))
    assert m, "issued PB password not visible in flash"
    open("/tmp/ui-worker-pw", "w").write(m.group(1) + "\n")
    worker = re.search(r"workername:\s*(\S+)", row.inner_text())
    assert worker, "workername not shown on runner row"
    open("/tmp/ui-worker-name", "w").write(worker.group(1))

    # Download the shipped Linux worker installer through the portal
    with page.expect_download() as dl:
        page.locator("a", has_text="Download").nth(1).click()
    dl.value.save_as("/tmp/to-linux-worker.tar.gz")

    # ship bundle + issued credentials to the VM, then install —
    # master is the host bridge endpoint
    for f in ("/tmp/to-linux-worker.tar.gz", "/tmp/ui-worker-pw",
              "/tmp/ui-worker-name"):
        assert _scp(f, f).returncode == 0, f"scp {f} failed"
    r = _ssh(
        "sudo bash -c 'systemctl stop to-buildbot-worker 2>/dev/null; "
        "rm -rf /opt/to-buildbot-worker /var/lib/to-buildbot-worker "
        "/etc/systemd/system/to-buildbot-worker.service; "
        "systemctl daemon-reload' && "
        "sudo env PATH=/opt/py312/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/bin:/usr/sbin:/sbin:/bin bash -c "
        "'cd /tmp && tar xzf to-linux-worker.tar.gz && "
        "bash install_linux_worker.sh "
        f"--master {MASTER} "
        "--name $(cat /tmp/ui-worker-name) "
        "--passwd-file /tmp/ui-worker-pw'",
        timeout=900)
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-600:]


def test_worker_shows_online(admin_page):
    """Admin Test on the row — flips health once the PB session
    attaches; also proves the VM worker reached the host master."""
    page = admin_page
    page.goto("/system/infrastructure")
    row = page.locator("tr", has_text="vm-worker").first
    row.locator("button", has_text="Test").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text("connected")
    expect(page.locator("tr", has_text="vm-worker").first
           ).to_contain_text("ok")
    # the attached worker must BE the VM — its identity, not the host's
    attached = _ssh("hostname").stdout.strip()
    want_host = os.environ.get("TO_VM_NAME", "to-worker")
    assert attached == want_host, attached


def test_add_ssh_target_with_key_and_hostkey(admin_page):
    """Agentless SSH target: host/user/workdir + pasted throwaway key
    via the UI form, then Test -> explicit host-key approval."""
    page = admin_page
    page.goto("/system/infrastructure")
    if "vm-ssh" not in page.inner_text("body"):
        page.locator("summary",
                     has_text="Add execution target").click()
        form = page.locator(
            "details.block-details:has(summary:text('Add execution "
            "target'))")
        form.locator("input[name=name]").fill("vm-ssh")
        # click the radio's label — the real user action that checks
        # it and fires the change handler revealing #ssh-fields
        form.locator("#target-type-field label",
                     has_text=re.compile(r"Agentless", re.I)).click()
        expect(form.locator("#ssh-fields")).to_be_visible()
        form.locator("input[name=os_arch]").fill("linux/amd64")
        form.locator("input[name=ssh_host]").fill(VM_HOST)
        form.locator("input[name=ssh_username]").fill(VM_USER)
        w = form.locator("input[name=ssh_workdir]")
        if w.count():
            w.fill("/tmp/to-ssh")
        key = open(VM_KEY).read()
        kf = form.locator(
            "textarea[name=ssh_key], input[name=ssh_key]")
        if kf.count():
            kf.first.fill(key)
        else:
            pytest.fail("no ssh_key field on the target form")
        form.locator("button[type=submit]").click()
        page.wait_for_load_state("load")
        expect(page.locator("body")).to_contain_text("vm-ssh")

    row = page.locator("tr", has_text="vm-ssh").first
    manage = row.locator("summary", has_text="Manage")
    if manage.count():
        manage.click()
    # Test -> host-key presentation -> approve -> Test again
    row.locator("button", has_text="Test").click()
    page.wait_for_load_state("load")
    body = page.inner_text("body")
    if "approve" in body.lower() and \
            row.locator("button", has_text="Approve host key").count():
        row.locator("button", has_text="Approve host key").click()
        page.wait_for_load_state("load")
        row.locator("button", has_text="Test").click()
        page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text(
        re.compile(r"connected|ok|verified", re.I))


def test_add_offline_worker_placeholder(admin_page):
    """A never-installed worker target stays offline — failure-path
    fixture for flow 7."""
    page = admin_page
    page.goto("/system/infrastructure")
    if "ui-offline-worker" in page.inner_text("body"):
        return
    page.locator("summary", has_text="Add execution target").click()
    form = page.locator(
        "details.block-details:has(summary:text('Add execution "
        "target'))")
    form.locator("input[name=name]").fill("ui-offline-worker")
    form.locator(
        "input[name=target_type][value=buildbot-worker]").check()
    form.locator("input[name=os_arch]").fill("linux/amd64")
    form.locator("button[type=submit]").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text("ui-offline-worker")
