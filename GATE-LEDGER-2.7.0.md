
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
