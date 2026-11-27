"""Framework discovery package (2.7.0) — the user's explicit
`framework` choice selects the adapter; auto-detection only
*suggests*. Static inspection runs in-process (bounded, no repo
code execution); native collection is a separate worker stage."""
from dataclasses import dataclass
from pathlib import Path

from . import (behave, bruno, cypress, gtest, jest, katalon,
               playwright, postman, pytestbdd, pytestdisc, robot)
from .base import (ADAPTER_VERSION, ContainmentError, Item, Result,
                   fingerprint, safe_under, setting)

FRAMEWORKS = {
    "katalon": katalon,
    "pytest": pytestdisc,
    "pytest-bdd": pytestbdd,
    "behave": behave,
    "robot": robot,
    "cypress": cypress,
    "playwright": playwright,
    "playwright-pytest": pytestdisc,   # same pytest discovery path
    "gtest": gtest,
    "jest": jest,
    "postman": postman,
    "bruno": bruno,
}
FRAMEWORK_CHOICES = [
    ("katalon", "Katalon Studio"),
    ("pytest", "pytest"),
    ("pytest-bdd", "pytest-bdd"),
    ("behave", "Behave"),
    ("robot", "Robot Framework"),
    ("cypress", "Cypress"),
    ("playwright", "Playwright Test (JS/TS)"),
    ("playwright-pytest", "Playwright via pytest"),
    ("gtest", "GoogleTest (C/C++)"),
    ("jest", "Jest (Node.js)"),
    ("postman", "Postman collections (Newman / Postman CLI)"),
    ("bruno", "Bruno collections (bru CLI)"),
]


@dataclass
class Ctx:
    """Discovery inputs: fp = FrameworkProject row, binding =
    GitBinding row, base = resolved scope root (worktree +
    subdirectory + project_root, containment-verified)."""
    fp: object
    binding: object
    base: Path


def resolve_base(binding, fp) -> Path:
    """worktree + subdirectory + project_root — containment-checked
    so a configured root cannot escape the checkout."""
    wt = Path(binding.worktree_path)
    base = wt / (binding.subdirectory or "")
    if fp.project_root:
        base = base / fp.project_root
    base = base.resolve()
    if not safe_under(base, wt):
        raise ContainmentError(
            f"project root {fp.project_root!r} escapes the checkout")
    return base


def discover(fp, binding) -> Result:
    mod = FRAMEWORKS.get(fp.framework)
    if mod is None:
        r = Result()
        r.warnings.append(f"unknown framework {fp.framework!r}")
        return r
    try:
        base = resolve_base(binding, fp)
    except ContainmentError as exc:
        r = Result()
        r.warnings.append(str(exc))
        return r
    res = mod.parse(Ctx(fp=fp, binding=binding, base=base))
    res.effective["framework"] = setting(fp.framework, "override")
    return res


def item_kind(r: Result):
    for it in r.items:
        yield it
