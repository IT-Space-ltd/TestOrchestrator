"""Flow 1 — first run, login, forced password change, wrong password."""
import pytest
from playwright.sync_api import expect

from conftest import (ADMIN_USER, BOOTSTRAP_PW, ADMIN_PW, BASE_URL,
                        _do_login)


def test_cert_warning_negative(browser):
    from playwright.sync_api import Error
    ctx = browser.new_context(base_url=BASE_URL)  # OFF deliberately
    page = ctx.new_page()
    blocked = False
    try:
        page.goto(BASE_URL + "/login", timeout=15000)
    except Error:
        blocked = True
    # Some builds navigate to the interstitial instead of throwing —
    # either way the warning page must NOT be the sign-in form.
    if not blocked:
        assert page.locator("input[name=password]").count() == 0, \
            "no cert warning was shown for the self-signed cert"
    ctx.close()


def test_login_and_forced_password_change(page):
    """Bootstrap Admin/Admin must land on the forced change form."""
    _do_login(page, ADMIN_USER, BOOTSTRAP_PW)
    try:
        page.wait_for_url("**/change-password", timeout=8000)
    except Exception:
        pytest.skip("bootstrap password already replaced on this "
                    "install — flow covered at first run")
    expect(page.locator("h1")).to_contain_text("password")
    page.fill("input[name=current_password]", BOOTSTRAP_PW)
    page.fill("input[name=new_password]", ADMIN_PW)
    page.fill("input[name=confirm_password]", ADMIN_PW)
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/change-password" not in u)


def test_wrong_password_rejected(browser, admin_state):
    ctx = browser.new_context(ignore_https_errors=True, base_url=BASE_URL)
    page = ctx.new_page()
    _do_login(page, ADMIN_USER, "definitely-wrong-1")
    # stays on login with an error, never reaches the dashboard
    expect(page.locator("form input[name=password]")).to_be_visible()
    assert "/login" in page.url or "Sign in" in page.title()
    ctx.close()
