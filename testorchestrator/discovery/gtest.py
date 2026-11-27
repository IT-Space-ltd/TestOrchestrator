"""GoogleTest adapter — static source inspection produces
CANDIDATES only: `TEST()`/`TEST_F()`/`TEST_P()`/
`INSTANTIATE_TEST_SUITE_P` names are parseable, but the
authoritative executable identity requires running the compiled
binary's `--gtest_list_tests` — that happens ONLY in the isolated
worker/SSH native-collection stage (never in this process).
Executable identity is preserved alongside suite/test identity;
duplicate test names across binaries are disambiguated by the
executable path component.

Settings keys (fp.settings_json): build_dir, executables[]
(patterns), prepare_cmd, configure_cmd, build_cmd, gtest_args[],
timeout_s — executed worker-side, never during static preview.
"""
import re
from .base import (Item, Result, glob_match, iter_files,
                   read_text_bounded, rel_posix, setting)

KIND = "gtest"
_TEST_RE = re.compile(
    r"^\s*TEST(?:_F|_P)?\s*\(\s*([A-Za-z_][\w]*)\s*,\s*"
    r"([A-Za-z_][\w]*)\s*\)", re.M)
_INST_RE = re.compile(
    r"^\s*INSTANTIATE_TEST_SUITE_P\s*\(\s*([A-Za-z_][\w]*)", re.M)
_SRC_EXT = (".cc", ".cpp", ".cxx", ".c++")


def parse(ctx) -> Result:
    res = Result(method="static")
    base = ctx.base
    st = ctx.fp.settings()
    roots = ctx.fp.test_roots() or ["test", "tests"]
    src = ("override" if ctx.fp.test_roots() else "default")
    res.effective["test_roots"] = setting(roots, src)
    exc = ctx.fp.exclude()
    res.effective["exclude"] = setting(
        exc, "override" if exc else "default")
    build_dir = st.get("build_dir") or ""
    exe_pats = st.get("executables") or []
    res.effective["build_dir"] = setting(
        build_dir, "override" if build_dir else "default")
    res.effective["executables"] = setting(
        exe_pats, "override" if exe_pats else "default")
    for k in ("prepare_cmd", "configure_cmd", "build_cmd"):
        v = st.get(k) or ""
        res.effective[k] = setting(
            v or "—", "override" if v else "default")

    # 1. Executable candidates present in the checkout (prebuilt
    #    workflow) — they become file-level selectable items.
    found_exe = False
    if build_dir and (base / build_dir).is_dir():
        for p in iter_files(base / build_dir, base, res.warnings):
            if not p.is_file():
                continue
            rel = rel_posix(p, base)
            if exe_pats and not glob_match(rel, exe_pats):
                continue
            import os
            if not os.access(p, os.X_OK):
                continue
            found_exe = True
            res.items.append(Item(
                kind="suite", path=rel, name=p.name,
                parent=build_dir, node_id=rel,
                granularity="file", selectable=True,
                tags="executable"))
    if build_dir and not found_exe:
        res.warnings.append(
            f"no executables matching {exe_pats or '*'} found under "
            f"{build_dir!r} — binary discovery requires native "
            "collection after a worker-side build")
        res.needs_native = True

    # 2. TEST() names in sources — candidates (the real selector is
    #    exe + --gtest_filter which needs the built binary).
    for root in roots:
        rd = base / root
        if not rd.is_dir():
            if not build_dir:
                res.warnings.append(f"test root {root!r} not found")
            continue
        for p in iter_files(rd, base, res.warnings):
            if p.suffix not in _SRC_EXT:
                continue
            rel = rel_posix(p, base)
            if exc and glob_match(rel, exc):
                continue
            text = read_text_bounded(p, res.warnings, rel)
            if text is None:
                continue
            tests = list(_TEST_RE.finditer(text))
            insts = _INST_RE.findall(text)
            if not tests:
                continue
            res.items.append(Item(
                kind="suite", path=rel, name=p.stem,
                parent=str(p.parent.relative_to(base)),
                node_id=rel, granularity="file",
                selectable=bool(exe_pats) and found_exe,
                warnings="" if found_exe else
                "source-level unit — select via its executable",
                tags=f"{len(tests)} TESTs"))
            for m in tests:
                suite, name = m.group(1), m.group(2)
                is_typed = "_P(" in m.group(0)
                res.items.append(Item(
                    kind="test", path=rel, name=f"{suite}.{name}",
                    parent=p.stem,
                    node_id=f"{suite}.{name}",
                    granularity="test", selectable=False,
                    tags="disabled" if name.startswith("DISABLED_")
                    else ("typed/param" if is_typed else ""),
                    warnings=("typed/parametrized — native "
                              "--gtest_list_tests resolves the "
                              "instantiated identity"
                              if is_typed else
                              "candidate — executable identity "
                              "needs native listing")))
            for inst in insts:
                res.needs_native = True
                res.items.append(Item(
                    kind="test", path=rel, name=f"{inst}/*",
                    parent=p.stem, node_id="",
                    granularity="test", selectable=False,
                    tags="instantiation",
                    warnings="INSTANTIATE_TEST_SUITE_P — "
                             "instantiations resolve via native "
                             "listing"))
            res.needs_native = True
    if not res.items:
        res.warnings.append(
            "no test sources or executables discovered")
    return res
