"""Flow 3 — settings: time-zone select, licence page, logging boundary."""
import re
from playwright.sync_api import expect


def test_timezone_select_saves(admin_page):
    """The curated IANA select (grouped like OS pickers) — pick a city
    and confirm it persists."""
    page = admin_page
    page.goto("/system/users")
    expect(page.locator("h1")).to_contain_text("Users")
    # open the inline tz editor for the Admin row
    row = page.locator("tr", has_text="Admin").first
    row.locator("label[for^=tzt-]").first.click()
    row.locator("select[name=timezone]").select_option(
        "Europe/Budapest")
    row.locator("button[type=submit]", has_text="Save").click()
    expect(row.locator("code")).to_have_text("Europe/Budapest")
    # restore UTC to keep the suite neutral
    row.locator("label[for^=tzt-]").first.click()
    row.locator("select[name=timezone]").select_option("UTC")
    row.locator("button[type=submit]", has_text="Save").click()
    expect(row.locator("code")).to_have_text("UTC")


def test_timezone_select_second_city(admin_page):
    """Second zone — Asia/Kolkata round-trips the same way."""
    page = admin_page
    page.goto("/system/users")
    row = page.locator("tr", has_text="Admin").first
    row.locator("label[for^=tzt-]").first.click()
    row.locator("select[name=timezone]").select_option("Asia/Kolkata")
    row.locator("button[type=submit]", has_text="Save").click()
    expect(row.locator("code")).to_have_text("Asia/Kolkata")
    row.locator("label[for^=tzt-]").first.click()
    row.locator("select[name=timezone]").select_option("UTC")
    row.locator("button[type=submit]", has_text="Save").click()


def test_licence_page_states(admin_page):
    page = admin_page
    page.goto("/system/licence")
    expect(page.locator("h1")).to_contain_text("Licence")
    # missing/invalid states render — the page must load cleanly
    expect(page.locator("body")).to_contain_text(
        re.compile(r"licen[cs]e", re.I))


def test_settings_hub_links(admin_page):
    page = admin_page
    page.goto("/system/settings")
    expect(page.locator("h1")).to_contain_text("Settings")
    for txt in ("security", "KRE", "Source", "Reports", "Users",
                "health"):
        expect(page.locator("body")).to_contain_text(
            re.compile(txt, re.I))


# BOUNDARY (recorded, not a failure): structured-logging settings
# (TO_LOGS_JSON_ENABLED et al.) are env-level ops settings in
# /etc/testorchestrator/web.env — there is deliberately no portal form
# for them (docs/external-logging.md). The logs pages themselves are
# covered by the export checks in test_06_execution.
