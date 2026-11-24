"""Flow 4 — project, git source, credential, secret masking."""
import re
from playwright.sync_api import expect


def test_create_credential_masked(admin_page):
    page = admin_page
    page.goto("/system/secrets")
    expect(page.locator("h1")).to_contain_text("Credentials")
    # open the create block (not the "Example" details above it)
    page.locator("details.add-block summary").click()
    form = page.locator("details.add-block")
    form.locator("input[name=name]").fill("ui-git-cred")
    form.locator("input[name=kind][value=git]").check()
    form.locator("textarea[name=value], input[name=value]").first.fill(
        "ui-throwaway-secret-12345")
    form.locator("button[type=submit]", has_text="Store encrypted"
                 ).click()
    expect(page.locator("body")).to_contain_text("ui-git-cred")
    # the stored value must never render back on the page
    assert "ui-throwaway-secret-12345" not in page.content()


def test_create_project_and_binding(admin_page):
    page = admin_page
    page.goto("/projects")
    expect(page.locator("h1")).to_contain_text("Projects")
    page.locator("details.add-block summary").click()
    form = page.locator("details.add-block")
    form.locator("input[name=name]").fill("ui-proj")
    form.locator("textarea[name=description]").fill(
        "ui acceptance project")
    form.locator("button[type=submit]", has_text="Apply").click()
    expect(page.locator("body")).to_contain_text("ui-proj")

    # git source binding lives on the project's Git bindings tab
    page.goto("/projects")
    page.locator("a", has_text="ui-proj").first.click()
    page.goto(page.url + "?tab=bindings")
    page.locator("#panel-bindings summary",
                 has_text="Add new binding").click()
    bform = page.locator("#panel-bindings form.add-form").last
    bform.locator("input[name=name]").fill("ui-bind")
    bform.locator("input[name=url]").fill(
        "file:///opt/ui-repo")
    bform.locator("input[name=ref]").fill("main")
    bform.locator("button[type=submit]").click()
    page.wait_for_load_state("load")
    expect(page.locator("body")).to_contain_text("ui-bind")

    # BOUNDARY: repo discovery is Katalon-.prj-only in 2.6.0 — the
    # pytest fixture repo has no .prj, so Sync cannot discover items.
    # Executions use the seeded discovered item (test data); the real
    # Katalon discovery path needs a Katalon project, which requires
    # assets this suite must not ship.

def test_vm_e2e_project_binding_and_real_sync(admin_page):
    """VM-E2E project + file:// binding created via UI, Sync performs a
    real clone + .prj discovery — Katalon items appear without any
    seeding (only the non-.prj item kinds are seeded separately)."""
    page = admin_page
    page.goto("/projects")
    if "VM-E2E" not in page.inner_text("body"):
        page.locator("details.add-block summary").click()
        form = page.locator("details.add-block")
        form.locator("input[name=name]").fill("VM-E2E")
        form.locator("textarea[name=description]").fill(
            "host-server/VM-worker acceptance")
        form.locator("button[type=submit]", has_text="Apply").click()
        expect(page.locator("body")).to_contain_text("VM-E2E")
    page.goto("/projects")
    page.locator("a", has_text="VM-E2E").first.click()
    page.goto(page.url.split("?")[0] + "?tab=bindings")
    if "vm-bind" not in page.inner_text("body"):
        summary = page.locator(
            "#panel-bindings summary", has_text="Add new binding")
        summary.last.click()
        bform = page.locator("#panel-bindings form.add-form").last
        bform.locator("input[name=name]").fill("vm-bind")
        bform.locator("input[name=url]").fill(
            "file:///var/lib/testorchestrator/fixture")
        bform.locator("input[name=ref]").fill("master")
        bform.locator("button[type=submit]").click()
        page.wait_for_load_state("load")
        expect(page.locator("body")).to_contain_text("vm-bind")
    # trigger Sync and wait for the discovered inventory to appear
    panel = page.locator("#panel-bindings")
    sync_btn = panel.locator("button", has_text="Sync")
    if sync_btn.count():
        sync_btn.first.click()
        page.wait_for_load_state("load")
    page.goto("/projects")
    page.locator("a", has_text="VM-E2E").first.click()
    page.goto(page.url.split("?")[0] + "?tab=inventory")
    from conftest import wait_for_text_after_reload
    assert wait_for_text_after_reload(page, "TS1", 120), \
        "discovery did not produce TS1 after sync"
    expect(page.locator("body")).to_contain_text("TS1")
