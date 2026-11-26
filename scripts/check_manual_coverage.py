#!/usr/bin/env python3
"""Coverage gate: every UI inventory item must appear in the manuals.

Fails (exit 1) if any page, field, select option or button from
docs/ui-inventory-2.7.0.json is not mentioned in the manuals.
Match rule: the literal name/value/label string must appear in
User-Manual.md or Admin-Manual.md. Templates under admin/system
blueprints count against the Admin Manual; portal/auth/main count
against the User Manual — but a hit in either manual satisfies.
"""
import html
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INV = json.loads((REPO / "docs" / "ui-inventory-2.7.0.json").read_text())
MANUALS = [
    (REPO / "Manuals-Doc" / "User-Manual.md"),
    (REPO / "Manuals-Doc" / "Admin-Manual.md"),
]
corpus = "\n".join(p.read_text(errors="replace") for p in MANUALS if p.exists())
import re as _re
corpus_l = _re.sub(r"\s+", " ", html.unescape(corpus).lower())

# template filename → user-facing page name used in the manuals
PAGE_ALIASES = {
    "discovered detail": "discovered-item",
    "fp collect": "collect page",
    "import new": "import",
    "project dashboard": "project",
    "release sync": "release",
    "suite edit": "suite",
    "suite matrix": "matrix",
    "backup report": "backup",
    "backup restore": "restore",
    "log export": "log export",
    "operational logs": "operational logs",
    "runtime wizard": "runtime wizard",
    "setup step": "setup",
}

missing = []
present = 0
total = 0

NOISE = _re.compile(r"\{\{|\{%")

def check(kind, label, where):
    global present, total
    if not label or len(label.strip()) < 2:
        return
    if NOISE.search(label):
        return
    total += 1
    if _re.sub(r"\s+", " ", html.unescape(label).strip().lower()) in corpus_l:
        present += 1
    else:
        missing.append(f"{kind}: {label} ({where})")

for page in INV["pages"]:
    tpl = page["template"]
    base = tpl.rsplit("/", 1)[-1].replace(".html", "").replace("_", " ")
    if not (tpl.startswith("_") or "/_" in tpl):
        check("page", PAGE_ALIASES.get(base, base), tpl)
    for f in page["fields"]:
        if f["name"] == "csrf_token":
            continue
        check("field", f["name"], tpl)
    for s in page["selects"]:
        check("select", s["name"], tpl)
        for o in s["options"]:
            if o["value"]:
                check("option", o["label"] or o["value"], f"{tpl}:{s['name']}")
    for b in page["buttons"]:
        check("button", b, tpl)

print(f"inventory items checked: {total}, present: {present}, missing: {len(missing)}")
if missing:
    print("MISSING (first 40):")
    for m in missing[:40]:
        print(" -", m)
    sys.exit(1)
print("COVERAGE OK")
