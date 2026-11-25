"""Target-side native collectors (2.7.0, M6).

Each framework ships a small script that runs INSIDE the isolated
staged checkout on the worker/SSH target and emits structured JSON
to Reports/collect.json — never parsed from human console output.
The JSON schema:

    {"framework": "...", "items": [
        {"kind": "suite|test|scenario", "path": "rel/path",
         "name": "...", "node_id": "EXACT SELECTOR",
         "granularity": "file|test|scenario",
         "parent": "...", "tags": ["m1"], "warnings": "..."}
    ], "warnings": [...]}

node_id is the EXACT executable selector: pytest ::nodeid incl.
generated param IDs, behave path:LINE, robot --test name, gtest
filter Suite.Test qualified by binary path, playwright
file::title-path, jest spec path.

These scripts run ONLY as part of the approved native-collection
dispatch — repository code may execute; that boundary is what the
approval gate and worker isolation exist for.
"""

PYTEST_COLLECT = r'''
"""pytest/pytest-bdd native collector — emits the collected item
list with EXACT node IDs (param IDs resolved by pytest itself)."""
import json, sys
from pathlib import Path

import pytest


class _Collect:
    def pytest_collection_finish(self, session):
        items = []
        for it in session.items:
            markers = sorted({m.name for m in it.iter_markers()})
            path = getattr(it, "path", None) or getattr(it, "fspath",
                                                       None)
            try:
                path = str(path.relative_to(
                    session.config.rootpath)) if path else ""
            except Exception:
                path = str(path or "")
            cls = ""
            if it.cls is not None:
                cls = it.cls.__name__
            items.append({
                "kind": "test",
                "path": path,
                "name": it.name,
                "node_id": it.nodeid,
                "granularity": "test",
                "parent": cls,
                "tags": markers,
                "lineno": getattr(it, "lineno", None) or 0,
                "warnings": ""})
        Path("Reports").mkdir(exist_ok=True)
        Path("Reports/collect.json").write_text(json.dumps({
            "framework": "pytest",
            "items": items,
            "warnings": [],
        }))


if __name__ == "__main__":
    roots = sys.argv[1:] or ["."]
    rc = pytest.main(
        ["--collect-only", "-q", "-p", "no:cacheprovider"] + roots,
        plugins=[_Collect()])
    sys.exit(0 if rc in (0, 5) else 1)   # 5 = no tests collected
'''

ROBOT_COLLECT = r'''
"""Robot native collector — uses the framework's own suite model
(TestSuite.from_file_system) so native GWT cases, templates, tags
and localization are parsed by Robot itself."""
import json, sys
from pathlib import Path


def _walk(suite, parent=""):
    for t in suite.tests:
        tags = sorted(str(t) for t in t.tags)
        warn = ""
        if getattr(t, "template", None):
            warn = ("templated — a [Template] case runs as ONE test "
                    "with the template keyword; data rows are not "
                    "separate executable tests")
        yield {
            "kind": "test", "path": str(t.source or ""),
            "name": t.name,
            "node_id": t.name,      # --test 'name' in this suite
            "granularity": "test", "parent": suite.name,
            "tags": tags, "warnings": warn}
    for sub in suite.suites:
        yield from _walk(sub, suite.name)


def main():
    from robot.api import TestSuite
    roots = sys.argv[1:] or ["."]
    items = []
    warnings = []
    for root in roots:
        try:
            suite = TestSuite.from_file_system(root)
            items += list(_walk(suite))
            items.append({
                "kind": "suite", "path": root,
                "name": suite.name, "node_id": root,
                "granularity": "file", "parent": parent if (parent := "")
                else "", "tags": [], "warnings": ""})
        except Exception as exc:
            warnings.append(f"{root}: {exc}")
    Path("Reports").mkdir(exist_ok=True)
    Path("Reports/collect.json").write_text(json.dumps(
        {"framework": "robot", "items": items,
         "warnings": warnings}))


if __name__ == "__main__":
    main()
'''

BEHAVE_COLLECT = r'''
"""Behave native collector — behave --dry-run -f json resolves
localized keywords, Rules, outlines and examples expansion with
the runner's own parser."""
import json, subprocess, sys
from pathlib import Path


def main():
    targets = sys.argv[1:] or ["features"]
    out = subprocess.run(
        [sys.executable, "-m", "behave", "--dry-run", "-f", "json",
         "--no-summary"] + targets,
        capture_output=True, text=True, timeout=600)
    items = []
    warnings = []
    try:
        doc = json.loads(out.stdout or "{}")
        for feat in doc.get("elements", []) or doc.get(
                "features", []) or []:
            loc = feat.get("location", "")
            fpath = loc.split(":")[0]
            items.append({
                "kind": "suite", "path": fpath,
                "name": feat.get("name", ""),
                "node_id": fpath, "granularity": "file",
                "parent": "", "tags": feat.get("tags", []),
                "warnings": ""})
            for el in feat.get("elements", []):
                if el.get("keyword", "") not in (
                        "Scenario", "Scenario Outline"):
                    continue
                line = (el.get("location") or "").split(":")
                nid = f"{line[0]}:{line[1]}" if len(line) > 1 \
                    else fpath
                items.append({
                    "kind": "scenario", "path": fpath,
                    "name": el.get("name", ""),
                    "node_id": nid, "granularity": "scenario",
                    "parent": feat.get("name", ""),
                    "tags": el.get("tags", []),
                    "warnings": ""})
    except Exception as exc:
        warnings.append(f"behave json parse: {exc}")
    if out.returncode not in (0, 1):
        warnings.append(f"behave rc={out.returncode}: "
                        f"{out.stderr[-300:]}")
    Path("Reports").mkdir(exist_ok=True)
    Path("Reports/collect.json").write_text(json.dumps(
        {"framework": "behave", "items": items,
         "warnings": warnings}))


if __name__ == "__main__":
    main()
'''

GTEST_COLLECT = r'''
"""gTest native collector — runs each binary --gtest_list_tests and
emits exe-qualified exact selectors: node_id = '<exe>||Suite.Test'.
Disabled and parametrized instances are surfaced verbatim."""
import json, subprocess, sys
from pathlib import Path


def main():
    exes = sys.argv[1:]
    items, warnings = [], []
    for exe in exes:
        try:
            out = subprocess.run([exe, "--gtest_list_tests"],
                                 capture_output=True, text=True,
                                 timeout=120)
        except OSError as exc:
            warnings.append(f"{exe}: {exc}")
            continue
        if out.returncode != 0:
            warnings.append(f"{exe}: list_tests rc={out.returncode}")
            continue
        items.append({"kind": "suite", "path": exe, "name": exe,
                      "node_id": exe + "||", "granularity": "file",
                      "parent": "", "tags": ["executable"],
                      "warnings": ""})
        suite = ""
        for line in out.stdout.splitlines():
            if line and not line.startswith(" ") and \
                    line.rstrip().endswith("."):
                suite = line.strip()
            elif suite and line.strip():
                name = line.strip()
                disabled = name.startswith("DISABLED_")
                items.append({
                    "kind": "test", "path": exe,
                    "name": f"{suite}{name}",
                    "node_id": f"{exe}||{suite}{name}",
                    "granularity": "test", "parent": suite,
                    "tags": ["disabled"] if disabled else [],
                    "warnings": ""})
    Path("Reports").mkdir(exist_ok=True)
    Path("Reports/collect.json").write_text(json.dumps(
        {"framework": "gtest", "items": items,
         "warnings": warnings}))


if __name__ == "__main__":
    main()
'''

PLAYWRIGHT_COLLECT = r'''// Playwright native collector (node) — `playwright test --list
// --reporter=json` resolves project variants, title hierarchy and
// parameterized instances with the framework's own collector.
const { execFileSync } = require("child_process");
const fs = require("fs");
// win32: npx resolves to npx.cmd, and Node >=20.12 refuses to exec
// batch files directly (EINVAL without shell:true). Collect skips the
// deps step by design, so resolve the staged node_modules CLI
// deterministically — POSIX-installed .bin shims are useless on
// Windows, and PATH may hold an unrelated 'playwright' (e.g. the
// Python playwright.exe has no 'test' command).
const NPX = process.platform === "win32" ? "npx.cmd" : "npx";
const SHELL = process.platform === "win32";
let cli = null;
for (const p of ["node_modules/@playwright/test/cli.js",
                 "node_modules/playwright/cli.js"])
  if (fs.existsSync(p)) { cli = p; break; }
try {
  const out = cli
    ? execFileSync(process.execPath,
        [cli, "test", "--list", "--reporter=json"],
        { encoding: "utf-8", timeout: 600000 })
    : execFileSync(
        NPX, ["--no-install", "playwright", "test", "--list",
              "--reporter=json"],
        { encoding: "utf-8", timeout: 600000, shell: SHELL });
  const doc = JSON.parse(out || "{}");
  const items = [];
  const seen = {};
  // duplicates: (file, project, full title) — --grep is a regex over
  // the title path, so an identical title in the same file+project
  // cannot be selected uniquely; those stay candidates.
  const walk = (suite, parent) => {
    // --list schema moved file from suite.location.file (older) to
    // suite.file / spec.file (1.4x+). Accept all three.
    const loc = (suite.location || {}).file || suite.file || "";
    for (const spec of suite.specs || []) {
      const specloc = loc || spec.file || "";
      for (const t of spec.tests || []) {
        const proj = t.projectName || "";
        const title = [parent, suite.title || "",
                       spec.title || ""].filter(Boolean).join(" > ");
        const key = `${specloc}::${proj}::${title}`;
        const dup = seen[key]; seen[key] = true;
        items.push({
          kind: "test", path: specloc, name: spec.title || "",
          node_id: dup ? "" : ("t:" + title + ";;" + proj),
          granularity: "test", parent: suite.title || "",
          tags: proj ? [proj] : [],
          warnings: dup ? "duplicate title in file+project — "
            + "select the file instead" : ""});
      }
    }
    for (const sub of suite.suites || [])
      walk(sub, [parent, suite.title || ""]
           .filter(Boolean).join(" > "));
  };
  for (const s of doc.suites || []) walk(s, "");
  fs.mkdirSync("Reports", { recursive: true });
  fs.writeFileSync("Reports/collect.json", JSON.stringify(
    { framework: "playwright", items, warnings: [] }));
} catch (e) {
  fs.mkdirSync("Reports", { recursive: true });
  fs.writeFileSync("Reports/collect.json", JSON.stringify({
    framework: "playwright", items: [],
    warnings: [`playwright --list failed: ${e.message}`] }));
}
'''

JEST_COLLECT = r'''// Jest native collector (node).
// Current-jest `--collectTests --json` emits per-test structured
// results WITHOUT running test bodies — nested describe names,
// expanded test.each/describe.each cases, skipped/todo markers.
// It still evaluates each file's top-level code → isolated target
// only. Older jest lacks --collectTests → fallback --listTests
// gives file-level identity; a warning marks tests as unresolved
// candidates (never fake selectors). Collection output is
// discovery metadata — `wouldRun` rows are NOT passing results;
// execution ingestion is a separate path.
const { execFileSync } = require("child_process");
const fs = require("fs");
// win32: npx resolves to npx.cmd, and Node >=20.12 refuses to exec
// batch files directly (EINVAL without shell:true). Prefer the staged
// node_modules jest CLI over npx resolution (same rationale as the
// playwright collector — POSIX .bin shims don't run on Windows and
// PATH may resolve an unrelated binary).
const NPX = process.platform === "win32" ? "npx.cmd" : "npx";
const SHELL = process.platform === "win32";
let jestCli = null;
for (const p of ["node_modules/jest-cli/bin/jest.js",
                 "node_modules/jest/bin/jest.js"])
  if (fs.existsSync(p)) { jestCli = p; break; }
const jestArgv = (jestCli
  ? [process.execPath, jestCli]
  : [NPX, "--no-install", "jest"]);
const warnings = [];
let items = [];
function emit() {
  fs.mkdirSync("Reports", { recursive: true });
  fs.writeFileSync("Reports/collect.json",
    JSON.stringify({ framework: "jest", items, warnings }));
}
let out = "";
try {
  out = execFileSync(
    jestArgv[0],
    jestArgv.slice(1).concat(["--collectTests", "--json"]),
    { encoding: "utf-8", timeout: 600000, shell: SHELL });
} catch (e) {
  // --collectTests unsupported/failed → file-level fallback
  try {
    const lout = execFileSync(
      jestArgv[0],
      jestArgv.slice(1).concat(["--listTests", "--json"]),
      { encoding: "utf-8", timeout: 600000, shell: SHELL });
    items = (JSON.parse(lout || "[]")).map(rel => ({
      kind: "suite", path: rel, name: rel.split("/").pop(),
      node_id: rel, granularity: "file", parent: "",
      tags: [], warnings: "" }));
    warnings.push("--collectTests unavailable (" + e.message +
      ") — file-level inventory only; per-test selection " +
      "requires a jest version that supports --collectTests");
  } catch (e2) {
    warnings.push(`jest collection failed: ${e2.message}`);
  }
  emit(); process.exit(0);
}
const doc = JSON.parse(out || "{}");
const seen = {};                       // duplicate fullName index
for (const tr of (doc.testResults || [])) {
  const rel = tr.name || tr.testFilePath || "";
  items.push({ kind: "suite", path: rel,
    name: rel.split("/").pop(), node_id: rel,
    granularity: "file", parent: "", tags: [], warnings: "" });
  for (const a of (tr.assertionResults || [])) {
    const full = a.fullName || a.title || "";
    const status = a.status || "";
    const dup = seen[rel + "::" + full];
    seen[rel + "::" + full] = true;
    // selectable only when the full name is unique in its file —
    // -t matches the complete name path, so identical names in the
    // same file are NOT disambiguable by pattern.
    items.push({
      kind: "test", path: rel, name: full,
      parent: (a.ancestorTitles || []).join(" "),
      node_id: dup ? "" : ("t:" + full),
      granularity: "test", parent2: rel,
      selectable: !dup && status !== "skipped" &&
                  status !== "todo" && status !== "pending",
      tags: status !== "passed" ? status : "",
      warnings: dup ? "duplicate full name in file — select the "
        + "file instead (testNamePattern cannot disambiguate)"
        : "" });
  }
}
emit();
'''

CYPRESS_COLLECT = r'''// Cypress collector (node) — no native list command exists;
// file-level inventory comes from static specPattern resolution.
const fs = require("fs");
fs.mkdirSync("Reports", { recursive: true });
fs.writeFileSync("Reports/collect.json", JSON.stringify({
  framework: "cypress", items: [], noop: true,
  warnings: ["cypress has no native list command — file-level " +
             "inventory comes from static specPattern resolution " +
             "(literal config)"] }));
'''

NODE_SCRIPTS = {"playwright", "jest", "cypress"}

# framework → (script content, interpreter argv builder)
COLLECT_SCRIPTS = {
    "pytest": PYTEST_COLLECT, "pytest-bdd": PYTEST_COLLECT,
    "playwright-pytest": PYTEST_COLLECT,
    "robot": ROBOT_COLLECT, "behave": BEHAVE_COLLECT,
    "gtest": GTEST_COLLECT, "jest": JEST_COLLECT,
    "playwright": PLAYWRIGHT_COLLECT,
    "cypress": CYPRESS_COLLECT,
}
