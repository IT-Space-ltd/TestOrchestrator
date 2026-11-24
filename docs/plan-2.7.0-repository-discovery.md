# 2.7.0 Plan — framework-aware repository onboarding & discovery

Status: **proposal — no implementation started**. Baseline
`main@3855e29d` (post-merge head containing all accepted 2.6.0 work;
identical content to released tag `2.6.0` plus the merge commit).
Branch `feature/2.7.0-repository-discovery` created from it.

## 1. Branch / PR inventory and closure record

Recorded 2026-11-24 after the 2.6.0 release:

| Ref | Head | Status | Unique work | Action taken |
|---|---|---|---|---|
| PR #4 `feature/2.6.0-node-runners` | `864373ec` | merged into `main` via `3855e29d` | none | closed (merged) + branch deleted local+remote |
| `feature/cheroot-frontend` | `6cc040d5` | merged | none | deleted local+remote |
| `release/2.5.1-backports` | `6ebf3b26` | merged | none | deleted local+remote |
| `spike/cheroot-frontend` | `42a4287c` | **5 unmerged commits** | spike experiments + docs; already productized as the shipped Cheroot frontend | deleted local+remote |
| PRs #1–#3 | — | merged (historical) | none | already closed |

All 7 stale `/tmp` git worktrees pruned; `/tmp` seed/evidence dirs
removed. The 2.6.0 handover (`docs/acceptance-2.6.0.md`), release
tag `2.6.0`, GitHub release assets, and `dist/release/2.6.0/` are
preserved untouched.

**Approved baseline**: `main@3855e29d`.

## 2. Current capability audit (2.6.0, file:line)

### What exists
- `GitBinding` (`execution.py:33-69`): `url`, `ref`,
  `subdirectory`, `prj_path`, `credential_ref` (SecretRef name only),
  `worktree_path`, `discovered_sha`, `discovery_status/error`.
  **No framework field** — model is Katalon-assumed.
- Katalon discovery (`gitsync.py:377-508`): static, safe — rglob +
  `ElementTree` only, never executes repo code; `.prj` root
  detection; `.tc` cases, `.ts` suites/collections (root-tag
  driven), `.glbl` profiles; containment via
  `resolve().is_relative_to()`; atomic per-SHA replace with
  stale-set retention on failure.
- `DiscoveredItem` (`execution.py:734-760`): kinds
  `case|suite|collection|profile`, repo-relative `path`,
  `members_json` (Katalon-shaped).
- Runtime kinds `kre|playwright|cypress|robot|pytest`
  (`system/routes.py:1870`); execution adapters `adapters/{kre,
  nodefw,pytestfw,robotfw}.py` — all argv-builders with JUnit into
  `Reports/`; probe-gated optional deps (`opt_pabot`, `opt_xdist`).
- Run-form filter knobs already exist: `robot_test|robot_include|
  robot_exclude`, `pytest_keyword`(-k), `pytest_markers`(-m)
  (`run_discovered` `portal/routes.py:1028-1073`).
- One piece of non-Katalon discovery exists:
  `discover_cypress_specs` (`dispatch.py:408-505`) honors
  `cypress.config.*` `specPattern` — but only inside the partition
  flow; it does not populate `DiscoveredItem`.

### What does NOT exist (the gap map)
1. No `framework`/`repo_type` on `GitBinding`; sync hard-fails
   without a `.prj` (`gitsync.py:401-403`).
2. `prj_path` is a dead field — stored, never read
   (`gitsync.py:396` ignores it).
3. No discovery for pytest/pytest-bdd/Behave/Robot/Cypress/
   Playwright; no auto-detection hints
   (`pytest.ini`/`pyproject.toml`, `*.robot`, `*.feature`,
   `cypress.config.*`, `playwright.config.*`).
4. `DiscoveredItem` has no `framework`, no `node_id`/selector, no
   per-test granularity; dispatch gate is
   `kind in ("suite","collection")` (`portal/routes.py:1031`,
   `api/routes.py:225`, `dispatch.py:1237`).
5. `pytestfw.build_args(node_ids=)` exists but is **unwired** — no
   run_config key or UI feeds it (`pytestfw.py:27,50-51`;
   `dispatch.py:1858-1862`).
6. No `behave`/`pytest-bdd` runtime kind; no `.feature` handling
   anywhere.
7. No discovery preview endpoint — discovery only runs inside
   worker-side sync and overwrites inventory.
8. No scheduled resync; only manual Sync / create / publish hooks.
9. `Execution.framework` is stamped `"katalon"` for all live runs
   (only the result importer sets it correctly —
   `execution.py:504`, `importer.py:184`).
10. Operational gaps to fold in: `cli` git backend ignores the
    `auth` param (`git_backend.py:69-86,153-159`); dulwich calls
    have no network timeout; `binding.last_error` can capture a
    userinfo-bearing URL (`gitsync.py:104`) — the form does not
    forbid credentials in the URL.

## 3. Design

### 3.1 Model: `FrameworkProject` (new table)

One `GitBinding` → N `FrameworkProject` rows — monorepos get one
project per framework area; overlapping roots allowed deliberately.

```
framework_projects
  id, binding_id FK, project_id FK, name
  framework            katalon|pytest|pytest-bdd|behave|robot|
                       cypress|playwright|playwright-pytest
  project_root         repo-relative (replaces prj_path usage)
  workdir              default = project_root
  config_file          repo-relative, framework-appropriate
                       (pytest.ini/pyproject.toml/behave.ini/
                        cypress.config.* / playwright.config.* / .prj)
  test_roots_json      [repo-relative dirs] — one or more
  include_json         glob list   (framework-defaulted)
  exclude_json         glob list
  feature_roots_json   BDD only — may differ from step defs
  stepdef_roots_json   behave/pytest-bdd/robot-BDD
  support_roots_json   fixtures/resources/support — non-test files
  settings_json        per-framework extra (Playwright project names,
                       Robot variable files, pytest addopts override…)
  adapter_version, discovered_sha, discovery_status/error
```

`DiscoveredItem` gains: `framework_project_id` (FK),
`framework` (str), `node_id` (framework selector — pytest
`::nodeid`, Robot `--test` name, spec path), `granularity`
(`file|test|scenario|case`), `selectable` (bool — only what the
adapter can execute reliably).

`GitBinding` unchanged except `prj_path` repurposed: migration maps
`subdirectory`+`prj_path` into an implicit `katalon`
`FrameworkProject` per existing binding (preserves behavior; old
column kept for read-compat one release, then dropped).

`Execution.framework` stamping fixed: stamped from the dispatching
runtime/framework-project, not default `"katalon"`.

### 3.2 Discovery pipeline — explicit separation

| Stage | Where | Executes repo code? |
|---|---|---|
| 1. Framework selection + config | portal form | no |
| 2. Static inspection | flask worker (in-process) | **no** — AST/glob/parse only |
| 3. Native collection | Buildbot worker / SSH target | **yes** — opt-in, approved |
| 4. Test selection | portal UI | no |
| 5. Execution | worker/SSH | yes (the run itself) |
| 6. Result ingestion | worker + portal | no |

**Static discovery** (new package `testorchestrator/discovery/`):

- `base.py` — `DiscoveryAdapter` protocol:
  `detect(ctx) -> float` (suggestion score, never decisive),
  `parse(ctx) -> DiscoveryResult` (items + warnings),
  `collect(ctx) -> DiscoveryResult` (native, worker-side).
- `katalon.py` — wraps existing `gitsync.discover_project`
  unchanged (parity guaranteed by keeping the same tests green).
- `pytest.py` — AST parse of `test_roots` for `test_*.py`/`*_test.py`
  honoring configured `python_files`/`python_classes`/
  `python_functions` from the config file; emits file items +
  `::` node ids for classes/functions/parametrize; markers collected
  from decorators. Native `collect`: `pytest --collect-only -q
  --junitxml`/`--co -q` on the worker (opt-in).
- `pytestbdd.py` — pytest items + Gherkin `.feature` parse linking
  scenarios to step defs under `feature_roots`/`stepdef_roots`.
- `behave.py` — `.feature` parse (features, scenarios, outlines/
  examples, tags); execution context = behave on the target.
- `robot.py` — static `.robot`/`.resource` parse (settings, tests,
  tags, templates, Given/When/Then-style keyword cases kept
  distinct from Gherkin `.feature`).
- `cypress.py` — spec glob honoring `specPattern`/`excludeSpecPattern`
  from the configured config file; testing-type label
  (e2e/component).
- `playwright.py` — config-aware spec discovery + `projects`
  variants; native `playwright test --list` opt-in.
- `playwright_pytest.py` — pytest adapter with the
  `pytest-playwright` marker expectations documented.

A `.feature` file is **never** assumed to be Behave/pytest-bdd/Robot
— the user's framework selection decides; wrong selection surfaces
as an actionable validation error, not silent reinterpretation.

### 3.3 Configuration precedence (deterministic, documented)

1. Explicit overrides saved on `FrameworkProject`.
2. The framework's own config file (discovered under
   `project_root` or given explicitly).
3. Framework defaults (shipped per-adapter, shown in the UI).

Unsupported overrides are **rejected with explanation** at
validation time, never silently dropped — e.g. `exclude` patterns a
runner can't express are refused; `shard` is refused for
cypress/kre (existing `_validate_parallel` precedent).

Paths: stored repo-relative, UI shows resolved `binding_root →
project_root → test_root` chain; every resolved path re-checked
with `resolve().is_relative_to(checkout)` — symlink escapes become
warnings/errors (existing gitsync mechanism generalized).

### 3.4 UI flow (project → Binding card → Framework projects)

```
Connect repository            [existing Binding form, unchanged:
                               url, credential ref, ref/subdir]
        │
        ▼
Add framework project         name
                              framework  (radio grid, 8 options —
                                          explicit choice required;
                                          "suggested: pytest (found
                                           pytest.ini)" hint only)
                              project_root   + 📁 repo dir browser
                              workdir        (default = root)
                              config_file    (framework-appropriate)
        │
        ▼
Test & support locations      test_roots[]        + dir browser
        (per-framework fields)  include/exclude globs (defaults shown)
                              feature_roots[]     (BDD only)
                              stepdef_roots[]     (BDD only)
                              support_roots[]     (non-test files)
        │
        ▼
Preview discovery  [button]   POST /bindings/<b>/fp/<fp>/preview
                              → static parse against synced worktree
                              → shows: effective config, resolved
                                paths, item counts by granularity,
                                per-item list, warnings, and
                                "static" vs "needs native collect"
                              → if native: explanatory notice +
                                explicit approve gate (worker-side,
                                isolated; no auto npm/pip install)
        │
        ▼
Save → inventory list         grouped by framework project;
                              per-item select checkboxes where
                              granularity=test/scenario
        │
        ▼
Run form                      selected items → runner + runtime +
                              existing knobs; adapters receive
                              node_ids/--test/--spec selections
```

New files: `templates/portal/framework_project_{new,preview}.html`,
partial `_framework_fields.html` (per-kind fieldsets toggled by
existing external-JS `data-` pattern — **no inline JS**, CSP rule).

### 3.5 Dispatch / selection plumbing

- Dispatch gate widened: `DISPATCHABLE_KINDS` per framework — file
  and test-level items for pytest/robot/node; suite/collection for
  katalon (unchanged).
- `run_config["selections"] = [node_id|spec|test_name, ...]`
  → `pytestfw` `node_ids` (finally wired) / `robotfw --test` /
  `nodefw --spec`/`--project`+grep / KRE `-testCasePath`-style
  filtering where Katalon supports it (else item-level only,
  labeled).
- Selection granularity labels in UI: "file" vs "test" vs
  "scenario" — only levels the adapter executes reliably.
- Refresh: on new `discovered_sha`, diff old vs new item sets
  (added/changed/renamed/removed); saved selections referencing
  vanished items get stale warnings.

## 4. Schema migration (alembic)

| Rev | Change |
|---|---|
| `a2b3c4d5e6f7` | `framework_projects` table + indexes |
| `b3c4d5e6f7a8` | `discovered_items`: +`framework_project_id` (nullable→backfill→FK), +`framework`, +`node_id`, +`granularity`, +`selectable` |
| `c4d5e6f7a8b9` | backfill: one `katalon` FrameworkProject per existing GitBinding (`project_root := coalesce(prj_path, subdirectory)`) |
| `d5e6f7a8b9c0` | `git_bindings.discovery_status` → per-framework-project state kept on the new table |

## 5. Dependencies & security

**New Python deps** (target-side, not server): none required for
static discovery — pytest parsing is stdlib `ast`; Gherkin
`.feature` parsing is a bounded line parser (no `gherkin` package —
note in code why; a real `pytest-bdd`/`behave` native collect uses
the frameworks already on the target). Robot static parse: naive
format parser; if `robotframework` parsing API is proposed later it
is a **target-side** dep, evaluated then.

**Security boundaries** (extend existing):
- Credentials: keep `credential_ref`-only; add URL validation
  rejecting `user:pass@` userinfo on binding save (fixes the
  `last_error` leak path, audit §2.10).
- `cli` git backend must either implement `auth` or refuse to run
  for credentialed bindings (fail loud, not silent).
- Static parse bounds: `_MAX_FILE` 512 KB precedent; add entity-
  expansion guard on XML parse (defusedxml already vendored? —
  verify; else bound + reject DTD).
- Native collection: runs ONLY on worker/SSH target, behind an
  explicit approval + readiness check; timeouts, output caps,
  secret redaction identical to run artifacts; never `npm install`/
  `pip install` as a side effect of browsing or previewing.
- Discovery output is untrusted repo content — escape everything in
  UI (Jinja autoescape) and store bounded.

## 6. Milestones

| M | Scope | Exit |
|---|---|---|
| M0 | schema + `FrameworkProject` CRUD + katalon adapter refactor (parity) | existing tests green, migration up/down clean |
| M1 | pytest + robot static discovery + preview endpoint | preview shows items on seeded conventional repos |
| M2 | onboarding UI (steps 1–4) + dir browser + precedence validation | UI e2e: add repo → select fw → locations → preview → save |
| M3 | BDD adapters (behave, pytest-bdd, robot-GWT distinction) | feature/scenario/tag inventory on fixture repos |
| M4 | cypress + playwright(+pytest) adapters | config-aware spec discovery, variants labeled |
| M5 | per-test selection → argv plumbing (`node_ids`, `--test`, `--spec`) | unselected tests demonstrably don't run |
| M6 | native collection on worker (opt-in) + refresh/diff/stale warnings | isolated-collect works; refresh diff correct |
| M7 | acceptance matrix executed on host+VM, worker+SSH | ledger appended |

## 7. Acceptance matrix (per framework)

Frameworks: katalon(regression), pytest, pytest-bdd, behave, robot,
robot-GWT, cypress, playwright, playwright-via-pytest.

| # | Step | Gate |
|---|---|---|
| A | add repo | URL/cred/ref; no creds in logs or stored URL |
| B | select framework | explicit choice; wrong choice → actionable error, not fallback |
| C | project + test locations | multiple roots, spaces/Unicode paths, nested configs |
| D | preview discovery | static items+warnings shown before save |
| E | save + select | per-file and per-test selection where supported |
| F | execute on worker | dispatched via UI, real results+artifacts |
| G | execute over SSH | same via agentless target |
| H | negative selection | unselected items demonstrably did not run |
| I | refresh after repo change | added/changed/removed diff + stale-selection warning |
| J | failure paths | missing paths, conflicting config, collection failure — all actionable errors |

Representative fixture repos (to be created under `tests/fixtures/`):
conventional layout, nested layout, multi-root, monorepo
(multi-framework), BDD split dirs, parametrized cases, duplicate
test names, invalid configs.

Live KRE stays subject to the approved-key requirement.
