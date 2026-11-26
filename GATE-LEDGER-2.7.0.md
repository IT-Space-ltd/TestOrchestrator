
## 2026-11-26 late — schedule targets, tree view, rebuild, ISS-026 validation

**Commits:** `e49283e5` (schedule target kinds), `de4698b5` (tree view),
`e377bbb8` (docs). Interim rebuild: sha256
`77bf18865a28ef2ca3555c6322d80307c930a9831f87e520a52bdf919f6371be`,
source_rev `de4698b5`; head `e377bbb8` differs by CHANGELOG/README only
(docs-only diff verified — zero product content). Package marked INTERIM.
Installed on `to-accept-linux` in place (deps identical; venvs carried;
data/fixtures preserved). NOTE: not a fresh install — Phase 6 requires
the clean-build install path.

**Cells run on the rebuilt package (unique IDs):**
- `d07ea6bb025e` pytestbdd-suite-rerun (fail.feature): completed/failed
  as expected, 1 result, other feature NOT run (negative proven) —
  ISS-026 fix validated end-to-end.
- `64f80837d793` pytestbdd-suite-positive (smoke.feature):
  completed/passed, 1 result.
- Live tree cell: build_tree over real inventory — 9 loose suites, 0
  collections (fixture has no .tsc — correct), template carries tree
  block/aria/repo badges; static assets test-tree.js/schedule-form.js
  serve 200 on the installed portal.
- Feature-suite selectability: 2/2 fixtures selectable post-fix
  (scenarios resolve to node_ids).

**UI-change evidence impact:** the schedule form and project-detail
template changed — affected prior evidence: schedule-form live checks
(pre-rebuild) and any e2e-ui assumptions about the Test tab default
subtab (now "tree"). In-repo modal tests use explicit subtabs —
unaffected. Rerun scope: schedule live cells + e2e-ui on the final
build in Phase 6 (already planned). No other accepted evidence touched.

**Not run (honestly):** jest/postman/bruno matrix cells; scheduled-
collection two-suite live cell; git publication; taskkill /F wrapper
test; subdirectory/ssh cells for remaining frameworks; storage stays
"not run, owner decision"; Phase 6 entirely. 2.8.0 backlog recorded in
CHANGELOG (product collections, suite generalization, plan polymorphism).

## 2026-11-26 night — schedule cells + .tsc discovery defect

- **New defect found + fixed** (`70272675`): `.tsc` collection files were
  never discovered — scan filters matched `.ts` only in both
  discovery/katalon.py and legacy gitsync. Fixed both; regression test
  passes. Rides the final build.
- **Live schedule cells on the installed package** (fake-kre, synthetic
  credential file only):
  - `5c2448469a07` scheduled-collection-2suites — completed/passed, ONE
    execution, units=0 — confirms one-KRE-invocation semantics (one
    capacity slot; timeout/overlap treat it as one run).
  - `ce6fbe710289` scheduled-suite — completed/passed.
  - `efed9fedf042` scheduled-plan — completed/passed.
  - Discovery verified two members [TS1, TS2] on the collection.
  - Limitation: legacy gitsync discovery does not extract collection
    runmode (the new framework adapter does — shown in tree once the
    final build lands).

## 2026-11-26 late-night — node-framework matrix attempt (INCOMPLETE — resume here)

**Done:** schedule cells (see above), `.tsc` discovery fix `70272675`.
Guest toolchain provisioned: jest-cli vendored INTO the fixture repo
(commit 57a9fc8 — node_modules must be committed because staging is
git-sync-based; key learning), newman + bru installed globally and
symlinked into /usr/local/bin.

**Cell status (node frameworks):**
- jest file/test-level, negative, subdirectory, ssh: **not run** —
  blocked at runtime readiness. Discovery persists correctly (4 items,
  suite+test granularity). Probes run but report `target-unavailable`;
  the probe detail was not captured before session end. Next step:
  find the probe output (buildbot steps for the rdy-* builds, or
  re-run the probe manually as the testorchestrator user with the
  staged fixture) — likely PATH/env inside the probe shell or
  expectations about project layout (framework root 'jest' vs where
  npx looks for node_modules).
- postman/bruno: same probe state; postman discovery warns collection
  scripts are repo-code (correct behavior). Not run.
- Validation gate works correctly — dispatch REFUSES with a clear
  message (`not dispatch-ready (target-unavailable)`) rather than
  running unready runtimes. This is correct product behavior.

**Resume recipe:** scripts on guest `/home/ubuntu/nodefw_run.py`
(submit probes → poll_all_pending → validate → sync_framework_project
→ run_cell). RuntimeExecutable paths: jest=/usr/local/bin/node,
postman=/usr/local/bin/newman, bruno=/usr/local/bin/bru — VERIFY these
match what adapters expect (nodefw runs via npx, so executable_path
may need to be npx or the node binary — unaudited).

**Katalon-cert repo:** private/404 — owner asked to make it public or
provide access. Not blocking: synthetic fixture covers the cells.

**Still not run:** remaining-framework subdirectory/ssh cells, git
publication, taskkill /F, nested/monorepo/unicode node layouts,
Phase 6 entirely.

## 2026-11-27 — probe semantics + Katalon format confirmation (items 1-3)

**Item 3 DONE — collection format confirmed from a genuine Katalon
project** (janos-szenfner/Katalon-cert, sha f5b6efe): real projects save
collections as `.ts` files with `TestSuiteCollectionEntity` root —
'Test Suite Collection v1.ts' etc. Discovery over the real repo on the
installed package: 94 cases, 14 suites, 3 collections with correct
membership (e.g. 'Test Suite Collection 3' → All-Search-Engine,
IT-Space-small, IT-Space). Classification is by XML root tag, never the
extension — the `.tsc` scan addition CANNOT misclassify `.ts` suites;
regression test `test_real_ts_suite_not_misclassified` passes (2/2 in
tests/test_tsc_discovery.py).

**Item 2 — tool locations on the target (documented rule proposal):**
- Jest: resolved via `npx --no-install jest` FROM THE STAGED PROJECT —
  project deps must exist in the staged tree. Since staging is git-sync,
  the documented rule: **the project's lockfile deps are installed by
  the operator on the target in the project checkout the binding syncs
  (committed node_modules is a fixture shortcut, NOT the product
  workflow)** — the probe names `npm ci` as the install step.
- Newman: pinned target tooling — either executable_path-pinned binary
  or `npx --no-install newman` resolution. Verified present on the
  guest: newman 6.2.3 on PATH.
- Bruno: `bru` pinned binary at executable_path or on PATH. Verified
  on guest: bru 4.4.0.
- One documented rule proposal (owner approval needed): **operator-
  pinned tooling on the target for CLIs (newman/bru); project-local
  deps for npx-resolved frameworks (jest/playwright/cypress), installed
  per-runner, never auto-installed, never required to be committed.**

**Item 1 PARTIAL — probe output:** probes execute and produce verdicts
(readiness gate correctly refuses dispatch with
`not dispatch-ready (target-unavailable)`); the probe's per-tool
markers are defined in adapters/nodefw.py PROBE_SH with actionable
install steps (`npm ci in the project root, or npm install jest`).
The captured target-unavailable DETAIL from the failed guest probes
was not extracted before session end — probe output lives in the
buildbot step logs of the rdy-* builds on the guest.
