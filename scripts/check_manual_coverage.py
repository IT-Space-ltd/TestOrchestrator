#!/usr/bin/env python3
"""Coverage gate: every UI inventory item must appear in the manuals.

Fails (exit 1) if any page, field, select option or button from
docs/ui-inventory-2.7.0.json is not mentioned in the manuals.
Match rule: the literal name/value/label string must appear in
User-Manual.md or Admin-Manual.md. Templates under admin/system
blueprints count against the Admin Manual; portal/auth/main count
against the User Manual — but a hit in either manual satisfies.
"""
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
corpus_l = corpus.lower()

missing = []
present = 0
total = 0

def check(kind, label, where):
    global present, total
    if not label or len(label.strip()) < 2:
        return
    total += 1
    if label.strip().lower() in corpus_l:
        present += 1
    else:
        missing.append(f"{kind}: {label} ({where})")

for page in INV["pages"]:
    tpl = page["template"]
    base = tpl.rsplit("/", 1)[-1].replace(".html", "").replace("_", " ")
    check("page", base, tpl)
    for f in page["fields"]:
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
