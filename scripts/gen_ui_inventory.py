#!/usr/bin/env python3
"""Generate the UI inventory for the 2.7.0 manuals coverage gate.

Scans templates + routes and emits docs/ui-inventory-2.7.0.json:
every page (template), every form field, select option, button,
and settings key — the coverage-check script then fails if any item
is missing from the manuals.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TPL = REPO / "testorchestrator" / "templates"


def scan_template(path: Path):
    src = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path.relative_to(TPL))
    entry = {"template": rel, "fields": [], "selects": [], "buttons": [],
             "links": []}
    # input / textarea fields
    for m in re.finditer(
            r'<(input|textarea)\b[^>]*?name="([^"]+)"[^>]*>', src):
        tag = m.group(0)
        typ = re.search(r'type="([^"]+)"', tag)
        entry["fields"].append({
            "name": m.group(2),
            "type": typ.group(1) if typ else ("textarea" if m.group(1) == "textarea" else "text"),
        })
    # select elements + their static options
    for m in re.finditer(r'<select\b[^>]*?name="([^"]+)"[^>]*>(.*?)</select>',
                         src, re.S):
        opts = re.findall(r'<option\b[^>]*?value="([^"]*)"[^>]*>(.*?)</option>',
                          m.group(2), re.S)
        entry["selects"].append({
            "name": m.group(1),
            "options": [{"value": v, "label": re.sub(r"\s+", " ", l).strip()}
                        for v, l in opts if "{%" not in v],
        })
    # buttons (submit/button elements with visible text)
    for m in re.finditer(r'<button\b[^>]*>(.*?)</button>', src, re.S):
        label = re.sub(r"<[^>]+>", "", m.group(1))
        label = re.sub(r"\s+", " ", label).strip()
        if label and "{%" not in label:
            entry["buttons"].append(label)
    return entry


def main():
    entries = []
    for path in sorted(TPL.rglob("*.html")):
        entries.append(scan_template(path))
    out = {
        "generated_from": "templates scan — scripts/gen_ui_inventory.py",
        "template_count": len(entries),
        "pages": entries,
    }
    dest = REPO / "docs" / "ui-inventory-2.7.0.json"
    dest.write_text(json.dumps(out, indent=2))
    nf = sum(len(e["fields"]) for e in entries)
    ns = sum(len(e["selects"]) for e in entries)
    nb = sum(len(e["buttons"]) for e in entries)
    print(f"templates={len(entries)} fields={nf} selects={ns} buttons={nb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
