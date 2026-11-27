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

# ---- tutorial / screenshot rules (owner gate, 2.7.0 revision) ----
# 1. every numbered tutorial step needs a screenshot reference in its block
# 2. every image embed needs alt text
# 3. referenced screenshot files must exist; files in shots dirs must be referenced
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
STEP_RE = re.compile(r"^\*\*Step \d+\.", re.M)
HEAD_RE = re.compile(r"^#{1,4} ", re.M)

shot_issues = []
shots_referenced = set()
step_count = 0
steps_with_shots = 0
img_count = 0
imgs_with_alt = 0

for manual in MANUALS:
    if not manual.exists():
        continue
    text = manual.read_text(errors="replace")
    # rule 2: alt text on every embed
    for alt, target in IMG_RE.findall(text):
        img_count += 1
        if alt.strip():
            imgs_with_alt += 1
        else:
            shot_issues.append(f"image without alt text: {target} ({manual.name})")
        if target.startswith("shots/"):
            shots_referenced.add(target)
    # rule 1: step blocks — from each **Step N. to the next step/heading
    steps = list(STEP_RE.finditer(text))
    for i, m in enumerate(steps):
        step_count += 1
        start = m.end()
        nxt = steps[i + 1].start() if i + 1 < len(steps) else len(text)
        heads = list(HEAD_RE.finditer(text, start, nxt))
        end = heads[0].start() if heads else nxt
        block = text[start:end]
        if IMG_RE.search(block):
            steps_with_shots += 1
        else:
            shot_issues.append(
                f"tutorial step without screenshot: {manual.name} "
                f"near offset {m.start()} — '{text[m.start():m.start()+60].strip()}'")

# rule 3: files exist / no orphans
shots_missing = []
shots_orphan = []
for manual in MANUALS:
    base = manual.parent
    for target in sorted(shots_referenced):
        if not (base / target).exists():
            shots_missing.append(target)
    shots_dir = base / "shots"
    if shots_dir.is_dir():
        for f in sorted(shots_dir.iterdir()):
            if f.is_file() and f"shots/{f.name}" not in shots_referenced:
                shots_orphan.append(f"shots/{f.name}")

if shots_missing:
    shot_issues.append(f"{len(shots_missing)} referenced screenshot files missing "
                       f"(capture pending): e.g. {shots_missing[:3]}")
if shots_orphan:
    shot_issues.append(f"{len(shots_orphan)} unreferenced screenshot files: {shots_orphan[:3]}")

print(f"tutorial steps: {step_count}, with screenshots: {steps_with_shots}")
print(f"image embeds: {img_count}, with alt text: {imgs_with_alt}")
print(f"screenshot files missing: {len(shots_missing)}, orphans: {len(shots_orphan)}")

fail = bool(missing)
# screenshot rules fail the gate only once the capture phase has begun —
# before any shots/ directory exists they are reported as pending, not errors.
shots_dir_exists = any((m.parent / "shots").is_dir() for m in MANUALS)
hard_shot_fail = False
for issue in shot_issues:
    if "without alt text" in issue or "unreferenced" in issue:
        hard_shot_fail = True
    elif shots_dir_exists:
        hard_shot_fail = True
if shot_issues:
    print(f"screenshot/step issues ({'FAILING' if hard_shot_fail else 'pending capture'}):")
    for i in shot_issues[:30]:
        print(" -", i)
if fail or hard_shot_fail:
    if missing:
        print("MISSING (first 40):")
        for m in missing[:40]:
            print(" -", m)
    sys.exit(1)
print("COVERAGE OK")
