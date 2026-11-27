"""Discovery adapter protocol (2.7.0).

Static inspection runs in-process and NEVER executes repository code
— bounded filesystem walks + parsers only. Native collection (running
the framework's own --collect/--list on a worker/SSH target) is a
separate, approval-gated stage defined per adapter.

Terminology:
- candidate   — an identity static inspection found but cannot prove
                is an exact executable selector
- validated   — the selector is exact for the adapter's runner argv

Bounds (all adapters):
- _MAX_FILE   per-file read cap
- _MAX_FILES  per-root traversal cap
- _MAX_ITEMS  total emitted items cap
- depth cap   directory recursion limit
Containment: every resolved path must stay inside the checkout —
symlink escapes are warnings, never reads.
"""
import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE = 512 * 1024
MAX_FILES = 5000
MAX_ITEMS = 10000
MAX_DEPTH = 32
ADAPTER_VERSION = "1"

# Directories never traversed during discovery.
SKIP_DIRS = {".git", ".cache", "Keywords", "Scripts", "Libs", "bin",
             "build", "Reports", "__pycache__", "node_modules",
             ".venv", "venv", "dist", ".idea", ".svn", "allure-results",
             "test-results", "cypress/screenshots", "cypress/videos"}


@dataclass
class Item:
    """One discovered unit. `kind` reuses the legacy vocabulary for
    dispatch compatibility: 'suite' = executable file-level unit,
    'test'/'scenario' = sub-file unit, 'case' = leaf definition,
    'profile' = config context."""
    kind: str               # suite|test|scenario|case|profile
    path: str               # repo-relative (posix)
    name: str = ""
    parent: str = ""
    node_id: str = ""       # executable selector (framework-specific)
    granularity: str = "file"   # file|test|scenario
    selectable: bool = True     # adapter can execute this reliably
    dynamic: bool = False
    warnings: str = ""
    members: list = field(default_factory=list)
    tags: str = ""              # csv of tags/markers for display


@dataclass
class Result:
    items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # "static" or "native" — how this inventory was produced.
    method: str = "static"
    # settings the adapter resolved, each {"value":…, "source":…}
    effective: dict = field(default_factory=dict)
    # True when native collection is REQUIRED to resolve test-level
    # identities the user asked for.
    needs_native: bool = False


def setting(value, source):
    return {"value": value, "source": source}


class ContainmentError(Exception):
    pass


def rel_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def safe_under(child: Path, base: Path) -> bool:
    try:
        child.resolve().is_relative_to(base.resolve())
        return True
    except Exception:
        return False


def iter_files(root: Path, base: Path, warnings: list,
               max_files: int = MAX_FILES, depth: int = MAX_DEPTH):
    """Bounded, contained, cycle-safe file walk under `root` (which
    must already be inside `base`). Yields files only."""
    if not root.is_dir():
        return
    seen = set()
    count = 0
    stack = [(root, 0)]
    base_r = base.resolve()
    while stack:
        d, lvl = stack.pop()
        if lvl > depth:
            warnings.append(f"{d}: depth limit {depth} exceeded")
            continue
        try:
            rd = d.resolve()
            if rd in seen:
                continue                    # symlink cycle
            seen.add(rd)
            if not rd.is_relative_to(base_r):
                warnings.append(f"{d}: symlink escape skipped")
                continue
        except OSError:
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if count >= max_files:
                warnings.append(
                    f"file cap {max_files} reached — inventory is partial")
                return
            try:
                if e.is_dir() and not e.is_symlink():
                    if e.name not in SKIP_DIRS:
                        stack.append((e, lvl + 1))
                elif e.is_file():
                    if not safe_under(e, base):
                        warnings.append(
                            f"{e}: symlink escape skipped")
                        continue
                    count += 1
                    yield e
            except OSError:
                continue


def read_text_bounded(path: Path, warnings: list, label: str = ""):
    """Return file text under _MAX_FILE, or None with a warning."""
    try:
        if path.stat().st_size > MAX_FILE:
            warnings.append(
                f"{label or path.name}: oversized (>{MAX_FILE//1024}KB) skipped")
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"{label or path.name}: unreadable ({exc})")
        return None


def fingerprint(fp) -> str:
    """Configuration fingerprint — invalidates discovery when any
    effective setting or the adapter version changes, not just the
    git SHA. Includes config-file CONTENT so edited configs restamp."""
    cfg = {
        "framework": fp.framework,
        "project_root": fp.project_root,
        "workdir": fp.workdir,
        "config_file": fp.config_file,
        "test_roots": fp.test_roots(),
        "include": fp.include(),
        "exclude": fp.exclude(),
        "feature_roots": fp.feature_roots(),
        "stepdef_roots": fp.stepdef_roots(),
        "support_roots": fp.support_roots(),
        "settings": fp.settings(),
        "adapter_version": fp.adapter_version or ADAPTER_VERSION,
    }
    return "v1:" + hashlib.sha256(
        json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def _expand_braces(pat: str) -> list:
    """`{a,b}` brace expansion → list of patterns (config globs use
    these e.g. `**/*.cy.{js,ts}`)."""
    import re
    m = re.search(r"\{([^{}]+)\}", pat)
    if not m:
        return [pat]
    out = []
    for alt in m.group(1).split(","):
        out += _expand_braces(pat[:m.start()] + alt +
                              pat[m.end():])
    return out


def _seg_re(seg: str) -> str:
    """One path segment → regex. Supports the minimatch extglobs
    config files actually carry (playwright/jest `testMatch` values
    use `@(a|b)`, `?(a|b)`, `+(a|b)`, `*(a|b)`, `!(a|b)`) on top of
    fnmatch's `*`, `?` and `[...]` classes."""
    import re
    out, i, n = [], 0, len(seg)
    depth = []  # stack of extglob opener offsets
    while i < n:
        c = seg[i]
        if c in "?*+@!" and i + 1 < n and seg[i + 1] == "(":
            depth.append(c)
            out.append("(?:" if c != "!" else "(?:(?!")
            i += 2
            continue
        if c == "(" and depth:
            out.append("(")
            i += 1
            continue
        if c == ")" and depth:
            op = depth.pop()
            if op == "?":
                out.append(")?")
            elif op == "+":
                out.append(")+")
            elif op == "*":
                out.append(")*")
            elif op == "@":
                out.append(")")
            else:  # "!": negate — match any segment not in the set
                out.append(")[^/]*)")
            i += 1
            continue
        if c == "|" and depth:
            out.append("|")
            i += 1
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = seg.find("]", i + 1)
            if j > i:
                out.append(seg[i:j + 1])
                i = j
            else:
                out.append(re.escape(c))
        else:
            out.append(re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


def _match_parts(rp: list, pp: list) -> bool:
    """Segment-wise match where `**` consumes zero or more path
    segments and `*` never crosses `/` (real glob semantics, unlike
    fnmatch-on-the-whole-string)."""
    import re
    if not pp:
        return not rp
    if pp[0] == "**":
        return _match_parts(rp, pp[1:]) or \
            (bool(rp) and _match_parts(rp[1:], pp))
    if not rp:
        return False
    try:
        return re.match(_seg_re(pp[0]), rp[0]) is not None and \
            _match_parts(rp[1:], pp[1:])
    except re.error:
        return False


def glob_match(rel: str, patterns) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    rp = rel.strip("/").split("/")
    for pat in patterns or []:
        for p in _expand_braces(str(pat)):
            if _match_parts(rp, p.strip("/").split("/")):
                return True
    return False


def nodeid_for(rel_path: str, parts: list) -> str:
    """Exact pytest nodeid — '::' join of file + scope names."""
    return "::".join([rel_path] + [p for p in parts if p])
