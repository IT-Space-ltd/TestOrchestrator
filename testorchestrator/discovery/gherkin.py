"""Bounded line-based Gherkin parser — shared by behave and
pytest-bdd adapters. Explicitly SUPPORTED syntax (English
keywords only): Feature:, Background:, Scenario[:], Scenario
Outline[/Template]:, Examples:, @tags (file + scenario level),
doc strings (\"\"\" and ```) skipped as multiline content.
Unsupported constructs (localized keywords, Rules, background
steps referencing) produce partial-discovery warnings, never
falsely validated selections.
"""
import re
from .base import MAX_FILE

KW = ("Feature:", "Background:", "Scenario Outline:",
      "Scenario Template:", "Scenario:", "Examples:", "Rule:")


def parse_feature(text, rel=""):
    """Return dict {title, tags, scenarios:[{name, line, kind,
    tags, outline, examples:int}], warnings:[]}."""
    out = {"title": "", "tags": [], "scenarios": [], "warnings": []}
    pending_tags, pending_step_tags = [], []
    cur = None
    seen_step = False
    in_doc = False
    localized = set()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1
        if in_doc:
            if line.startswith('"""') or line.startswith("```"):
                in_doc = False
            continue
        if line.startswith('"""') or line.startswith("```"):
            in_doc = True
            continue
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            toks = [t.lstrip("@") for t in line.split()
                    if t.startswith("@")]
            if cur is None and not out["scenarios"] and \
                    not out["title"]:
                pending_tags += toks
            else:
                pending_step_tags += toks
            continue
        if line.startswith("Feature:"):
            out["title"] = line.split(":", 1)[1].strip()
            out["tags"] += pending_tags
            pending_tags = []
            continue
        if line.startswith("Rule:"):
            out["warnings"].append(
                f"{rel}:{i}: Rule: not supported — scenarios "
                "still listed but rule grouping ignored")
            continue
        for kw in ("Scenario Outline:", "Scenario Template:",
                   "Scenario:", "Background:"):
            if line.startswith(kw):
                if kw == "Background:":
                    cur = None
                    pending_step_tags = []
                    continue
                cur = {
                    "name": line.split(":", 1)[1].strip(),
                    "line": i,
                    "kind": "scenario",
                    "outline": "Outline" in kw or "Template" in kw,
                    "tags": pending_tags + pending_step_tags,
                    "examples": 0,
                }
                pending_tags, pending_step_tags = [], []
                out["scenarios"].append(cur)
                break
        else:
            if line.startswith("Examples:"):
                if cur is not None and cur["outline"]:
                    cur["examples"] += 1
                else:
                    out["warnings"].append(
                        f"{rel}:{i}: Examples: outside a "
                        "scenario outline")
            elif re.match(r"^(Given|When|Then|And|But)\b", line):
                seen_step = True
            elif re.match(r"^[\|\-#\s\*]", line):
                pass            # example/data tables, comments
            elif line and not seen_step and out["title"] == "" and \
                    not any(line.startswith(k) for k in KW):
                # looks like non-English keywords or free text
                localized.add(line.split()[0] if line else "")
    if localized:
        out["warnings"].append(
            f"{rel}: unrecognised keywords {sorted(localized)[:4]} — "
            "localized Gherkin is not supported; inventory may be "
            "partial")
    return out
