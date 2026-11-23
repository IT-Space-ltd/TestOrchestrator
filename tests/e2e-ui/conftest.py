"""Playwright UI acceptance for the installed TestOrchestrator package.

Isolation rules:
- Runs ONLY against an already-installed package (BASE_URL env, default
  https://localhost — the package's own Cheroot self-signed TLS).
- ignore_https_errors is set ONLY on the test browser context.
- Throwaway credentials only — traces/screenshots may capture page
  content; artifacts are not committed.
- No fixed sleeps: expect()/auto-waiting everywhere.
"""
import os
import pathlib
import pytest

BASE_URL = os.environ.get("TO_UI_BASE_URL", "https://localhost")
STATE_DIR = pathlib.Path(
    os.environ.get("TO_UI_STATE_DIR", "/tmp/to-ui-state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)

ADMIN_USER = os.environ.get("TO_UI_ADMIN_USER", "Admin")
BOOTSTRAP_PW = os.environ.get("TO_UI_BOOTSTRAP_PW", "Admin")
ADMIN_PW = os.environ.get(
    "TO_UI_ADMIN_PW", "UiThrowaway-Passw0rd!")  # throwaway, never real

ADMIN_STATE = STATE_DIR / "admin-state.json"


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


def _do_login(page, user, pw):
    page.goto("/login")
    page.fill("input[name=username]", user)
    page.fill("input[name=password]", pw)
    page.click("button[type=submit]")


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Self-signed package cert — scoped to the TEST context only.
    base_url lets every test use relative paths so the suite can be
    pointed at any install via TO_UI_BASE_URL."""
    return {**browser_context_args,
            "ignore_https_errors": True,
            "base_url": BASE_URL}


@pytest.fixture(scope="session")
def admin_state(browser, base_url):
    """Login once through the real UI; every other test reuses this
    storage state (session cookie), never the password path.

    Idempotent: on a fresh install bootstrap Admin/Admin forces the
    password change; on reruns the throwaway replacement authenticates
    directly."""
    if ADMIN_STATE.exists():
        # a saved cookie can go stale — session_version rolls on
        # upgrade/restore — validate before trusting it
        ctx = browser.new_context(ignore_https_errors=True,
                                  base_url=BASE_URL,
                                  storage_state=str(ADMIN_STATE))
        page = ctx.new_page()
        page.goto("/system/users")
        stale = "/login" in page.url
        ctx.close()
        if stale:
            ADMIN_STATE.unlink()
    if not ADMIN_STATE.exists():
        ctx = browser.new_context(ignore_https_errors=True,
                                  base_url=BASE_URL)
        page = ctx.new_page()
        _do_login(page, ADMIN_USER, BOOTSTRAP_PW)
        try:
            page.wait_for_url(
                lambda u: "/login" not in u, timeout=15000)
        except Exception:
            # bootstrap already replaced on a previous run
            _do_login(page, ADMIN_USER, ADMIN_PW)
            page.wait_for_url(lambda u: "/login" not in u,
                              timeout=15000)
        if "/change-password" in page.url:
            page.fill("input[name=current_password]", BOOTSTRAP_PW)
            page.fill("input[name=new_password]", ADMIN_PW)
            page.fill("input[name=confirm_password]", ADMIN_PW)
            page.click("button[type=submit]")
            page.wait_for_url(lambda u: "/change-password" not in u)
        ctx.storage_state(path=str(ADMIN_STATE))
        ctx.close()
    return str(ADMIN_STATE)


@pytest.fixture
def admin_page(browser, admin_state):
    ctx = browser.new_context(ignore_https_errors=True,
                              base_url=BASE_URL,
                              storage_state=admin_state)
    page = ctx.new_page()
    yield page
    ctx.close()


def wait_for_text_after_reload(page, pattern, timeout_s=120):
    """Server-side state changes need a reload to be visible — poll with
    a deadline (assertion-driven; not a blind sleep)."""
    import re as _re
    import time as _t
    deadline = _t.monotonic() + timeout_s
    rx = _re.compile(pattern, _re.I) if isinstance(pattern, str) \
        else pattern
    while True:
        if rx.search(page.inner_text("body")):
            return True
        if _t.monotonic() > deadline:
            return False
        page.wait_for_timeout(500)
        page.reload()
