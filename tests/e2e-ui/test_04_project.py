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
    page.locator("details.add-block summary, summary",
                 has_text=re.compile(r"binding|Add", re.I)).last.click()
    bform = page.locator("form.add-form").last
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
