"""Flow 2 — users & roles: create a Tester, restricted page shows 403."""
import re
import pytest
from playwright.sync_api import expect

TESTER_PW = "UiThrowaway-Tester99!"
TESTER_PW2 = "UiThrowaway-Tester88!"


def _login_tester(page):
    """Log in as the tester, tolerating whichever rotation is current,
    and completing the forced change once."""
    for pw in (TESTER_PW, TESTER_PW2):
        page.goto("/login")
        page.fill("input[name=username]", "ui-tester")
        page.fill("input[name=password]", pw)
        page.click("button[type=submit]")
        page.wait_for_load_state("load")
        if "/login" not in page.url:
            break
    if "/change-password" in page.url:
        new = TESTER_PW2 if pw == TESTER_PW else TESTER_PW
        page.fill("input[name=current_password]", pw)
        page.fill("input[name=new_password]", new)
        page.fill("input[name=confirm_password]", new)
        page.click("button[type=submit]")
        page.wait_for_load_state("load")



def test_create_tester_user(admin_page):
    page = admin_page
    page.goto("/system/users")
    expect(page.locator("h1")).to_contain_text("Users")
    page.locator("details.add-block summary").click()
    form = page.locator("details.add-block")
    form.locator("input[name=username]").fill("ui-tester")
    form.locator("input[name=display_name]").fill("UI Tester")
    form.locator("select[name=timezone]").select_option(
        "Europe/Budapest")
    form.locator("input[name=role][value=tester]").check()
    form.locator("input[name=temporary_password]").fill(TESTER_PW)
    page.locator("details.add-block button[type=submit]", has_text="Create").click()
    expect(page.locator("td", has_text="ui-tester").first).to_be_visible()


def test_tester_gets_403_on_admin_pages(browser):
    ctx = browser.new_context(ignore_https_errors=True,
                              base_url="https://localhost")
    page = ctx.new_page()
    _login_tester(page)
    for path in ("/system/users", "/system/secrets",
                 "/system/infrastructure"):
        page.goto(path)
        expect(page.locator("h1")).to_have_text(
            re.compile(r"403"))
    ctx.close()


def test_tester_cannot_reach_users_api(browser):
    ctx = browser.new_context(ignore_https_errors=True,
                              base_url="https://localhost")
    page = ctx.new_page()
    _login_tester(page)
    resp = page.request.get("/system/users")
    assert resp.status == 403
    ctx.close()
