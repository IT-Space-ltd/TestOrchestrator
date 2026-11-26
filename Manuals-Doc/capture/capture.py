#!/usr/bin/env python3
"""Reproducible screenshot capture for the 2.7.0 manuals.

Runs against the installed final build on the guest (or any seeded
instance). Synthetic data only. Records head + sha256 of the build
the frames came from into the Screenshot Index.

Usage:
  python3 capture.py --base http://127.0.0.1:PORT --out ../Screenshot-Doc \
      --user Admin --password 'Review-Preview-#2026!'

Frames are numbered in capture order; callouts are added in the
manuals' prose. Window: 1440x900, default theme. Alt text lives in
the Screenshot Index next to each frame's provenance.
"""
import argparse
import json
import sys
import time

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--user", default="Admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--provenance", default="",
                    help="head sha + package sha256 recorded in the index")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright required: pip install playwright && playwright install chromium")

    import os
    os.makedirs(os.path.join(args.out, "user"), exist_ok=True)
    os.makedirs(os.path.join(args.out, "admin"), exist_ok=True)

    frames = []
    def shot(page, name, audience, caption, wait=400):
        page.wait_for_timeout(wait)
        path = os.path.join(args.out, audience, f"{name}.png")
        page.screenshot(path=path)
        frames.append({"file": f"{audience}/{name}.png", "caption": caption})
        print(" captured", name)

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # login — error state first, then success
        page.goto(f"{args.base}/login")
        page.fill("input[name=username]", args.user)
        page.fill("input[name=password]", "wrong-password-synthetic")
        page.click("button[type=submit],input[type=submit]")
        shot(page, "01-login-error", "user",
             "Sign-in with an incorrect password — the error state.")
        page.fill("input[name=username]", args.user)
        page.fill("input[name=password]", args.password)
        page.click("button[type=submit],input[type=submit]")
        page.wait_for_timeout(600)
        shot(page, "02-after-login", "user",
             "The navigation and dashboard after signing in.")

        # key pages — best-effort, missing pages are skipped with a note
        for url, name, aud, cap in [
            ("/projects", "03-projects-list", "user", "The projects list."),
            ("/system/infrastructure", "20-infrastructure", "admin", "Admin — infrastructure overview with runtimes and readiness."),
            ("/system/integrations", "21-integrations", "admin", "Admin — CI integration tokens with expiry states."),
        ]:
            try:
                r = page.goto(f"{args.base}{url}")
                if r and r.status == 200:
                    shot(page, name, aud, cap, wait=600)
            except Exception as exc:
                print(" skipped", url, exc)

        b.close()

    idx = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base": args.base,
        "provenance": args.provenance,
        "window": "1440x900",
        "frames": frames,
    }
    with open(os.path.join(args.out, "capture-manifest.json"), "w") as fh:
        json.dump(idx, fh, indent=1)
    print(f"done — {len(frames)} frames")

if __name__ == "__main__":
    main()
