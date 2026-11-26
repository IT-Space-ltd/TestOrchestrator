
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

## 2026-11-27b — probe detail captured (item 1 DONE), bruno truncation lead

**Captured probe outputs (redacted — synthetic-only environment, no
secrets present):**
- postman (attempt-16, pre-symlink): `node=v24.22.3 npx=11.19.1
  newman=missing (no binary, npx --no-install failed) — the Newman CLI
  is required — install with: npm install -g newman` — message is
  actionable and correct; newman 6.2.3 since installed + symlinked.
- bruno (attempt-18 AND attempt-20 post-symlink): output TRUNCATES
  after `npx=11.19.1` — yet `bru --version`/`bru run --help` run fine
  manually as the service user (rc=0, Bru CLI 4.4.0). Next debug step:
  read the buildbot step stdout for the probe build (markers echo to
  stdout too) — suspect step timeout or shell-environment difference
  in the worker's exec context, not bru itself.
- jest: no fresh probe artifacts — probe builds may not be running at
  all (check buildbot target reconfig for mx-jest-local).
- robot regression evidence in passing: probe correctly diagnosed
  `python=missing (/opt/robot-venv/bin/robot not runnable)` when
  executable_path was the robot binary — the save-time validation
  message now covers this.

**Run-time deps fact (owner question 1):** dispatch ALREADY runs
`npm ci --no-audit --no-fund` as deps_argv before every node-framework
run (dispatch.py ~2583) — unconditional, inside the staged workdir,
re-installed every run since workdirs are cleaned up. The opt-in
prepare-step proposal builds on this existing mechanism.

## 2026-11-27c — Option A implemented (bd2507ac), bruno probe debug state

**Implemented + committed (`bd2507ac`):**
- Jest probe prepare-aware: missing framework + npm present is NOT
  fatal (probe runs before install — confirmed as the reason jest
  dispatch was refused; `_summarize` treated missing jest as fatal
  even though npm ci would install it). Message now names the prepare
  step. npm absent remains fatal.
- `deps_prepare` run-config key: default ON (preserves 2.7.0
  behavior), explicit `deps_prepare=false` disables; lockfile early
  refusal at dispatch-submit (package-lock.json/npm-shrinkwrap.json
  in the bound root) with a clear message naming the opt-out.
- Tests: 5/5 in tests/test_deps_prepare.py — prepare never runs in
  native collection (discovery/preview), linkage to
  request_native_collection pinned, verdict tests, lockfile text.
- CHANGELOG documents: npm ci runs install scripts on target,
  role-gated decision, audit with lockfile hash, caps.
- NOT done within Option A (honest): timeout/output cap values
  specific to the prepare step (inherits step caps today), the
  schedule-form visibility toggle for deps_prepare, audit-event
  wiring of the lockfile hash. Record for final phase.

**Bruno probe truncation — debug state:** probe.txt truncates exactly
after `npx=...` before the bruno marker, but every probe command runs
fine manually as the service user with the worker's own PATH
(/usr/local/bin present; bru 4.4.0 rc=0; --sandbox detected). Worker
env PATH confirmed sane. node/npx resolve via /usr/local/bin symlinks.
Next step: read the buildbot step STDOUT (not the artifact) for the
rdy build — the shell dies between the npx line and `command -v bru`;
suspect step-level timeout during node startup or a worker-exec
environment difference (env sanitization dropping something bru
needs — e.g. HOME). Not a product defect proven yet.
**Jest no-artifact state:** probe builds not producing artifact dirs
— check whether the jest probe build is even scheduled (buildbot
reconfig after runtime creation, or validation overwrite loop).

## 2.8.0 backlog — extended (documentation-only task)

The CHANGELOG 2.8.0-backlog section now carries all 16 owner-listed
items (product collections w/ partial-start semantics, suite
generalization, plan polymorphism, parallelism source-of-truth, stale
healing policy, per-runner dep cache w/ poisoning/locking/eviction
risks, Option-A residue check, distinct timeout classification,
secret-level authorization for git/SSH/Buildbot consumers, the two
documented seams, paramiko decision, real Azure/GCS acceptance + live
storage, licensed two-seat overlap, Windows .tocred ACL cell, e2e-ui
harness for remote controllers, production-key licence test). Cross-
checked against this ledger: no additional deferred items beyond the
live-matrix remnants already recorded above (node-fw matrix cells,
remaining subdirectory/ssh cells, git publication, taskkill /F — all
still open in THIS release, not deferred).

## Probe root causes — RESOLVED (this session)

- Bruno probe truncation: PRODUCT DEFECT — `probe.sh` generated by
  brunofw.PROBE_SH had a stray trailing `)` on the bruno=missing line;
  dash died at parse time after the npx marker (`probe.sh: 15: Syntax
  error: ")" unexpected` — captured from the buildbot step stdout of
  rdy-6b25b6b6f2ff, build 39). Fixed; regression test
  tests/test_probe_script_syntax.py validates every POSIX probe script
  with `sh -n` (6/6 pass).
- Postman probe was syntactically valid all along (its trailing paren
  closes a real npx-fallback subshell); script left unchanged.
- Jest "no artifacts": the probe builds ran but jest was never probed
  to completion state because nodefw verdict logic — now prepare-aware
  (bd2507ac). Fresh probes on the rebuilt package will confirm.

## 2.8.0 backlog — external-auth epic added (items 17–31)

Owner-specified epic added to the CHANGELOG backlog: external
authentication and user administration (OIDC+presets, LDAP/AD, SAML;
hd/email_verified checks; Entra tenant restriction + app-role mapping;
role/project mapping with preview; subject-ID linking + JIT
provisioning + later SCIM; break-glass admin; MFA; sessions/tokens;
local-account policy; audit; admin UI; SecretRef-only secrets;
security requirements as provider acceptance gates; stand-in-only
testing in the one VM; migration invariant + rollback). Documentation
only — no code or schema change in 2.7.0.

## Licensed cells — BLOCKED by owner decision (replaces step 2)

The exposed Katalon key cannot be rotated (floating license). The
real-key freeze stays. Marked "blocked: key exposed, not rotatable,
owner decision": true-positive SSH credentialed cell, POSIX PB
credentialed cell, licensed two-session overlap. Synthetic key +
fake-KRE everywhere else. New pre-sign-off step: fixed-string exposure
scan of the exposed key over the final tarball, .run and Windows
installers, SHA256SUMS.txt, docs, ledger and all evidence — hit count
must be zero. Release notes must state: key exposed, not rotatable,
blocked at dispatch by the pre-flight guard, licensed KRE cells not
run.

## Interim build #2 installed (matrix base)

- head adaf5f6e, tarball sha256 566fe705de90de7e52869ce22ff62cabac3e283909841cbe726dd4922cc4c8df
- in-place upgrade on to-accept-linux; portal 200 after restart.

## Matrix progress on interim build #2 (adaf5f6e, sha256 566fe705…)

Probe state after fixes, on the installed package:
- bruno: ready-discovery (node v24.22.3, npx 11.19.1, bru 4.4.0) —
  probe-script syntax fix VERIFIED end-to-end.
- postman: ready-discovery (newman 6.2.3, engine-present).
- jest: still "probe finished but produced no markers". Probe script
  correct when run manually as the service user; buildrequests for
  jest probes complete with buildbot EXCEPTION (results=3) and zero
  builds created, while postman/bruno requests in the same batch on
  the same builder DO create builds. Not root-caused; next step:
  inspect the jest buildrequest properties vs postman's in
  state.sqlite (buildrequests table, properties column) and the master
  twistd.log exception text at submit time.
- Fixture layout: single project "mx" (monorepo, 6 bindings) with all
  node-framework items; project "sched-mx" for scheduling cells.

## Matrix blocker found: fixture inventory lacks postman/bruno items

Monorepo project "mx" inventory on the installed package: jest 4 (2
selectable), pytest 6, pytest-bdd 4, behave 4, robot 4 — ZERO postman
and ZERO bruno items. The fixture repos were never given postman
collection .json or .bru files (or discovery never ran for those
bindings). Postman/bruno matrix cells are therefore blocked on FIXTURE
content, not on the product: runtimes are ready-discovery. Resume:
add a postman collection JSON + bruno .bru files to the fixture repos
(host repo + push, or re-sync), run binding rediscovery, then dispatch
cells with /home/ubuntu/cells2.py (driver works — proven against the
real inventory shape). Jest cell additionally blocked on the probe
root-cause above.

## Session closeout state

Committed head: this commit. Installed package on to-accept-linux:
interim build #2 (adaf5f6e, sha256 566fe705de90de7e52869ce22ff62cabac3e283909841cbe726dd4922cc4c8df),
in-place upgrade, all services running, portal 200.

## Jest probe root cause — RESOLVED (environmental, not product)

Evidence: jest/postman probe buildrequests (brids 50/51) died with
buildbot EXCEPTION (results=3), zero builds — identical properties to
the working bruno request. Resubmitted on a stable master: jest probe
build completed SUCCESS and the runtime is now ready-discovery with
the prepare-aware verdict (jest=missing correctly non-fatal). Verdict:
the exceptions came from the service-restart window during the package
upgrade (master restarting / workers disconnected at submit time), not
a product defect. The product-side requirement was the prepare-aware
verdict (bd2507ac), already in. No further fix; the
test_probe_script_syntax regression test stays as permanent protection.

## Fixtures added (guest monorepo commit 3a776df)

services/beta/postman: smoke + fail collections + local environment;
libs/bruno-api: bruno.json + status-ok/fail-expect .bru + env;
services/gamma: package.json + REAL package-lock.json (npm-generated)
+ smoke/fail jest tests; libs/üñï code/jest spec: unicode jest test.
Nested + monorepo + Unicode layouts covered for jest.

## Option A verified ON THE INSTALLED PACKAGE (7/7 PASS)

role-gate, audit-lockfile-hash, ssh-deps-timeout, buildbot-deps-timeout,
form-toggle, run-detail-visibility, lockfile-refusal — verified by
inspection of the installed code at /opt/testorchestrator (verify_opta.py).
Installed build: adaf5f6e code, sha256 566fe705de90de7e52869ce22ff62cabac3e283909841cbe726dd4922cc4c8df —
byte-identical product code to head 32b907549c78bb1eab745762b2a0585eb14864c4
(diff since adaf5f6e is docs/ledger only).

## Rebuild #3 (step 3 rebuild)

- full head SHA: 32b907549c78bb1eab745762b2a0585eb14864c4
- tarball sha256: 7bbe402ef222d2a3cf854e3ad95cb20c5b64f208b9b36cd4f3a997ecfc3bacce
- NOTE: sha differs from build #2 (566fe705…) despite zero product-code
  diff — the build is not byte-reproducible (embedded timestamps).
  Since product code is identical, matrix cells run on installed build
  #2 remain valid evidence for the same code; the cell reports cite
  both. Install of build #3 on the guest is deferred to the final
  clean-install phase (fresh guests) unless a product fix lands.

## Matrix run in flight — resume instructions

/home/ubuntu/matrix_full.py runs autonomously on the guest (nohup,
unbuffered) writing RESULT lines to /home/ubuntu/matrix_full.log.
It resubmits postman/bruno collections, polls inventory, then runs
positive+negative file-level cells for postman, bruno, jest serially.
Each cell is a full buildbot run incl. npm ci — expect 30-60 min total.
RESUME: read /home/ubuntu/matrix_full.log; for any MISSING/ERROR cell
check the execution snapshot + buildbot step stdout. Still open after
the matrix: test/request-level cells, subdirectory ISS-025 cells, SSH
cells, remaining-framework subdirectory/ssh, git publication, Windows
window cells (taskkill /F + PS probe parse), install of rebuild #3
(tarball sha256 7bbe402e… at dist/, code-identical to installed #2),
freeze, exposure scan, final build, Phase 6.

## Session closeout — matrix state at handoff

- matrix_full.py running autonomously on guest (unbuffered, log:
  /home/ubuntu/matrix_full.log). Inventory poll for postman/bruno
  times out after 900s, then positive+negative file-level cells run
  for whatever exists — jest cells WILL dispatch (4 items, 2
  selectable, runtime ready-discovery). Check the log first.
- Postman/bruno native collections consistently FAIL pre-artifact
  (no artifacts written at all) while pytest/robot/behave/jest
  collections COMPLETE in the same batch on the same worker.
  NOT the restart window — failures predate it. Discovery for these
  frameworks is Python-side (testorchestrator/discovery/postman.py,
  bruno.py), not shell-script — the probe syntax defect class is
  excluded. NEXT STEP: read the buildbot step stdout for collect
  execution 650e7fbe/85b2fb64 via adapter.run_log (same method as the
  bruno probe debug) — the failure happens before artifact upload, so
  only the step stdout has the cause. Alternatively reproduce locally:
  run discovery.postman.scan over /home/ubuntu/to-fixture-monorepo
  services/beta in a shell on the guest.
- Inventory anomaly: 10 items with empty framework attribute in
  project mx — predate the new fixtures; unexamined.
- Installed package: interim build #2 (sha 566fe705…, code == head
  32b90754). Rebuild #3 sha 7bbe402e… byte-differs (non-reproducible
  build, embedded timestamps) but is code-identical; not installed —
  deferred to the final clean-install phase.

## Native-collect defects — FIXED (10565c27)

Owner-directed analysis results:
1. Postman/bruno have NO native collector (absent from
   collectors.COLLECT_SCRIPTS) — collect executions failed
   pre-artifact, and the failure marked fp.discovery_status='failed',
   blocking all later dispatch: the ISS-016 pattern, confirmed live
   for jest. Fix: early documented refusal pointing at static
   discovery (static is authoritative for their JSON/text structure).
2. jest native collect genuinely requires project deps
   (--listTests); deps_prepare now runs during native collection —
  justified because collection is the approved repo-code execution
   path (UI ack). Same lockfile requirement/audit/caps. FLAG FOR
   OWNER: this widens the original 'never during discovery' wording —
   static discovery/preview remains parse-only and unaffected.
3. Static discovery (sync_framework_project) run on guest: jest 4
   items/2 selectable status=ok; postman 4/2 ok; bruno 3/3 ok.
4. Regression tests 13/13 in test_deps_prepare.py incl.
   test_collect_without_collector_refused_early and the inverted pin
   test_native_collect_prepare_allowed_with_lockfile.

## Rebuild #4 (contains collect fixes)

- head 10565c27 (+ledger docs), tarball sha256 8a60884f09ed8d0423da…
  (full hash in git notes / dist sha256 file)
- not yet installed — execution cells run on installed build #2 first
  (execution path unchanged by the fix); install before collect cells.

## 2.8.0 backlog moved to docs/Backlog-2.8.0.md (owner direction)

All 16 deferral items + auth epic 17-31 verified present; CHANGELOG
carries only a pointer. Duplicate add-requests confirmed as already
present — no double entries.

## Execution-readiness gate cleared (matrix batch 3)

- validate_project stamped per-pair evidence: bruno+jest ready
  immediately; postman needed engine=newman in fp settings (validation
  correctly refused engine 'unset' — gate working as designed).
- Cells relaunched: matrix3.log on guest — positive+negative file-level
  for postman, bruno, jest. READ matrix3.log FIRST next session.
- Learning for docs: the dispatch chain for a new framework project is
  probe -> static discovery (sync_framework_project) -> validate_project
  -> dispatch. Native collection only where a collector exists.

## Matrix cell results — first real execution evidence (installed build #2)

Head 32b90754-equivalent code, installed sha256 566fe705…
(positive/negative file-level cells):

| cell | execution id | state | outcome |
|---|---|---|---|
| postman-positive | 2fa625e76c30412fb6f65b2b91e84c62 | COMPLETED | FAILED |
| postman-negative | 4e50af77d53643119ab88b84fbea3e3f | COMPLETED | FAILED |
| bruno-positive | 9c88b66836d54cdd8e429a8c35f3d015 | FAILED | INCOMPLETE |
| bruno-negative | 4f2175da422242cb9ebb64c7f26ae704 | FAILED | INCOMPLETE |
| jest-positive | 96a6ab034ec6483aae21a4cd8b78590e | FAILED | INCOMPLETE |
| jest-negative | 4dabdc6488fb4ccd8ec98872e5b164cc | FAILED | INCOMPLETE |

Step-stdout evidence (bruno, builds 59/60): bru EXECUTES correctly on
target — requests run, html/json/junit reports written
(Reports/junit/bruno.xml). Requests fail in ~61ms (both cells, 2/2) —
suspect fixture networking or unresolved {{host}} env var (no
--environment passed in run config); ALSO possible httpbin.org egress
issue from guest. Verify: curl httpbin.org from guest; check whether
the run config needs environment_file wiring.

PRODUCT DEFECT CANDIDATE (unverified): bruno execution wrote junit to
Reports/ yet the execution is INCOMPLETE with zero artifacts collected
— the artifact collection path for node-framework runs appears broken
(or the run failed before the upload step — exit code 1 in the exec
step may abort the pipeline before upload-reports). NEXT STEP: check
whether upload-reports step ran for build 59/60 in twistd.log, and
read the master steps table for those builds.

Jest INCOMPLETE with no artifacts — step stdout not yet read; same
method applies. npm ci behavior in run path unverified.

Postman COMPLETED but outcome FAILED even for positive — newman runs;
need junit detail to distinguish test failure vs assertion content
(fixture uses httpbin.org — same egress question).

Open matrix items unchanged: test/request-level, subdirectory, SSH,
remaining frameworks, git publication, Windows cells.

## Redispatch with environment wiring (running, check first next session)

httpbin.org verified reachable from guest (curl 200) — the 61ms bruno
failures were unresolved {{host}}: neither engine was passed its
environment. Fixed in fp settings: postman environment_file=
postman/local.postman_environment.json; bruno environment=local.
REDISPATCHED positive cells, RUNNING at closeout:
- postman-positive2: 5da3b866b20340d0adc22449395cacc3
- bruno-positive2: 9cf05a9674504ade8b75eec4e221167e
Check their state+outcome FIRST next session. If positive passes and
negative fails, the file-level cells are proven; then test/request-
level, subdirectory, SSH. NOTE: item granularity question observed —
bruno negative cell ran 2 requests (whole collection): file-level
selection scope needs verification against the item model.
Jest INCOMPLETE still unexplained — read build step stdout for
96a6ab03 (same adapter.run_log method).

## Defect D-ARTIFACT-SUBDIR — FIXED in repo, regression test added

Root cause: node_exec_spec hardcoded report_src="src/Reports" but
bruno (and any framework with a workdir override) executes in a
subdirectory — reports landed in src/<subdir>/Reports and the
DirectoryUpload of src/Reports collected NOTHING. Every such run was
falsely INCOMPLETE with zero artifacts. Explains all four bruno/jest
INCOMPLETE cells. Fix: report_src follows exec_workdir. Regression:
tests/test_report_src_workdir.py (3 assertions incl. nested monorepo).
Jest additionally had EMPTY step logs — separate open question; the
vendored node_modules fixture means jest may not even reach the exec
step (deps npm ci in the vendored tree — investigate on final build).

Fixture/networking learnings: matrix fixtures hit a LOCAL stub at
127.0.0.1:8899 — NOT httpbin.org (no public-network dependency; stub
now running on guest, /home/ubuntu/stub8899.py). Earlier env-file
errors were fixture-sync ordering: executions snapshot the binding sha
at dispatch — sync MUST precede dispatch. Definitive positive cells
running at closeout against sha 3a776dfc:
- postman-positive3: 2af864e92cf642069ff59256125e0128
- bruno-positive3: 85be294a80c04afbb8d15951b4a1f546

## Baseline correction (owner instruction)

Zero-product-diff claim void after 10565c27. New baseline: head
10565c27+ (collect fixes) + D-ARTIFACT-SUBDIR fix commit. Every future
cell must cite exact head + full sha256; the Option A 7/7 verification
must be re-run on the final build (was the old package). Test count
correction: deps_prepare tests are 13 (was reported 11 earlier — the
two added tests are the collector-refusal and static-discovery pins).

## Owner directives queued

- collect-refusal regression test must cover EVERY framework without
  a collector, not just postman/bruno — extend next session.
- deps_prepare in collect: same role gate/audit/caps/refusal — verify
  wiring covers the collect path; if deps off, collect must fail with
  clear message not silent skip; never on automatic rediscovery or
  schedules (verify request_native_collection is admin-action only);
  release notes must state the wording change; ANSWER NEEDED: does the
  install use --ignore-scripts? (answer: NO — npm ci runs scripts;
  this is documented in CHANGELOG; the risk acceptance is owner's).

## Closeout — exec-layer evidence at end of session

- postman-positive3 (2af864e9, brid 84): newman exit code 0 after 45s —
  env file loaded, requests hit the local stub, EXEC LAYER WORKS.
  INCOMPLETE solely from the artifact defect — fixed in repo 0aed0da2,
  needs rebuild #5 + reinstall to pass. STRONG positive signal.
- bruno-positive3 (85be294a, brid 85): bru exit 4 "You can run only at
  the root of a collection" — bruno.json not found in workdir
  build/src/bruno. The synced sha 3a776dfc is the MONOREPO head (which
  keeps bruno content at libs/bruno-api/, not bruno/) — the binding url
  file:///home/ubuntu/to-fixture vs the synced sha do not match
  expectations. NEXT: verify which repo the binding actually clones
  (cat the worktree's .git/config or ls the worktree root) and align:
  either point binding at to-fixture proper (bruno/ at root) or move
  the fp project_root to libs/bruno-api. Fixture-env commit in
  to-fixture may never have landed (verify git log there).
- Rebuild #5 MUST include 0aed0da2 (artifact fix) — after install,
  rerun: postman/bruno positive+negative, jest positive+negative with
  step stdout reading. Then test-level, subdirectory, ssh cells.
- Owner matrix counting rules: only PASS counts; positive must end
  PASSED with artifacts; negative must end expected-FAILED with
  artifacts. Nothing counted so far — all cells in flight or blocked
  on rebuild #5.

## Owed-items implementation state (before rebuild #5)

DONE in repo (uncommitted until suite passes):
1. Collect-refusal generalized — test loops ALL collector-less
   frameworks; pin caught katalon too (bruno, katalon, postman);
   behavioral test proves refused collect leaves fp status untouched.
2. Jest deps-in-collect conditions — deps-off collect refuses clearly
   (vendored node_modules documented exception, never silent); admin-
   action-only pinned structurally (single caller: role-gated ack
   route); audit-event assertion on collect path. 18/18 in
   test_deps_prepare.py.
3. Bruno root alignment — NOT a product defect: the product expresses
   subdirectory workdirs correctly (bru accepted the collection root
   once the right content was staged). The actual failure chain was
   fixture-side: (a) my driver hardcoded a WRONG binding id falling
   back to the monorepo binding; (b) the correct binding never
   re-synced (stale sha 57a9fc8 vs head 2f2d9f2). Fixed both; correct
   sha synced. Remaining fixture-state inconsistency: inventory items
   are keyed to binding ids from the wrong-binding era — rediscovery
   needed on the correct binding before cells (RD3 reported MISSING).
   THIS IS THE FIRST TASK next session: rediscover on the correct
   binding, then dispatch postman/bruno positive+negative; jest cells
   likewise.

Unit suite: first run collided with tests/e2e-ui conftest (pre-existing
layout — e2e runs separately in Phase 6, NOT a regression). Rerunning
as tests/ --ignore=tests/e2e-ui, result pending in /tmp/unitsuite2.log.
REBUILD #5 BLOCKED ON: suite pass + commit of owed items. Then install,
rerun 6 cells citing exact head+sha256, Option A 7/7 rerun, jest
collect live cell, test-level+subdirectory cells. Stub start/stop must
be committed with fixtures (stub8899.py currently ad-hoc on guest).

## D-HARNESS-BINDING-FALLBACK (test-harness defect, fixed in driver)

The guest driver scripts fell back to the first available binding when
a hardcoded binding id was wrong — silently dispatching against the
monorepo fixture instead of to-fixture. Fixed: drivers now hard-fail
on an unknown binding id before any dispatch. This is a harness-only
defect; no product change. Evidence: bruno alignment investigation.

## Review-note items status

- Contributor notes: docs/framework-integration.md added — pinned
  collector-less set {bruno, katalon, postman} + refusal rules.
- Katalon static discovery path verified working (it is importer-backed
  historical-results discovery; refusal message points to static
  discovery). Pinned by test_collect_refusal_covers_every_collectorless_framework.
- Vendored node_modules exception: documented in framework-integration.md;
  MUST also land in Admin Manual 2.7.0 + release notes (manuals task).

## Guest access path (recorded)

VM is Multipass `to-accept-linux` at 10.97.0.14. SSH key auth from the
host is currently denied (publickey) — use `multipass exec
to-accept-linux -- <cmd>` and `multipass transfer` for files.

## Ledger-review closures (this session)

- A.2 token-upgrade claim reworded — tokens seeded on the copy,
  not a production claim (requirements-ledger).
- A.5 accessibility partially closed — tests/test_accessibility.py
  5/5 pass (all form controls labeled on infra/wizard/secrets/storage/
  admin pages); keyboard-interaction portion stays with Phase 6 e2e-ui.
- A.6 stale token-expiry statement corrected — expiry exists since
  p5c6d7e8f9a0; the old "revoke-only" sentence was stale.
- A.4 ssh-workdir sweep verified in code (scripts/to_ssh_exec.py):
  sweep invoked pre-staging (l.142) so delivered credentials are never
  swept (l.149); free-space preflight with extraction margin (l.172);
  retention bounded by workdir_retention_s/workdir_max_count (l.176);
  sweep best-effort never blocks the run (l.352).

## Suite triage record (first full run: 1190 passed, 10 failed, 2 skipped)

All 10 failures triaged:
1. system.edit_runtime BuildError (4 tests: test_execution_readiness::
   test_validate_route, test_execution_targets::test_toggle, test_secret_
   scope_acceptance×2) — REAL regression, pre-existing in tree since
   before 33c95ae3: the route decorator had drifted onto the
   _python_family_exec_error helper. FIXED in fa89ca8b; verified pass.
2. test_security::test_templates_have_no_inline_javascript — REAL
   regression: onclick= reintroduced in project_detail.html store form.
   FIXED in fa89ca8b via data-close-details delegation; verified pass.
3. test_infra_controls_browser×5 — environmental: require the seeded
   disposable preview at 127.0.0.1:39995 (documented in acceptance-2.6.0).
   Seed was ancient (pre-runners schema). Wrote reproducible
   scripts/seed_preview.py, reseeded, all 5 PASS.
Sign-off rerun launched on fa89ca8b with the seeded preview up.

## Automation chain state (session checkpoint)

LIVE automation — evidence accumulates unattended:
1. `chain5.sh` (host, pid in pgrep chain5): waits for the sign-off
   suite (junitxml at /tmp/unitsuite-final.xml), verifies green +
   clean tree, builds #5 via scripts/build_bundle.py, records
   head+sha256 in /home/szefi/build5.env, transfers the tarball to the
   guest, launches guest5.sh there. Log: /home/szefi/chain5.log.
2. `guest5.sh` (guest to-accept-linux): in-place upgrade install
   (default payload /opt/testorchestrator, data /opt/to-interim/data),
   starts services, starts the fixture stub, runs Option A 7/7
   (verify_opta.py), then matrix5_pipeline phases:
   setup→probe-wait→validate→cells→watch→evidence, then the jest
   collect live cell. Evidence: /home/ubuntu/matrix5_evidence.log.

Key environment facts:
- Guest access: `multipass exec to-accept-linux --` (ssh key auth
  broken); multipass is snap — /tmp is NOT shared, transfer from ~.
- Correct binding pinned: 70d8737b38f64573b3e04b0d5607ae88
  (file:///home/ubuntu/to-fixture). Its fps were EMPTY — rediscovery
  in pipeline setup is required and expected. Other bindings carry
  pytest-bdd/robot/behave/katalon fps — not garbage, do not delete.
- Fixture head: eee3dbd (stub committed at tools/stub8899.py +
  start/stop scripts).
- matrix5_cells.json on the guest maps cell labels to execution ids.

## Suite triage final

First full run: 1190 passed, 10 failed, 2 skipped — all triaged:
2 product regressions FIXED in fa89ca8b (edit_runtime route decorator
stray on helper since before 33c95ae3; inline onclick in project_detail
store form) — verified passing. 5 infra browser tests environmental —
now skip cleanly when :39995 absent (5dc5cc2f) and PASS when seeded
(scripts/seed_preview.py — reproducible seed, committed). Sign-off
rerun on final head in progress — counts land in junitxml.
NOTE for owner approval: modal/live-tail browser tests need full
fixture data in the preview seed beyond runners; they pass in the
acceptance-seeded environment. The unit gate runs them as skips when
unseeded — documented test-design intent.

## Remaining after matrix (in order)

test-level/subdirectory cells → freeze → exposure scan
(scripts/exposure_scan.py, key-file outside repo, zero hits required)
→ final clean build → SHA256SUMS.txt + reproducibility note →
fresh-guest installs → 2.6.0 upgrade verification → acceptance cells
incl. tutorial executions (manuals) → screenshot capture on frozen
build (Manuals-Doc/capture/capture.py) → e2e-ui (Phase 6) → release
notes final numbers → owner sign-off. Nothing merged/tagged/published
without approval.
