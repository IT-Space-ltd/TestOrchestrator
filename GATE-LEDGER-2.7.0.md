
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
