#!/usr/bin/env python3
"""Screenshot capture pipeline for the manuals (owner requirement E).

Reproducible, scripted capture against an installed package. Every shot
records provenance: build head + package sha256 + page URL + viewport.
Synthetic data only — the capture data set uses fixed fake names
(see CAPTURE_IDENTITY below); nothing real may appear in a shot.

Prereqs (isolated venv, never the product runtime):
    python3.12 -m venv /tmp/pw-venv
    /tmp/pw-venv/bin/pip install playwright
    /tmp/pw-venv/bin/playwright install --with-deps chromium

Usage:
    TO_UI_BASE_URL=https://10.97.0.14:9443 \
    TO_UI_ADMIN_USER=Admin TO_UI_ADMIN_PW='Throwaway-Only-1!' \
    /tmp/pw-venv/bin/python scripts/capture_screenshots.py \
        --manifest docs/capture-manifest.json --shots Manuals-Doc/shots

The manifest records, per screenshot: file, head, sha256, url, viewport,
alt text target, capture time. The coverage gate reads it.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# Fixed synthetic identity — scan-forbidden strings must never include
# these; conversely nothing else may appear. Keep in sync with the
# exposure scan wordlist.
CAPTURE_IDENTITY = {
    "project": "Example Project",
    "user": "Example User",
    "binding_url": "https://git.example.invalid/team/tests.git",
    "host": "tests.example.invalid",
}

def git_head():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=Path(__file__).resolve().parent.parent).stdout.strip()
    except Exception:
        return ""

def release_sha(base_url):
    """The installed package's own build provenance — release.json via
    the status API if reachable, else empty (recorded as unknown)."""
    import urllib.request
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(
                base_url.rstrip("/") + "/api/v1/system/release",
                context=ctx, timeout=8) as r:
            doc = json.loads(r.read() or "{}")
            return doc.get("sha256", ""), doc.get("head", "")
    except Exception:
        return "", ""

# Capture plan: (file, path, viewport, wait_for, notes). Extended as
# chapters are written — one entry per referenced screenshot.
def plan(base):
    P = []
    def add(name, path, note="", vw=(1280, 900), wait="networkidle"):
        P.append({"file": f"shots/{name}", "path": path, "viewport": vw,
                  "wait": wait, "note": note})
    add("um-first-run-01.png", "/login", "browser chrome with address bar")
    add("um-first-run-02.png", "/login", "sign-in page, numbered callouts")
    add("um-first-run-03.png", "/login", "filled sign-in form")
    add("um-first-run-04.png", "/projects", "left menu Projects highlighted")
    add("um-first-run-05.png", "/projects", "empty project list state")
    add("um-first-run-06.png", "/projects/new", "new project form filled")
    add("um-first-run-07.png", "/", "binding form filled (navigate in-flow)")
    add("um-first-run-08.png", "/", "framework dropdown open with jest")
    add("um-first-run-09.png", "/admin/infrastructure", "runtime list ready-execution")
    add("um-first-run-10.png", "/", "run form one item ticked")
    add("um-first-run-11.png", "/", "execution PASSED")
    add("um-first-run-12.png", "/", "artifacts list")
    return P

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="docs/capture-manifest.json")
    ap.add_argument("--shots", default="Manuals-Doc/shots")
    ap.add_argument("--dry-run", action="store_true",
                    help="write the plan and provenance without capturing")
    args = ap.parse_args()
    import os
    base = os.environ.get("TO_UI_BASE_URL", "https://localhost:9443")
    sha, head_pkg = release_sha(base)
    entries = []
    plan_items = plan(base)
    shots_dir = Path(args.shots)
    if not args.dry_run:
        shots_dir.mkdir(parents=True, exist_ok=True)
    for it in plan_items:
        entries.append({
            "file": it["file"], "url": base.rstrip("/") + it["path"],
            "viewport": it["viewport"], "note": it["note"],
            "package_sha256": sha, "package_head": head_pkg,
            "repo_head_at_capture": git_head(),
            "captured_at": "", "status": "planned" if args.dry_run else "pending",
        })
    if args.dry_run:
        Path(args.manifest).write_text(json.dumps(
            {"base_url": base, "entries": entries}, indent=2))
        print(f"dry-run: {len(entries)} planned shots -> {args.manifest}")
        return 0
    # real capture
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed in this venv — see header", file=sys.stderr)
        return 2
    user = os.environ.get("TO_UI_ADMIN_USER", "Admin")
    pw = os.environ.get("TO_UI_ADMIN_PW", "")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=True,
                                  viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(base.rstrip("/") + "/login")
        try:
            page.fill('input[name="username"]', user)
            page.fill('input[name="password"]', pw)
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            print("login failed:", str(e)[:120], file=sys.stderr)
        for ent in entries:
            try:
                page.goto(ent["url"])
                page.wait_for_load_state("networkidle", timeout=10000)
                out = shots_dir / Path(ent["file"]).name
                page.screenshot(path=str(out))
                ent["status"] = "captured"
                ent["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                   time.gmtime())
                print("captured", ent["file"])
            except Exception as e:
                ent["status"] = f"error: {str(e)[:80]}"
                print("FAILED", ent["file"], str(e)[:80])
        browser.close()
    Path(args.manifest).write_text(json.dumps(
        {"base_url": base, "entries": entries}, indent=2))
    bad = [e for e in entries if e["status"] != "captured"]
    print(f"captured {len(entries) - len(bad)}/{len(entries)}; "
          f"manifest at {args.manifest}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
