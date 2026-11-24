# 2.7.0 Plan — framework-aware repository onboarding & discovery

Status: **implementation in progress**. Baseline
`main@3855e29d` (post-merge head containing all accepted 2.6.0 work;
identical content to released tag `2.6.0` plus the merge commit).
Branch `feature/2.7.0-repository-discovery` created from it.

**Authorization status**: the §8 read-only stop is superseded —
product code, regression tests, disposable-database migrations, and
creating/updating a draft PR are approved. Still requiring explicit
approval: live-data migrations, new privileged host changes,
separately gated dependencies, merge/tag/publish, VM provisioning.

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

`GitBinding` unchanged — `subdirectory` stays the checkout-level
scope; each binding gets an implicit `katalon` `FrameworkProject`
with `project_root=""` (binding-scope root). **Review correction:**
the backfill derives from *effective* behavior — discovery ran
under `worktree+subdirectory` and rglobbed for exactly one `.prj`;
`prj_path` was stored-but-ignored, so it is recorded only as
informational `config_file` text and does NOT re-root discovery.
Legacy columns are retained (no drop in 2.7.0).

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

**Draft save:** a framework project can be saved at any time —
even when discovery cannot run yet (no worker available, repo not
yet synced, no checkout). The states are strictly separated:
**"configuration saved"** (draft — editable, not executable) vs.
**"discovery validated"** (preview succeeded → execution unlocked).
The Run button for a framework project stays disabled until
discovery validated; saved drafts show their status as a badge.
Model side: `discovery_status` on `FrameworkProject` —
`draft|pending|ok|stale|failed`. A `stale` status means the saved
configuration is intact but the inventory needs a refresh before
use (new repository revision, changed settings); stale projects
show a refresh hint and cannot dispatch either.

### 3.5 Field-by-field onboarding (required / optional / framework-specific)

**Step "Connect repository"** (existing Binding form, unchanged):

| Field | Status | Note |
|---|---|---|
| Repository URL | required | https/ssh/local; userinfo (`user:pass@`) is **rejected** |
| Credential reference | optional | SecretRef name; never a value, never in URL/logs |
| Ref (branch/tag/commit) | optional | default `main` |

**Step "Framework project"** (new):

| Field | Status | Applies to | Note |
|---|---|---|---|
| `name` (display name) | required | all | free text |
| `framework` | required | all | explicit choice; auto-detection is a hint only |
| `project_root` | required | all | relative to checkout; dir browser + free text |
| `workdir` | optional | all | default = `project_root` |
| `config_file` | optional | all (katalon fixed to `.prj` root) | framework default is searched; override settable |
| `test_roots[]` | required (≥1, pre-filled default) | all | default e.g. `tests`/`src` per framework |
| `include`/`exclude` | optional | all | globs, framework defaults pre-filled |
| `feature_roots[]` | BDD-required | behave, pytest-bdd | default `features/` or `test_roots` |
| `stepdef_roots[]` | BDD-optional | behave, pytest-bdd, robot-GWT | default `step_definitions/` |
| `support_roots[]` | optional | all | fixtures/resources — never listed as tests |
| `settings_json` | optional | Playwright projects, Robot var-files, pytest addopts | per-adapter |

### 3.6 Framework capability matrix (target state)

| Framework | Static discovery | Selection granularity | Native collection | Limitations |
|---|---|---|---|---|
| katalon | XML parse `.tc`/`.ts`/`.glbl` (current) | suite/collection (file); case via run filters only | not needed | unchanged, parity |
| pytest | AST parse (`test_*.py`, classes, functions, parametrize IDs, markers) | **file + test** (`::nodeid`) | optional (`--collect-only`, deeper: fixtures/conftest) | static parse cannot see dynamically generated tests (fixtures, plugins) |
| pytest-bdd | pytest AST + Gherkin parse | file + scenario | optional | binding matching not always unambiguous statically |
| behave | `.feature` parse (scenarios, outlines/examples, tags) | file + scenario | optional | step matching evaluated at run time |
| robot | `.robot` parse (tests, tags, templates, GWT style) | file + test (`--test`) | optional (libdoc-like) | dynamic/test templates only partially visible statically |
| cypress | `specPattern` glob from config | **file only** (`--spec`) | optional (no standard `cypress --list` → stays manual) | no per-`it()` selection in UI (not reliable) — clearly labeled |
| playwright | spec glob + `projects` from config | file + (`--grep` test if `--list` collect used) | recommended for projects/variants (`--list`) | per-test selection via grep unstable with special chars → labeled |
| playwright-via-pytest | same as pytest | file + test | optional | needs `pytest-playwright` on the target (probe) |

**Plain-language rule:** where only file-level selection is
reliable (Cypress), only file-level is offered and labeled as such
— no silent downgrade.

### 3.7 Dispatch / selection plumbing

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
| `b7c8d9e0f1a2` | `framework_projects` table + `discovered_items` columns (`framework_project_id` FK via named-constraint batch mode, `framework`, `node_id`, `granularity`, `selectable`) |
| `c8d9e0f1a2b3` | backfill: one `katalon` FrameworkProject per existing GitBinding — `project_root=""` (binding scope already includes `subdirectory`); `prj_path` kept informational in `config_file`, NOT re-rooted (review correction) |
| `d9e0f1a2b3c4` | `discovered_items` +`tags`/`fingerprint`; `framework_projects` +`discovery_warnings_json`/`discovery_fingerprint` (config-fingerprint staleness, not just git SHA) |

**Existing-data guarantee:** existing bindings, suites, releases,
schedules and stored executions keep **bit-identical behavior** —
the migration creates exactly one `katalon` FrameworkProject per
existing binding, preserving the effective paths (`subdirectory`
scope; `prj_path` informational only — it was never read). No
existing object changes framework, paths or selection;
`Execution.framework` is stamped correctly only for **new** runs
(historical rows stay untouched). Visible change for existing
users: none — the Katalon inventory list shows the same items
through the same binding.

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
- Static parse bounds: `_MAX_FILE` 512 KB precedent; switch XML
  parsing to `defusedxml.ElementTree` (already vendored, 0.7.1) —
  closes the internal-entity-expansion hole in stdlib `ET`.
- Native collection: runs ONLY on worker/SSH target, behind an
  explicit approval + readiness check; timeouts, output caps,
  secret redaction identical to run artifacts; never `npm install`/
  `pip install` as a side effect of browsing or previewing.
- Discovery output is untrusted repo content — escape everything in
  UI (Jinja autoescape) and store bounded.

## 6. Milestones

**Status update (post-review):** M0–M5 are **implementation
complete — acceptance pending**, not final capability acceptance.
The reported test run (20 new + targeted existing suites) is
targeted evidence; the full regression gate runs in M12.

| M | Scope | Status | Implementation / tests |
|---|-------|--------|------------------------|
| M0 | schema + `FrameworkProject` + katalon parity | impl. done | `execution.py` model; `b7c8d9e0f1a2`/`c8d9e0f1a2b3`/`d9e0f1a2b3c4`; backfill from effective behavior (tested 5 binding shapes) |
| M1 | pytest + robot static discovery | impl. done | `discovery/pytestdisc.py` (AST, exact `::nodeid`, parametrized→candidate); `discovery/robot.py` (suites/tests/tags/`[Template]`/GWT); `tests/test_framework_discovery.py::test_pytest_ast_discovery`, `test_robot_tests_tags_templates` |
| M2 | onboarding UI + browser + precedence | impl. done | `FrameworkProjectForm`, routes `fp_new/edit/detail/preview/discover/delete` + `binding_browse`, `framework_project.html`; effective-settings table with source badges |
| M3 | BDD adapters | impl. done | `discovery/gherkin.py` bounded parser (documented English-keyword subset, localized→warnings); `discovery/behave.py` (`path:LINE` exact selectors); `discovery/pytestbdd.py` (`@scenario`/`scenarios()` incl. module-level calls; wildcard→candidate; binding≠step-matching); robot native-GWT distinct from `.feature`; tests `test_behave_*`, `test_pytestbdd_*`, `test_robot_*` |
| M4 | cypress + playwright(+pytest) | impl. done | `discovery/cypress.py`, `discovery/playwright.py` — literal-only config extraction (JS never executed; dynamic keys → 'unresolved statically', no silent defaults); `playwright-pytest`→pytest adapter alias; file-level selection only where reliable; tests `test_cypress_*`, `test_playwright_*` |
| M5 | selection → argv plumbing + gates | impl. done | `dispatch._fp_item_gate` (validated-revision + selectable-only + runtime-kind match, server-side); `node_ids`/`behave_targets`/`spec`/`robot_test` snapshot fields; pytest/behave/nodefw branches; `adapters/behavefw.py` + `behave` runtime kind + probe; tests `test_dispatch_gates`, `test_exact_selection_snapshot_map` |
| M6 | native collection on worker (opt-in) | approved | VM provisioning approved — see §6b |
| M7 | acceptance on host+VM, worker+SSH | approved | ledger to be appended |
| M8 | **GoogleTest + Jest** (selector, adapters, runtimes, dispatch, ingestion) | in progress | §10 |
| M9 | **storage subsystem** (local/mounted/S3 settings + backend interfaces) | planned | §11 |
| M10 | **remote collection + Git publication + retention** | planned | §12 |
| M11 | Results & Artifacts project tab | planned | §13 |
| M12 | integrated acceptance + full regression | planned | §14 |

Milestone evidence ledger: `3024d727` M0+M1 · `46357d43` plan ·
`bbc77e0a` M2 · `bdaca4a7` M5 · `c7910ef2` regression tests.

## 6b. M6/M7 authorization record

Approved: disposable worker VM under documented resource/network/
cleanup plan; native collection on the VM for controlled acceptance
fixtures; browser-driven acceptance (host server + VM worker);
worker and SSH paths. Host inspection precedes provisioning — new
privileged host changes (packages, drivers, services, firewall) are
presented for approval first. Not approved: arbitrary external
repositories, real secrets, privileged host components.

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

## 8. Approval gate and first response

This instruction authorizes **read-only inspection and plan
preparation only** — it does not yet authorize implementation.

Already done in the release session under the earlier explicit
instruction ("merge the 2.6.0 branch, close the not-needed repos,
create the release") — recorded here so the approval list is
unambiguous:

- PR #4 merged into `main` (`3855e29d`) and auto-closed; tag
  `2.6.0` pushed; GitHub release 2.6.0 published with 7 assets.
- Branches deleted (local + remote): `feature/2.6.0-node-runners`,
  `feature/cheroot-frontend`, `release/2.5.1-backports` (all fully
  merged), `spike/cheroot-frontend` (5 unmerged spike commits —
  already productized as the shipped Cheroot frontend).
- `feature/2.7.0-repository-discovery` created from baseline
  `main@3855e29d` and pushed — contains only this plan document.

**Actions that still require approval before execution:**

| Action | Detail |
|---|---|
| M0 schema migration | new `framework_projects` table + `discovered_items` columns + katalon backfill — runs on user databases |
| Product-code changes | new `discovery/` package, portal routes/forms/templates, dispatch plumbing |
| Dependency installs | none planned server-side; target-side needs only frameworks users already have |
| VM provisioning | disposable worker VM for acceptance (milestones M6–M7) |
| PR creation | when implementation starts — opened as **draft** |
| Merge / tag / publish | only on separate explicit approval after acceptance |

No further PR closures, branch deletions, code changes, migrations,
dependency installs, or VM creation happen until the corresponding
actions are approved.

### Draft configuration and discovery validation

The UI must allow a repository and framework project to be saved as
a draft when discovery cannot yet run — e.g. no suitable worker
available or dependencies missing. The three states are strictly
distinguished:

- **Configuration saved** — the settings have been stored (draft).
- **Discovery validated** — discovery completed successfully for a
  specific repository revision and configuration.
- **Discovery stale or failed** — the inventory requires refresh or
  correction before use.

Valid discovery for the selected revision and configuration is
required before executing a discovered selection. A saved draft is
never presented as a successfully parsed project.

### Scope and capability conflicts

Where a requirement conflicts with a framework's capabilities, the
conflict is reported and an explicit alternative proposed — never
silently reduced scope, never seeded inventories substituting real
discovery, never claiming individual-test selection where only
file-level selection is supported (see matrix §3.6).

**After delivering this plan: stop and wait for approval.**

## 9. Review corrections applied during implementation

The reviewer's corrections are folded into the implementation:

1. **Katalon backfill derives from effective behavior** — migration
   `c8d9e0f1a2b3` sets `project_root=""` (binding scope includes
   `subdirectory`); `prj_path` is informational `config_file` text
   only. Tested on: subdirectory-only, prj_path-only, both/
   conflicting, neither-with-nested-.prj, existing inventories.
   No ignored field was activated; legacy columns retained.
2. **Candidates vs validated** — static results emit exact
   executable selectors only where provable: pytest `::nodeid`
   (unparametrized), behave `path:LINE`, pytest-bdd bound
   `@scenario`→`nodeid`, robot `--test` name, katalon/cypress/
   playwright file paths. Parametrized/pytest-bdd-`scenarios()`/
   template/dynamic-binding items are `selectable=False` candidates
   with `needs_native` set — a static preview never unlocks
   individual-test execution where native collection is required.
   pytest-bdd keeps scenario→test *binding* separate from
   scenario-step→step-definition *matching*.
3. **No JS config execution** — Cypress/Playwright adapters read
   only literal `key: "..."`/`[...]` values via bounded regex;
   imported/computed keys warn 'unresolved statically' and explicit
   overrides/roots are used (never silent default substitution).
   Every effective setting records its source
   (override|config|default).
4. **Explicit parser syntax** — gherkin.py documents its supported
   subset (English keywords, Feature/Background/Scenario/Outline/
   Examples/tags/doc-strings; localized keywords → partial-
   discovery warnings, never false validation). robot.py supports
   `*** Test Cases/Tasks ***` names, `[Tags]`, `[Template]`,
   native GWT steps; unsupported constructs warn.
5. **Exact selection is enforced** — node_ids carry file+scope
   context (duplicate names disambiguated); unproven selectors are
   not selectable; Cypress exposes file-level only; `--grep`-style
   approximations are never emitted as selectors. Katalon
   granularity unchanged.
6. **Onboarding consistency** — framework-appropriate scope fields
   (not a generic mandatory `test_roots`; `.` is valid); file-level
   items selectable incl. Cypress specs; defaults are suggestions
   with recorded sources; config fingerprint (JSON of all effective
   settings + adapter version + config-file presence) invalidates
   discovery, not just git SHA; `adapter_version` revalidation via
   the same fingerprint.
7. **Auth/path safety** — URL userinfo rejection (`user:pass@` →
   actionable error; username-only SSH `git@host:` allowed);
   `iter_files` enforces containment, symlink-cycle detection,
   escape skipping, file/dir/item/depth caps; `read_text_bounded`
   caps file size.
8. **Draft without checkout** — FrameworkProject saves in `draft`
   without discovery; gates (validated discovery, selectable,
   dispatchable kinds) are enforced server-side in dispatch, not
   just in the UI.

## 10. M8 — GoogleTest and Jest

### 10.1 GoogleTest (`framework=gtest`, runtime kind `gtest`)

Static adapter (`discovery/gtest.py`): parses literal
`TEST()`/`TEST_F()`/`TEST_P()`/`INSTANTIATE_TEST_SUITE_P` names
under configured test roots — candidates only, never authoritative.
Settings: project_root, workdir, source/test locations, build_dir,
explicit prepare/configure/build commands (run worker-side only),
executable patterns, filters (`--gtest_filter`), timeouts, report
output. Native listing (`<exe> --gtest_list_tests`) runs only in
the isolated worker/SSH stage. Item identity =
executable-path + `Suite.Test`; disabled tests labeled; duplicate
names across binaries disambiguated by the executable component.
Build provenance + executable SHA-256 recorded per run.
Failure taxonomy: prepare/build / collection / test /
infrastructure mapped to distinct execution states.

### 10.2 Jest (`framework=jest`, runtime kind `jest`)

Static adapter (`discovery/jest.py`): literal config extraction
(`jest.config.*`, `package.json` "jest" key) for `roots`,
`testMatch`/`testRegex`, `projects`, `testEnvironment`,
`coverageDirectory`. JS config never executed — dynamic values
unresolved-statically. File-level items selectable; `describe`/
`it`/`test` names listed as candidates (jest `-t` filtering is
regex-based — per-test selection is exposed only where the
identity is unambiguous). Multi-project repos keep `projects[].name`
identity on items. Native `jest --listTests --json` on the worker.
Never auto-snapshot-update (`--ci` always); non-interactive.

## 11. M9 — storage subsystem

`ArtifactBackend` model: `local` (admin-approved root), `network`
(administrator-mounted share — same filesystem contract, approved
subdir), `s3` (bucket/prefix/region/optional endpoint + SecretRef
or workload identity). Connection validation + explicit temp
write/read/delete test on save. Credentials never in URLs/logs/
exports; TLS verified. Tested S3-compatible provider recorded —
no universal-compatibility claim. New destinations apply to new
executions only; historical refs preserved; moving artifacts is a
separate explicit migration.

## 12. M10 — collection, publication, retention

Manifest per artifact: path, size, sha256, content-type, storage
ref, transfer state (pending/uploading/available/failed/expired).
Outcome ≠ transfer status. Idempotent retries without rerunning.
Staged files kept until confirmed or bounded failure-retention.
Git publication: optional commit+push to source or separate
results repo — execution-scoped path
`TestReports/<project>/<execution-id>/<attempt>/`, never
force-push, bounded conflict retries, no report-commit → execution
loop, explicit artifact subset, no LFS auto-enable, separate
write-credential ref. Separate-source-vs-publication commits
recorded.

## 13. M11 — Results & Artifacts tab + access controls

Project tab adjacent to Git settings: storage destination config
+ per-execution artifact views. Enforce: project authz +
cross-project isolation, private-by-default, authenticated
download, untrusted-HTML isolation, path containment/symlink
protection, audit on setting/publication changes, retention
separate from execution metadata.

## 14. M12 — integrated acceptance

gtest built-from-source AND prebuilt; jest multi-project; worker +
SSH; exact selection incl. unselected-did-not-run proof; config
invalidation; local/mounted/S3/Git destinations; concurrency,
conflicts, unavailable storage, retries; historical access after
storage change; access after VM removal; isolation + retention;
publication-loop prevention; FULL regression (not targeted counts)
+ acceptance ledger.
