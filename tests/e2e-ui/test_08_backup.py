"""Flow 8 — backup/restore through the portal."""
import re
from playwright.sync_api import expect
from conftest import ADMIN_PW


def test_backup_page_renders(admin_page):
    page = admin_page
    page.goto("/system/backup")
    expect(page.locator("h1, h2").first).to_contain_text(
        re.compile(r"Backup", re.I))


def test_backup_create(admin_page):
    page = admin_page
    page.goto("/system/backup")
    page.locator("summary", has_text="Create backup").click()
    page.fill("input[name=passphrase]", "UiThrowaway-Backup-Pw99!")
    page.fill("input[name=confirm]", "UiThrowaway-Backup-Pw99!")
    page.fill("input[name=password]", ADMIN_PW)
    with page.expect_download() as dl:
        page.locator("button", has_text="Create & download").click()
    name = dl.value.suggested_filename
    assert name.endswith(".tobackup"), name


def test_restore_page_boundary(admin_page):
    """Restore staging page renders; the destructive apply step is a
    separate, deliberate operator action — boundary: staging UI only."""
    page = admin_page
    page.goto("/system/backup")
    expect(page.locator("body")).to_contain_text(
        re.compile(r"restore|Restore", re.I))
