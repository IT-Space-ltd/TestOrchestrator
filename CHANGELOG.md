# Changelog

## [Unreleased 2.8.0]

### Added

- **Reports main menu — starter report slices.** A new
  top-level Reports page provides a project-scoped execution-summary preview
  with period/state/outcome/environment/source-ref filters, aggregate outcome
  cards, a disclosed 5000-row limit, and CSV export. A second report type,
  pass-rate and duration trends, adds browser-rendered Plotly charts, a data
  table, and daily-row CSV export using the same scoped query layer. Trends use
  logical-run semantics so retries cannot inflate counts. A third report type
  ranks top-failing test cases and flaky candidates; the flaky heuristic is
  disclosed inline (at least three executed logical runs with both pass and
  failure/error evidence, ranked by a balanced-instability score). A fourth
  report type breaks non-passed logical runs down by explicit error kind,
  test-failure evidence, or an honestly uncategorized bucket. A fifth report
  type summarizes schedule reliability from final logical-run outcomes plus
  audited misfire, overlap-skip, target-unavailable and fire-failure events;
  zero-run schedules remain visible so silent schedules are not hidden. A
  sixth report type summarizes runner/runtime utilization using terminal
  execution attempts rather than logical runs because retries and partition
  units consume real capacity; busy time is clipped to the report window and
  capacity percentages use the configured dispatch ceilings without clipping
  over-100% evidence. A seventh report type groups results by plan,
  app-side suite, repository suite, or repository collection using immutable
  snapshot target identity; plan rows are explicitly member-execution rollups
  rather than whole-plan-run outcomes, and direct test/case targets are
  omitted and disclosed instead of being folded into a suite row. An eighth
  report type compares frameworks by terminal logical-run outcomes, parsed
  case pass rates (skipped excluded), duration, and project coverage; native
  collection operations are excluded as inventory maintenance and ambiguous
  legacy rows remain in an explicit unknown bucket rather than being guessed.
  A ninth Admin-only report summarizes global audit/compliance evidence with
  full-window event-type aggregates, actor/export counts, bounded detailed
  audit rows, chart, and CSV export; non-admin users cannot select or query it.
  Release traceability links visible release scope items to exact immutable
  binding/kind/path source targets and terminal logical-run evidence; ambiguous
  same-path bindings are never conflated, and the report explicitly does not
  claim requirement/issue traceability because no such link model exists yet.
  CSV rows carry the generated-at instant, viewer timezone, filter snapshot,
  and
  truncation metadata. The query layer is scoped to the signed-in user's
  visible projects before filtering; CSV export is audited and
  spreadsheet-formula-leading text is escaped. PDF/docx/xlsx and additional
  report types remain pending owner-approved dependencies and later 2.8.0
  slices.

- **Reports saved filter sets — first private slice.** Signed-in users can
  save the currently applied Reports filters under a private per-user name,
  apply them later, and delete them. Filter keys and value sizes are
  server-side whitelisted, ownership is enforced on apply/delete, and save /
  delete actions are audited. Shared definitions, scheduled generation and
  share links remain later authorization-sensitive slices.

## [2.7.0] — 2026-11-27

Released on `main` from the merged repository-discovery branch.
Schema changes so far: `projects.retention_json`
(project-level retention overrides); earlier 2.7.0 migrations add
`framework_projects`, `discovered_items` framework/selector/
provenance columns, `artifact_stores`, and discovery fingerprints.
New migration `n2b3c4d5e6f7` adds `secret_refs.scope_json` +
`migration_pending`; `o4b5c6d7e8f9` adds
`runtime_connections.licensing_mode` / `license_refs` /
`license_server_url`; `p5c6d7e8f9a0` adds `api_tokens.expires_at`.

### Added

- **Test tree view (Test tab default — owner decision, recorded).** Read-only inventory tree —
  collection → suite → test cases — with per-level counts, repo badges
  (repository-defined items refreshed on sync), per-framework
  granularity labels (Cypress is file-level only), stale-member badges
  (render-time diff against the current inventory, warn-only — entries
  are never dropped), and last-result badges from a single rollup
  query. Keyboard-navigable (ARIA treeview: arrows, Enter/Space,
  `aria-expanded`, roving tabindex). All discovered content is escaped.

- **Schedule target kinds.** Katalon schedules target a test suite, a
  test suite collection, or a plan — matching the run form. Other
  frameworks target a discovery selection or a plan. The item picker
  filters by kind; collections show member suites and run mode
  read-only. The server validates kind match and rejects mismatches
  with a clear message, ignores picker values for plan targets,
  requires at least one target, and never fails validation silently.
  Timeout/overlap examples state collection semantics (timeout covers
  the whole collection run; a collection is one run for overlap).
  Legacy projects without framework-project rows still offer
  `katalon`; old schedules open, save and run as before.

- **Schedule form per-framework fields.** Jest (test path/name
  patterns), Postman/Newman (collection, environment, folder,
  iterations) and Bruno (collection folder, environment, tags) join
  the framework selector; values map onto the execution-native run
  config the dispatch layer already consumes. Switching framework
  never carries hidden foreign values; the server rejects foreign
  fields by name.

- **CI API token expiry (P3.13).** Optional `expires_at` — default 90
  days at creation, adjustable 1–3650 days, explicit never-expires
  opt-out. Existing tokens migrate to NULL and stay valid. An expired
  token is denied like a revoked one, the denial is audited, and the
  integrations page surfaces expired / days-left (warning ≤14 days) /
  never distinctly. Migration `p5c6d7e8f9a0` (additive, rollback
  verified).

- **KRE licensing modes — online / offline / private.** A KRE runtime
  now declares its licensing mode explicitly
  (`runtime_connections.licensing_mode`, migration
  `o4b5c6d7e8f9`): `online` keeps the existing `-apiKey` credential
  contract (unchanged for all existing runtimes); `offline` needs no
  API key and instead uses genuine Katalon-issued `.lic` files in the
  execution account's `~/.katalon/license` — either
  operator-provisioned or managed through new `license`-kind secrets
  delivered per-run and installed under a `to-<sha>.lic` ownership
  prefix (operator files never touched, `.to_managed` ledger,
  persistent across runs); `private` emits `-serverUrl=<url>`
  alongside the API-key credential. The missing-credential dispatch
  gate is licensing-mode aware, and the **local dispatch path gains
  the gate it previously lacked**. There is deliberately no "hybrid"
  execution mode — hybrid deployments run online- and
  offline-configured runtimes side by side. The readiness probe
  reports the actual execution account, license dir, .lic inventory,
  and managed-marker state without attempting activation. See
  `docs/kre-licensing-modes.md`.

- **Credential authorization scope.** `runtime`-kind secrets now carry
  a grant list (`scope_json`) matching project / runtime / runner
  identities; every dimension is a list — non-empty must contain the
  identity, empty is a wildcard. Dispatch denies resolution with a
  machine-readable `credential-scope` error when no grant covers the
  execution, checked at claim time so revocation is effective. New
  secrets default-deny; saving a `credential_ref` on a runtime records
  a pending association which never bypasses enforcement. Admins edit
  grants on the Secrets page; migrating secrets get grants derived
  from their concrete existing runtime associations (restricted
  `allowed_projects` are preserved inside the grant) and are flagged
  `migration_pending` for review — no automatic broadening.

- **Repository discovery + framework projects.** A Git binding can
  carry named framework projects (`pytest`, `robot`, `playwright`,
  `cypress`, `jest`, `gtest`, `behave`, `pytest-bdd`, `postman`,
  `bruno`, `katalon`). Each project selects its discovery adapter;
  items carry framework, selector (`node_id`), granularity, and
  provenance (`static` preview vs `native` worker collection).
  Candidate items are never executable until validated.

- **Execution-level runtime readiness.** Toolchain probing
  (ready-discovery) is now distinct from execution readiness
  (ready-execution): the (runtime, project) pair must validate —
  association, framework compatibility, validated discovery, engine,
  workspace permissions, browser/plugin evidence, and a result
  ingestion path. Dispatch refuses non-KRE runtimes without current
  per-project evidence; `native_collect` discovery keeps the
  toolchain-only gate. Invalidation on probe results, runtime edits,
  and project-association changes. UI explains every state and offers
  the Validate-for-project action. KRE's existing flow is unchanged.

- **Artifact stores (durable results/artifact storage).** Per-project
  destinations of kind `local` / `mounted` / `s3` with display name,
  per-kind config, active/retire lifecycle, and connection testing.
  S3-compatible stores support endpoint, bucket, prefix, credential
  reference (secrets store only — never inline), and a custom CA
  bundle constrained to administrator-approved roots. Historical
  artifacts keep their original store reference and stay retrievable
  after destination changes.

- **Object Storage Provider selector.** The artifact-store form now
  offers Amazon S3 / Azure Blob Storage / Google Cloud Storage /
  Other S3-compatible with per-provider fieldsets and a store-edit
  flow. Azure Blob uses the documented REST API (Shared Key or SAS,
  no new dependency — `requests`); GCS uses its official XML-API/HMAC
  interop on the existing boto3 stack. Live PUT/GET against Azure/GCS
  is not covered by an emulator on this environment — see the storage
  verification report.

- **Native GoogleTest execution on Windows workers.** The POSIX-only
  gate is removed: Windows PB workers now run gtest suites through a
  staged Python driver (`.to_gtest_run.py`) executed by the runtime's
  configured interpreter — subprocess argv lists (no cmd quoting),
  per-binary `--gtest_filter`/`--gtest_output=xml` runs, sha256
  build-manifest, prepare/configure/build steps, `fail_if_no_test`
  probing, list-tests support, and exit codes matching
  `classify_exit`. Execution uses the `posix=False` spec path —
  Job-object kill-on-close semantics on cancel/master-loss, no sh
  or pidfile dependency. The runtime's `executable_path` is the
  interpreter (e.g. `C:\Python312\python.exe`); the test binary comes
  from discovery/selection as before.

- **Runtime concurrency enforcement.** A KRE runtime's saved "Max
  parallel sessions" is now effective at dispatch: executions beyond
  the cap stay queued with a capacity reason instead of starting
  uncontrolled processes. The cap is checked under the same atomic
  claim as runner slot assignment, so simultaneous submissions cannot
  over-admit; capacity is only released on confirmed termination or
  explicit reconcile — an SSH disconnect never frees a slot. Configured
  capacity stays distinct from KRE license entitlement, which the
  product does not probe. Verified end-to-end on both supported
  topologies — agentless Linux SSH and a Windows PB worker running
  as SYSTEM/session-0 — with controlled synthetic launchers:
  simultaneous submissions, real overlap (process evidence), queueing
  at capacity, cancel and timeout isolation, connection/worker
  interruption without duplicate dispatch, per-execution credential
  ACLs and cleanup, zero orphaned processes, and serialization when
  the cap is set to one.

- **Separate retention policies.** Artifact files and execution
  metadata/parsed summaries now have independent retention (global
  defaults + per-project overrides; operational logs keep their
  existing separate setting). Preview-affected-records before
  enabling destructive policy, explicit confirmation for sweeps,
  audit records on every cleanup. Active executions, in-flight
  transfers, and unverified staged files are never deleted. Expired
  artifacts render as `expired` state — never unexplained
  missing-file errors; the execution summary remains available.

### Changed

- **`authoring.cleanup_abandoned` is wired into the reconcile loop** —
  f00557d8 added it with tests but never invoked it; abandoned drafts
  accumulated forever. Only user-abandoned drafts are touched.
- **`.run` installer build default tracks the current release** — the
  hardcoded 1.9.0 fallback silently wrapped a stale payload; the
  default is now derived from `release/release.json`.

### Removed

- **`adapters/updater.py` placeholder seam** — unwired
  `NotConfiguredError` stub; the real updater lives in
  `testorchestrator/updater.py` with the full verify/drain/apply/
  activate/health-check flow.

### Fixed
- **Windows KRE cancellation/process-tree kill.** The PowerShell
  credential launcher set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` through
  a nested-struct member assignment, which PowerShell writes to a copy;
  the limit silently remained zero and a force-killed wrapper could
  leave the KRE child alive. The launcher now copies the nested limit
  struct out, mutates it, and copies it back. Verified on the Windows
  acceptance guest: `taskkill /F` on the wrapper killed the child,
  removed the staged credential before launch, and leaked no fixed-key
  material into wrapper output. Regression coverage pins the copy-back
  contract.

- **Windows controller upgrade preserves install identity and sessions.**
  The NSIS installer rewrote `testorchestrator.env` before invoking
  `init_env.py`, erasing the existing generated `TO_SECRET_KEY` and
  `TO_INSTALL_ID`; every upgrade regenerated them and invalidated
  sessions/install identity. Deterministic installer wiring is now
  merged into the existing env file, preserving generated secrets and
  operator-added lines while still updating installer-owned keys.
  Regression coverage pins the merge behaviour.

- **Upgrade blocker — installer payload-copy defense (owner ruling from
  the production-like 2.6.0 upgrade cell).** A service unit missing
  from the documented stop list (`testorchestrator-buildbot-ssh`)
  survived the upgrade procedure, held the payload python busy, and
  the copy crashed mid-write — a half-written hybrid install with all
  services down. Both installers (source `scripts/install.py` and
  frozen `toctl install`) now stop every active `testorchestrator-*`
  unit themselves before copying, scan `/proc` for any process still
  referencing the payload tree, and refuse to write until it is
  stopped — no more brick-by-partial-copy. Regression tests
  `tests/test_installer_upgrade_defense.py` (8/8). The Admin Manual
  upgrade procedure gained the missing unit, a post-stop survivor
  check, and a description of the installer safety net.

- **D-NODE-SUBDIR-WORKDIR — node framework execution in monorepo
  subdirectories.** The execution workdir, the `package-lock.json`
  check and spec paths now follow the framework project root
  (`fp.test_roots`) instead of the repository root — jest in a
  monorepo subfolder runs `npm ci` and the CLI in the correct
  directory, with spec paths rebased. Also fixes a pre-existing latent
  crash in the deps-step builder (`run_config` read as a method).

- **Native collection in monorepo subdirectories.** The collector
  script (`.to_collect.js`) is referenced relative to the actual
  execution workdir — previously it was staged at the source root and
  missed with MODULE_NOT_FOUND whenever the project sat in a
  subdirectory.

- **Native collection inventory paths.** Node collectors emitted
  absolute worker-local paths which ingestion stored verbatim,
  polluting inventory with unusable rows. Collectors now emit
  framework-root-relative paths, and ingestion re-prefixes the project
  root for monorepo layouts so native rows merge with static rows.

- **Native collection outcome reflects the operation.** A successful
  collection ended INCOMPLETE because junit aggregation over zero
  cases cannot pass; the outcome now reflects ingestion success.
  Ingest errors were additionally written to a nonexistent attribute
  and silently dropped — they are persisted in `error_text`.

- **Execution snapshots always pin the source sha.** A headless or
  API caller that omitted `source_sha` produced executions with no
  reproducibility pin; the binding's synced sha is now pinned by
  default.

- **Readiness probes advance without UI interaction.** Probe
  completion was processed only when someone opened the
  infrastructure page — an unattended install could never become
  ready. The worker maintenance loop now polls pending probes every
  tick.

- **Probes detect npx-incompatible runtime executables.** A
  node-framework runtime pointed at `node` instead of `npx` passed
  the PATH probes but died at dispatch (`bad option: --no-install`).
  The probe now tests the configured executable with the exact
  invocation shape dispatch uses and fails readiness with a clear
  message.


- **D-ARTIFACT-SUBDIR — artifact collection now follows the execution
  workdir.** The node-framework exec spec hardcoded
  `report_src="src/Reports"`, but subdirectory frameworks (Bruno at
  its collection root, nested monorepo layouts) write reports inside
  their workdir — nothing was ever uploaded and every such run falsely
  ended INCOMPLETE despite the test CLI passing. `report_src` now
  follows the execution workdir. Regression test
  `tests/test_report_src_workdir.py`.

- **Native collect refusal for collector-less frameworks.** Bruno,
  Katalon and Postman have no collector script — a native collect
  request previously failed deep in the pipeline and poisoned the
  framework project's `discovery_status` to `failed`, blocking all
  later dispatch. Collect is now refused early with a clear message
  pointing at static discovery, the refusal never touches
  `discovery_status`, and a pinned test loops over every
  collector-less framework. Jest native collect runs `deps_prepare`
  first (npm ci **without** `--ignore-scripts` — install scripts
  execute; explicit admin action only, same role gate, audit event
  with lockfile hash, timeout caps and lockfile requirement as the
  dispatch path). With deps preparation off, collect fails clearly —
  except when `node_modules` is vendored in the repository, the
  documented exception — and never silently skips the install.

- **POSIX probe scripts — syntax regression guard.** The Bruno probe
  carried a stray `)` that failed `sh -n`; all six POSIX probe scripts
  are now syntax-checked by `tests/test_probe_script_syntax.py`.

- **ISS-023 — cancel intent now governs the terminal state across
  Buildbot retries.** A cancel racing a retry could be lost: the retry
  completed with passing results and the execution reported
  `completed`/passed despite the operator's cancel. The classification
  captures cancel intent before the collection pipeline, clears
  contradictory unrequested-abort text, and refreshes the row before
  reading intent (a heartbeats-stale row could misclassify a requested
  cancel). Verified live on Linux ssh transport: queued, dispatched,
  running and mid-retry cancels all end `canceled` — the mid-retry
  cell (`7aaaf9e5849e`) killed the dispatcher mid-run, the cancel won
  the retry window and no retry ever ran.
- **ISS-024 — ssh remote workdirs are bounded.** `to_ssh_exec` never
  removed per-execution remote directories; 1.5G accumulated on the
  acceptance guest filled /tmp and broke SFTP staging. Workdirs are
  removed after collection (success, failure, confirmed cancel) and a
  preparation-time sweep removes stale marker-carrying siblings older
  than 24h — foreign directories are never touched; `keep_workdir` is
  an explicit debugging opt-out still bounded by the sweep.

- **ISS-022 — blocked Windows retries no longer execute; executions
  classify UNKNOWN.** A retry blocked by the prep-step guard
  (`TO_RETRY_BLOCKED`, exit 70) previously continued through
  fetch-source and re-ran the test CLI to completion because
  `ShellCommand` defaults `haltOnFailure=False` — the no-relaunch
  policy violation was invisible, the execution even showed
  `completed`. All pre-run gate steps now halt on failure, the
  portal checks for the block marker before accepting results, scans
  the correct Windows step (`prep_1`, buildbot dedups duplicate step
  names), and the execution classifies `UNKNOWN` with the
  retry-blocked message per the W6-kit spec. Verified end-to-end on
  Windows PB (worker killed mid-run): the retry halted after prep,
  no run step, state UNKNOWN. Regression tests in
  `tests/test_retry_prep.py` (14 tests).

- **SSH private keys pasted into forms no longer corrupt (ISS-021).**
  HTML form submission normalizes textarea newlines to CRLF, so a
  private key pasted into the ssh-target form was stored with `\r\n`
  line endings verbatim — the materialized key file then failed to
  parse in both OpenSSH and paramiko ("error in libcrypto") and every
  ssh-target execution failed authentication. `store_secret` now
  normalizes CRLF to LF for `ssh`-kind secrets (key material is
  LF-format by spec); other kinds are stored verbatim. Regression
  test in `test_infra.py` pins both behaviors. Surfaced on the Linux
  acceptance VM when the e2e-ui suite re-seeded the ssh target
  through the UI form — the failure chain (probe verdict → validation
  gate → dispatch refusal) correctly reported it as an ssh-target
  problem rather than fabricating success.

- **KRE credential delivery hardening.** Delivered credentials now
  land inside a prep-created restricted drop dir (`build/.to_cred`:
  0700 on POSIX, SYSTEM+Administrators DACL on Windows) instead of a
  window where the file was briefly world-readable; the POSIX writer
  applies its mode at `open()` time and SSH workdirs are chmod 700
  before staging. `credential_ref` correctly wins over the legacy
  `credential_file` when both are set, matching the documented
  precedence.
- **KRE credential-error acceptance defects.** Three defects found by
  the credential-error acceptance matrix on the remote POSIX PB
  transport: a KRE runtime with neither `credential_ref` nor
  `credential_file` launched KRE with no `-apiKey` and reported
  COMPLETED (now fails `config` before any transport work);
  `kre_cred_exec.sh` rejected the delivered `../.to_cred/cred` path
  form so every credentialed KRE run on a remote POSIX PB worker
  failed (now accepts absolute paths or the per-run `../<name>` form);
  and `kre_cred_exec:` errors were unconditionally classified `config`
  (credential value/content problems stay `config`; file, permission,
  and missing-executable problems now classify `infrastructure`).
- **Interrupted runs can no longer report PASSED from partial
  evidence.** `exit_status` was set on every reconciled run, so
  `_normalize`'s `completed` flag was always true and a killed run
  (exec_timeout, watchdog, worker loss) whose surviving junit was
  all-pass reported outcome PASSED — a false-pass surface for
  API/CI consumers (ISS-014). An interrupted run now asserts only
  observed failures: nonzero exit + all-pass/no-failure evidence →
  `incomplete` with an `execution.interrupted_partial` audit
  record; observed failures still classify `failed`. Clean exits
  are unaffected. Verified live on Windows PB (gtest
  `--gtest_repeat=-1` killed at watchdog) and Linux PB
  (exec_timeout).
- **SSH transport: license rejection no longer masked as `config`.**
  A failed KRE activation still prints KRE's argv-validation complaints
  ("Cannot find project"), which outranked the generic license fallback
  in `classify_error` — genuine license rejection over SSH surfaced as
  `config` ("ssh remote group terminated") instead of `license`.
  Activation-failure markers (incl. "Failed to activate with API key")
  now outrank config markers whenever activation never succeeded;
  successful runs that later hit a real config problem still classify
  `config`. Verified live on the SSH transport with real `katalonc`
  rejecting a synthetic key (`error_kind=license`, ex
  4da4bae36ad04e4c98f84615792a48bd).
- **Playwright native collector: file path for `--list` 1.4x+ schema.**
  `playwright test --list --reporter=json` moved the file path from
  `suite.location.file` to `suite.file` / `spec.file`; collected items
  came back with an empty `path`, producing unusable native inventory
  rows (ISS-015). The collector accepts all three locations; verified
  live against Playwright 1.65.1 on a Linux PB worker.
- **Cypress native collect no longer poisons discovery status.**
  Cypress has no native list command, so its collector is an
  intentional no-op — but `apply_native_inventory` treated the empty
  item list as a failed collection and set
  `fp.discovery_status = "failed"`, blocking every subsequent cypress
  execution through the `_fp_item_gate` (ISS-016). No-op collect runs
  (`"noop": true`) now leave inventory and discovery status untouched;
  the informational warning still surfaces on the run. Verified live.
- **Node native collectors spawn correctly on Windows workers.**
  The staged playwright/jest collectors invoked `npx` literally —
  on Windows that resolves to `npx.cmd`, which Node >=20.12 refuses
  to exec without `shell: true` (ENOENT then EINVAL), and the
  deps step is skipped for collect by design so npx bin resolution
  could fall back to PATH and hit an unrelated `playwright` binary
  (a Python `playwright.exe` presents a different CLI —
  `unknown command 'test'`) (ISS-017). Collectors now run the staged
  `node_modules` CLI deterministically via `node` — vendored POSIX
  `.bin` shims never execute on Windows — and fall back to
  `npx`/`npx.cmd` with `shell: true` on win32 only when no staged
  package exists. Verified live on a Windows PB worker: real
  `playwright test --list` produced test-granularity items.
- **GoogleTest native collection and exact parameterized selection.**
  Collect runs carried no framework settings (`fp.settings()` was
  only folded into `run_config` for item dispatches, never for
  `native_collect`), so `executables` resolved empty and the
  collector exec'd the `.` test-root as a binary — zero items,
  `discovery_status=failed` (ISS-018). The collect run now snapshots
  project settings like item dispatches do; the staged collector
  glob-expands `executables` patterns (`build/*`) against the
  checkout instead of exec'ing them literally. Parameterized
  instances collected `AddsUp/0  # GetParam() = 1` verbatim — the
  annotation is not filterable and never matched junit identity;
  node_ids are now the canonical name. Selecting a collected
  `<exe>||Suite.Test` item now sets `spec` + exact `--gtest_filter`
  (previously it ran the whole binary). Verified live on a Windows
  PB worker: collect surfaces `Arith/ParamAdd.AddsUp/0,1,2`,
  param-exact dispatch produced an isolated PASSED/FAILED result,
  full-binary run produced all three.
- **Busy runtimes no longer fail auto-picked executions.**
  `pick_runtime` excluded any runtime at its concurrency cap, so a
  queued execution on a single-capacity runtime failed "no enabled
  compatible runtime" instead of waiting for the slot. Auto-pick now
  prefers runtimes with free capacity but falls back to a busy one —
  the capacity claim holds the execution QUEUED.
- **Test harness credential-wrapper argv.** `bb_local_stub.py`
  dropped `spec.executable`/`spec.args` when rendering the
  credential wrapper — the stub ran `sh wrapper cred sh` instead of
  the real exe (latent; only surfaced once pipeline fixtures carried
  real credentials). Now mirrors the master.cfg argv construction.
- **Project-scope authorization on runtime picks.** An explicit
  `runtime_id` in a run request now enforces the runtime's
  `allowed_projects` (and the bound runner's) — the check previously
  applied only to auto-picked runtimes. KRE runtimes can also be
  associated to projects through the same route as other kinds.
- **Buildbot web UI theming.** The bundled Buildbot UI now uses the
  product palette via `www.theme` (`bb-sidebar-*` variables mapped to
  the app's `--sidebar-bg`/`--sidebar-fg`/accent values) instead of
  Buildbot's stock blue theme.
- **Project dashboard chart blowout.** The daily pass/fail bars on
  a project's Dashboard tab were sized `2 + count × 14` px with no
  normalization — a busy day produced ~1300px columns inside the
  90px chart. Bar segments now scale to the peak day's total and
  the chart box clips overflow.
- **Guided-wizard framework picker alignment.** Step 1 radios
  inherited the global `.field input { width: 100% }` rule,
  leaving each radio detached full-width above its label. The
  picker is now a grid of clickable tiles (radio + name +
  description per card) with an accent highlight on the selection.
- **Real-framework matrix defects** (found during Linux worker +
  SSH-only acceptance against real toolchains):
  - Discovery glob engine could not evaluate minimatch extglobs
    (`@(...)` `?(...)` `+(...)` `*(...)` `!(...)`) — playwright/jest
    `testMatch` defaults never matched spec files.
  - postman/bruno probe scripts emitted `newman=`/`bru=` markers the
    readiness summarizer never consumed — probe verdicts could not
    reach `ready` and dispatch stayed gated.
  - `Reports/`/`Reports/junit` not pre-created in the exec workdir —
    jest `--outputFile`, newman junit export and bru
    `--reporter-junit` failed ENOENT (POSIX exec wrapper, Windows
    prep, SSH run.sh all covered).
  - jest file-granularity items were not mapped to `spec` — a
    suite-file selection ran the whole jest suite.
  - `kre.classify_error` matched the bare word "license" — KRE logs a
    benign "Failed to activate with TestCloud license" fallback in
    every run, so unrelated failures misclassified as license.
  - jest's `Reports/jest.json` contract was collected but never
    parsed into TestResult rows — failing runs verdicted "no result
    data" and clean passes surfaced `incomplete`. `parse_jest` now
    feeds the canonical ingest (framework-gated, sha-deduped).
  - gtest driver passed `--gtest_fail_if_no_test_selected`
    unconditionally; gtest versions that don't know the flag (e.g.
    libgtest 1.14) print help and exit 0 having run nothing — a
    silent vacuous pass. The driver now probes `--gtest_help` per
    binary and fails when no result XML was produced.
- **Windows worker defects** (found during Windows 11 PB-worker
  acceptance against real toolchains):
  - Probe spec never set `posix` — Windows workers were sent POSIX
    `sh` probe scripts.
  - `probe.cmd` scripts (pytest/robot/node) used cmd constructs that
    abort or double-fire: `call :label` inside `if`/`for` parens,
    bare `npx`/`npm` (.cmd shims transfer control permanently),
    `A && (B) || (C)` emitting both branches, unescaped parens in
    marker text. Rewritten errorlevel-style with `.cmd` helper files.
  - `_cleanup_win_argv` exited 1 — suppressed `Remove-Item` errors
    still propagated through `$?` to `powershell -Command`.
  - `ELECTRON_RUN_AS_NODE=""` in the exec env map broke Cypress on
    Windows — an empty-valued variable is still present in the
    environment block and Electron honours it (`MODULE_NOT_FOUND`,
    empty requireStack). The key is omitted on Windows workers.
  - postman/bruno/gtest had `unsupported-on-windows` probe
    short-circuits despite Windows exec paths — replaced with real
    `probe.cmd` implementations.
  - Robot probe treated `python -m robot --version`'s exit 251
    (informational) as missing — now output-based like POSIX.
- **S3 artifact retrieval** after staging removal — objects now stream
  via `open()` to a bounded staging file with sha256 verification and
  deterministic cleanup (concurrency cap, size ceiling, ENOSPC
  handling, abandoned-temp sweep on startup).
- **Mounted-share blocking** — share I/O runs on a bounded executor
  (2 workers, 20 s cap): an NFS `hard`-mount outage returns a prompt
  `StoreError` instead of parking request threads; recovery is clean.
- **Buildbot KRE failure classification** — license/config/
  infrastructure kinds are now derived from the run log instead of
  the generic "no result data" verdict.
- **KRE on remote workers** (found during the remote-worker
  acceptance matrix — the exec argv previously embedded the
  controller-host path of `kre_cred_exec.py`, unreachable from any
  remote worker, and the script itself was POSIX-only):
  - The credential resolver is now staged **per execution** — inside
    the source archive as `src/.to_kre_cred_exec.py` on PB workers
    (run under the worker interpreter: `python` on Windows,
    `python3` on POSIX), SFTP'd into the remote workdir on SSH
    targets. `credential_wrapper` in the exec spec is the staged
    name; `helper_sha256` records the staged content for evidence.
  - `kre_cred_exec.py` is portable: Windows runs under a
    kill-on-close job object; POSIX launches the engine in its own
    process group and kills the pgid so `katalonc`'s java child
    cannot outlive the wrapper while holding a license.
  - Readiness probes validate the real remote path: KRE executable
    version, worker interpreter, and staged-helper executability
    (`helper_exec=ok`), not just executable presence.
  - Classification distinguishes the layers: helper failures
    (`kre_cred_exec:` → `config`, never a license verdict), genuine
    KRE activation rejections (`license`), post-activation KRE
    config complaints (`config` — outranking generic license words,
    which fixes a truncated-tail misclassification), step kill
    markers (`infrastructure`).
  - Agentless-SSH: terminal failure confirms remote process-group
    death (the detached run otherwise holds the license after a
    timeout); SSH failure classification reads the SFTP'd `run.out`
    artifact (SSH builds have no worker step stdout); a refused
    buildrequest cancel is surfaced and re-issued every tick until
    the buildrequest completes.
- **Offline packaged install** — the vendored wheel set now includes
  the pinned boto3 dependencies (boto3/botocore/jmespath/
  python-dateutil/s3transfer) so S3 support resolves without network.
- **Managed KRE credential delivery + target-native launchers**
  (replaces the interim `.py` helper and the operator-placed key
  file on remote targets):
  - `credential_ref` is now the supported path on every topology:
    an authorized user stores the KRE API key as a `runtime` secret
    (System → Secrets) and selects the reference on the runtime.
    Per execution, the portal stages a 0600 file and delivers it —
    Buildbot `FileDownload` (`.to_kre_cred` at the build root) on PB
    workers, SFTP `run.cred` into the run workdir on SSH targets.
    No operator-placed file, no manual copying, nothing inside the
    source archive or artifacts; every kill/cleanup path removes it.
  - The credential resolver is now `kre_cred_exec.sh` (POSIX,
    plain `sh` — no `python3` requirement) and
    `kre_cred_exec.ps1` (Windows `powershell -File`, kill-on-close
    Job Object — no `python` requirement). Both are staged per
    execution with a `helper_sha256` provenance record; the helper
    scrubs `-apiKey=` from KRE's own echoed argv before step
    capture, and the key never appears in helper argv.
  - POSIX kill semantics fixed: KRE runs in the launcher's process
    group so Buildbot's step `killpg` and the SSH group kill both
    reach it (a `setsid`'ed engine escaped both and could orphan a
    licensed run); a pid-directed signal now kills the whole child
    tree so `katalonc`'s java grandchild cannot survive holding the
    license.
  - Credential failure kinds are distinct: unknown reference and
    wrong-kind secret → `config`; undecryptable material →
    `infrastructure`; only a genuine KRE rejection → `license`.
  - The legacy `credential_file` (operator-placed 0600 file on the
    target) remains supported for compatibility — it is no longer
    required or default.
  - UI: the manual runtime form gained per-field platform examples
    and a credential-reference selector; connection-requirements
    help no longer overflows. Infrastructure buttons are now "Add
    Runtime (Guided)" (the framework wizard — KRE included) and
    "Add Runtime (Manual)". The guided wizard offers a Katalon
    profile: executable path plus a `secret`-kind field rendered
    as a select of `runtime`-kind secrets, mapping onto the KRE
    runtime columns (`executable_path`, `credential_ref`,
    `credential_file`, `concurrency`).
- **Quality-gate pass** (dead-code, duplication, security,
  memory-leak, and SonarLint sweeps):
  - "Run now" on a plan-type schedule always raised "scheduled
    plan no longer exists" — `plan` was hardcoded `None` (ISS-019);
    it now loads via `db.session.get` like the cron path
    (`dispatch.fire_due_schedules`), with a regression test
    (`test_run_now_plan_target_dispatches`).
  - Concurrency validation in the KRE runtime wizard used `assert`
    inside `try`/`except` — silently skipped under `python -O`;
    replaced with an explicit `ValueError` check; `0`/negative
    submissions covered by test.
  - Removed dead code surfaced by vulture + SonarLint:
    unreferenced `after_this_request` import,
    `behavefw.collect_args`, `gtestfw.list_args`,
    `gherkin.scenario_node_id`, and unused locals
    (`npx_forced`, `known`, `binding` + tuple-unpack renames).
  - Bandit audit: 1 High flagged on `updater.py` tarfile is a
    false positive (`tarfile.data_filter` is applied); all 16
    Mediums audited clean (argv-list subprocesses, shlex-quoted
    paramiko, no DTD XML path, intentional dual-stack binds).
  - Duplication (jscpd): 0.39% — three clones, all per-adapter
    probe-script boilerplate kept deliberately isolated.
  - Memory: 300-cycle execution + junit-ingest loop showed flat
    RSS (~93→96 MB plateau), stable object counts and constant
    fd count — no leaks.

Engine acceptance (all verified live — dev stack + installed
package): Playwright 1.65.1 and Cypress 16.3.0/Electron 43 real
runs on Linux PB, Windows PB and the final installed payload —
collect, pass/fail, exec-timeout kill, cancel, junit + native
artifacts on every topology. GoogleTest verified end-to-end —
native collection, parameterized-instance identity and exact
`--gtest_filter` selection, spaces/Unicode paths, timeout/kill,
cancel, junit retrieval, worker-service termination + recovery —
on Windows PB and on the installed package (worker-compiled
MinGW/g++ binary). ISS-015/016/017/018 were found and fixed during
this acceptance; no engine-coverage residuals remain.

### Dependencies

- Added runtime deps (pinned): `boto3==1.44.10`, `botocore`,
  `jmespath`, `python-dateutil`, `s3transfer`, `six` — vendored in
  `3rdparty/python-wheels/` with license texts + notices.

### Known limitations (2.7.0)

- **Windows worker installer is unsigned** (owner decision — no signing
  step, no certificate, output name unchanged). Windows SmartScreen
  will show a warning on first run ("Windows protected your PC").
  To install anyway: click **More info** then **Run anyway** — the
  publisher shows as "Unknown" because the binary is unsigned.
  Before running, verify the download with `Get-FileHash` in
  PowerShell against the SHA-256 published for the exact worker
  installer artifact. **Code signing is a future item, owner-blocked,
  with no work planned for 2.7.0.**
- **Timeout classification** (owner decision): timeout-killed
  executions classify failure-kind `execution` with outcome
  INCOMPLETE — never PASSED. A distinct `timeout` classification is
  a 2.8 candidate, not 2.7.0 scope.
- **Secret-scope enforcement for Git-kind secrets is a documented
  limitation for 2.7.0** (owner decision — enforcement moves to 2.8):
  grants are enforced for KRE credential delivery only; Git-binding,
  SSH and Buildbot secret consumers stay outside the grant model.
  Reason: enforcement for Git bindings needs a migration that derives
  grants for existing bindings, or every Git sync breaks at upgrade.
  The exposed-secret pre-flight guard stays in force for ALL kinds —
  a secret flagged exposed is refused at dispatch regardless of type.

- S3 adapter verified against SeaweedFS (S3 stand-in, not GCS or
  AWS-provider acceptance); Azure verified against Azurite 3.34.0
  emulator over loopback+SSH tunnel, not live Azure. Insecure
  endpoints are a test-only flag.
- One production-issuer-key test remains blocked
  (`test_production_key_auto_loaded` — declared skip; documented
  boundary in `docs/licensing.md`). `test_payload_fields_signed`
  now runs against an isolated test issuer in the suite — no
  production-key dependence, and the test-only trust path cannot
  enter production configuration.
- Licensed two-session KRE overlap is unverified: scheduling,
  isolation, cancellation and recovery were proven with synthetic
  launchers on both topologies, but real concurrent KRE runs wait on
  the rotated API key and confirmed license entitlement — synthetic
  overlap must not be read as licensed KRE concurrency.
- Packaged-acceptance topology collapsed server+worker into one
  disposable VM — not independent-host partition evidence.
- Secret authorization is implemented and verified at the
  application level (default-deny grants: project/runner/runtime
  dimensions, claim-time revocation, denial before decryption or
  delivery, pending-association recording, audited admin edits —
  `tests/test_secret_scope_acceptance.py`, upgrade migration
  `n2b3c4d5e6f7` backfills grants from existing associations and
  flags `migration_pending` for admin review). Two owner-accepted
  residuals: the `-apiKey=` argv exposure boundary (same-account
  visibility, documented disposable-target exception) and live
  Katalon key rotation pending on the owner's replacement key.


## [2.6.0] — 2026-11-24

Feature release — Playwright Test, headless Cypress E2E, Robot
Framework and pytest as first-class runners on the existing
Buildbot/SSH execution paths.
Schema changes: `runtime_connections.runtime_kind`
(`kre`|`playwright`|`cypress`|`robot`|`pytest`, default `kre` —
existing connections upgrade unchanged) and `users.timezone` (IANA
name, default `UTC` — existing users keep identical display).

### Added

- **Settings backup & restore** (System → Backup & restore):
  Administrator-only, re-authenticated, fully audited encrypted
  `.tobackup` archives (AES-256-GCM + scrypt passphrase KDF; the
  secret-store key travels inside the encrypted payload). Settings-only
  scope — execution history/evidence stay with the instance. Staged
  restore (upload → validate → preview → confirm → apply → verify) with
  fresh-install one-time local setup token, replace mode with automatic
  pre-restore safety backup, atomic rollback, maintenance-mode gating,
  session/API-token revocation, and needs-verification marking for
  environment-dependent targets. See `docs/backup-restore.md`.

- **Robot Framework runner.** Register a runtime with kind `robot`
  and configure the target's Python interpreter explicitly
  (`executable_path` — venv `bin/python`/`Scripts\python.exe`
  works; pure argv, no shell/PATH/activation dependency). Runs
  invoke `python -m robot` with isolated `Reports/` output —
  `--xunit junit.xml` feeds the shared JUnit normalizer while
  native `output.xml`, `log.html`, `report.html`, console logs and
  project evidence upload as artifacts on pass *and* fail.
  Project-relative suite file/directory, `--test`/`--suite` and
  `--include`/`--exclude` tag selection are supported from the run
  form; Robot's exit codes (1–249 failed-test count, 250–252
  usage/data/config, 253 interrupted, 255 internal) classify
  explicitly so invalid invocations never read as test results.
  No browser selector applies — browsers belong to the Robot
  project's libraries. Suite-level parallelism uses
  Pabot (`--processes=N`) when the optional dependency probed
  `opt_pabot=ok` on the target — without it parallel dispatch is
  refused, never silently sequential. Out of scope for 2.6.0:
  custom listeners, keyword-level portal browsing.

- **pytest runner.** Register a runtime with kind `pytest` and
  configure the target's Python interpreter explicitly — the same
  `executable_path` contract as `robot` (venv `bin/python`/
  `Scripts\python.exe`, pure argv, no shell/PATH dependency). Runs
  invoke `python -m pytest --junitxml Reports/junit.xml -q` inside
  the staged project; the JUnit report feeds the shared normalizer
  and console logs plus project evidence upload as artifacts on
  pass *and* fail. The run form's pytest options map to `-k`
  (keyword expression) and `-m` (marker expression); parallel mode
  adds `-n=N` via `pytest-xdist` when the optional dependency probed
  ok on the target.

- **Node.js browser runners.** Register a runtime with kind
  `playwright` or `cypress` on any Buildbot worker (Windows/Linux)
  or agentless Linux SSH target. Runs stage the project under
  `build/src` and invoke `npx playwright test --reporter=junit` /
  `npx cypress run` (reporter `junit`, `toConsoleStandard:true`,
  per-spec `junit-[hash].xml` names so later specs cannot overwrite
  earlier reports). JUnit, logs, traces, screenshots and videos land
  in the standard Reports/ upload → existing `parse_junit`
  normalization and artifact retention — same run IDs, same
  pipeline.
- **Check runner readiness** action on the Infrastructure page —
  runs a probe build on the *same target, account and transport*
  the real run uses (remote worker via its own builder; agentless
  SSH via the dispatcher over SSH/SFTP). Reports connectivity,
  Node.js/framework/browser versions, and browser reachability of a
  configured application URL. Installs nothing, runs no tests,
  echoes no secrets; results persist on the runtime record.
- **Browser selection** for node runtimes — validated against the
  framework's supported set (`chromium`/`firefox`/`webkit`;
  `chrome`/`firefox`/`edge`/`electron`/`chromium`), invalid values
  rejected, never silently substituted.
- **SSH run spec** gains `exec_subdir` and `env` — the generated
  remote `run.sh` cd's to the staged project root and exports
  framework env (e.g. `PLAYWRIGHT_JUNIT_OUTPUT_FILE`) before exec.
- **UI guidance**: runtime-kind selector, per-target connection-
  requirements table, and prerequisites text on the run forms and
  Infrastructure page.

- **Concurrency & queueing.** True concurrent independent runs with
  framework-specific parallelism, durable parent/child aggregation,
  resource-aware admission (job slots + process budgets via CAS
  reservations), explicit concurrency controls and capacity
  enforcement, fair queueing with actionable wait reasons, queue
  deadlines, UNKNOWN-capacity holds, and schedule overlap /
  missed-fire (`allow`|`skip`, `late`|`skip`) policies.
- **CI API & webhooks** — token-authenticated REST endpoints to
  trigger, poll, cancel, and retry runs, plus outbound webhook
  notifications on execution completion. Bearer tokens are stored
  as SHA-256 only (shown once at creation), scope/project-limited,
  revocable; idempotent via `client_ref`.
- **Operational log export** — admin-exportable CSV/JSON of the
  operational log with redaction of secrets in both formats,
  size-bounded background jobs, `.part`-file cleanup across
  restarts, and an export download page.
- **Reconciliation UI** — Admin view of orphaned/ambiguous runs
  (UNKNOWN / cancel-requested / expired-lease executions holding
  reservations) with manual resolve actions, reservation chips,
  state/warning badges, and explicit orphaned-evidence pruning
  under `imported-evidence`, `workspaces` and `remote-runs`.
- **History matrices** — durable per-suite/plan/target result
  matrices for at-a-glance failure-pattern review.
- **Artifact manifests & lifecycle** — per-run manifests with
  retention enforcement.
- **Project membership enforcement** — explicit project
  assignment for non-admin roles across UI, audit, token, and
  dispatch paths; administrators reach all projects via the role.

- **Advanced analytics (Group A)** — new on-demand section under
  each dashboard's existing content, using the vendored Plotly.js
  and the shared semantic palette (counting policy:
  `docs/analytics-counting.md`). Existing charts, metric strips
  and tables are unchanged.
- **Main Dashboard:**
  - *Project outcome comparison* — horizontal stacked bars of
    terminal **logical runs** per project by final resolved
    outcome (counts/% toggle; click-through to filtered
    executions).
  - *First-attempt vs final pass rate* — paired run-level lines
    over the same cohort (hover shows numerator/denominator and
    retry count).
  - *Queue wait & turnaround* — median + p95 per enqueue day for
    dispatchable attempts; turnaround is honestly labelled
    enqueue→finished (no dedicated results-ready timestamp exists
    — the instrumentation gap is documented).
- **Project Dashboard** (follows the page's existing filters):
  - *Test-result history* — case × attempt heatmap; color AND a
    P/F/E/S letter per cell (never color alone), empty cells for
    "case not in run", click-through to the run's evidence.
  - *Suite-duration distribution* — box plots of logical-run
    duration per suite (unit shards count inside their parent).
  - *Environment comparison* — suite × environment heatmap with
    selectable metric (case pass rate / run pass rate / median
    duration), sequential blue scale, "(unset)" column, cell
    drill-through.
- **Infrastructure:** `analytics.py` aggregation
  (membership-scoped, bounded, disclosed truncation),
  `/dashboard/analytics` and `/projects/<id>/analytics` JSON +
  CSV endpoints, manual Refresh (never the 5 s live poll —
  zoom/legend preserved via `uirevision`), collapsible data
  tables under every chart, and Executions-list
  `suite_id`/`environment` filters for drill-through.
- **Advanced analytics (Group B)** — four further charts beneath
  the same dashboards, same logical-run counting policy
  (`docs/analytics-counting.md`):
  - *Execution activity* (Main Dashboard) — day-of-week × hour
    (UTC) heatmap counting each logical run once; submitted vs
    started selector (started = first actual execution start,
    never-started runs excluded); cell drill-through opens the
    exact bounded executions cohort.
  - *First-attempt vs final pass rate* (Project Dashboard) —
    Group A's aggregation reused under the project filters; hover
    shows numerator/denominator/retries/excluded. No drill-through
    (accepted limitation, stated inline).
  - *Suite-duration regression* (Project Dashboard) — median
    logical-run wall-clock duration vs the previous equal-length
    period under the same filters; seconds/% views, sample counts,
    N/A for missing or zero baselines, insufficient-sample (n<3)
    flagging, contributing-execution links for both periods.
  - *Evidence freshness* (Project Dashboard) — suite ×
    environment age since the latest usable result (a complete
    failing result is still evidence); fresh/stale/never states on
    a documented 7-day threshold, all-history lookup disclosed
    with a beyond-window marker, "never" only where suite and
    environment are both known to exist, exact execution link.
- **Project page tabs** — Access and the analytics dashboard are
  now in-place tabs: Access renders inside the project page
  (admin-only, unchanged `@role_required` enforcement; the
  standalone `/projects/<id>/access` URL still works), and the
  analytics dashboard opens as the Analytics tab (lazy — the
  aggregation only runs when the tab is requested; the standalone
  `/projects/<id>/dashboard` URL still works and now uses the
  wide layout).
- **Per-user display time zones** — each user picks an IANA time
  zone (e.g. `Europe/Budapest`) via a grouped `<select>` of ~140
  curated major-city zones organized by region (UTC / Europe /
  Africa / Americas / Asia / Atlantic / Oceania & Pacific, with a
  current-offset label that notes it varies with the date) — the
  same style as OS pickers — on Create User, inline on the Users
  list (click Edit on a row's zone to swap text for the dropdown +
  Save), and the **My Account** self-service page; any valid IANA
  identifier beyond the curated list is still accepted
  server-side, and a saved off-list zone is kept selectable under
  a "Saved" group. Existing users migrate to UTC unchanged; a
  browser-detected zone is only a suggestion, never an override.
  Stored instants stay UTC —
  dashboards, execution lists/details, attempt history, audit
  trail, operational logs, schedule/upcoming displays, releases,
  admin pages, log-export jobs and app-generated report summaries
  render in the viewer's zone with a numeric offset (repeated
  DST local times stay distinguishable; machine-facing output
  never gets a `Z`). Analytics — including Group A/B charts —
  bucket by the viewer's local calendar day, weekday and hour,
  and date filters convert local-midnight boundaries to UTC;
  CSV exports keep named UTC columns and add localized columns
  with the zone identified. Schedules still fire at their stored
  UTC instant — the form states the execution zone vs the
  display zone. Settings backup round-trips the preference;
  older backups default to UTC and invalid identifiers warn and
  fall back safely. `tzdata` is pinned so packaged Windows and
  Linux installs carry the IANA database for `zoneinfo`.

### Changed

- **System pages modernized** to a shared design language — wide
  layout, cards, accent headings and table headers, status/kind
  badges, consistent primary/secondary/danger buttons, collapsible
  add/create sections, responsive grids, accessible controls:
  Settings hub (incl. the Advanced/diagnostics card), Reporting,
  Network & certificates (toggle switch, selectable detected-
  address rows, port grid), Credentials, Health & services,
  Changelog, and Licence. Infrastructure, Reconciliation and
  Backup & restore pages share the same wide layout and styling.
- **Settings hub icons** — each Settings card now carries an
  inline SVG icon (shield, server, key, report, users, heartbeat,
  wrench), left-aligned and vertically centered beside the text.
- **Execution detail page modernized** — every section (Details,
  unit runs, Results, Report, reporting-labs, Logs, Evidence,
  Snapshot, Report publication) is now a card; state, outcome,
  error, report-status and artifact-kind values render as badges;
  action buttons use the shared primary/secondary/danger styles;
  the dispatch snapshot collapsed behind a details disclosure.
  Also fixes a markup bug where the Report publication card was
  duplicated inside the document `<title>`.
- **Secondary action buttons** now use the IT-Space brand yellow
  (`#f1cf6e`, navy text) so they are clearly visible on white
  cards — applied globally (execution detail, Users, Reconciliation,
  and all other secondary actions).
- **Users page reworked** — wide layout with a carded table
  (accent-tinted header, role/status/membership badges,
  right-aligned actions); **Create user** collapses behind a
  button with project assignment at creation time; **Reset
  password** opens a full-width expandable panel under the row
  instead of a popover; red **Delete** action with self-delete and
  last-admin guards (`user.deleted` audited).
- **Operational Logs** — Live Tail moved out of the filter-button
  row into a dedicated toolbar (pill switch + status left, row
  count right) so polling no longer shifts Apply/Reset/export
  buttons. Operational Logs, Audit Trail, Log Export and Changelog
  are all wide-layout.
- **Changelog rendering fixed** — the markdown renderer now joins
  paragraphs and list continuations correctly (previously every
  soft-wrapped line became its own paragraph and `&amp;` entities
  double-escaped), renders one level of nested sub-lists (indented
  bullets used to flatten into the top level), and honours
  `*emphasis*`.
- **IT-Space branding** — full-page tiled logo mosaic on the login
  page (seamless mirrored tiles, dark-mode aware); Changelog,
  Licence and Backup & restore headings render over the page-wide
  IT-SPACE logo hero; Licence gained a branded vendor-credit
  footer (IT-Space Ltd, info@it-space.info, it-space.info).
- **Licence page in the sidebar** — Admin → Licence (directly
  under Changelog) with the modern add-licence card; previously
  reachable only by URL.
- **`reportinglabs_enabled` now defaults to on** — HTML reports
  are generated unless explicitly disabled on the Reporting page
  (now a modern toggle switch).
- **Menu order**: …Audit → Operational Logs → Backup & restore →
  Third-party notices & licences → Changelog → Licence.

### Fixed

- **Executions list Worker filter never populated** — the
  template iterated `workers` while the route passed `runners`,
  so the dropdown was always empty.
- **Project Access tab out of design** — the link rendered as a
  plain hyperlink next to the styled tab labels and navigated
  away; it is now a real in-place tab like the others
  (see "Project page tabs" above).
- **Reconciliation page crash on SQLite** — stored datetimes read
  back timezone-naive while the page compared them against an
  aware `utcnow()`, so any real UNKNOWN / expired-lease row raised
  `TypeError`. The route now normalizes stored values to UTC and
  binds a naive UTC `now` matching the stored format.
- **Dashboard "Open" project link out of design** — the five-second
  live poll rebuilt project rows with a bare hyperlink, undoing the
  styled button the template rendered. The poll now emits the same
  `secondary sm` button.
- **Release timeline names truncated** — names were ellipsized at a
  fixed 10 rem; they now wrap so the full name (e.g.
  "R2026.11 — Documentation Demo") is readable.
- **Dashboard projects table** — the actions column had an empty
  header (now labelled Actions), action cells used a bare
  `display:flex` td that drew a phantom line across the row (now a
  `cell-actions` div like the other tables), and rows vertically
  center like the rest of the app's tables.
- **Timestamps readable** — dashboard and analytics pages no
  longer show raw ISO `T`/`Z` markers; times render as
  `YYYY-MM-DD HH:MM:SS` with an explicit UTC label where needed.
- **Unclosed "Recent executions" section** on the project
  analytics page — the section element was never closed (masked
  by the outer card wrapper); closing it also fixed dashboard
  content leaking onto sibling tabs once embedded as a tab.
- **Content-Security-Policy blocked all inline JavaScript** —
  `script-src 'self'` (no `unsafe-inline`) made every inline
  `<script>` block and `on*=` handler dead: the Agentless-SSH field
  reveal on the Add-target form (SSH targets could not be
  configured through the UI), the select-all/clear buttons on the
  project-access and user-access pickers, the project-row filter,
  the timezone "Use detected" suggestion, the "View all releases"
  link, and all nine `confirm()` gates on destructive forms
  (delete user/credential/target/execution, restore, restart,
  bulk cancel, prune, run-now) silently never fired. All inline
  code is externalized into `static/js/ui-inline.js` (delegated
  `data-confirm` submit/click handling, `data-check-group`
  select-all, the SSH-fields toggle, timezone detection); a
  regression test now fails if any template reintroduces inline
  scripts or handlers.
- **Retry-blocked runs misclassified as UNKNOWN-able echo** —
  `_retry_blocked_line` matched the literal `TO_RETRY_BLOCKED`
  marker *inside* the prep step's script command echo (the script
  text contains `echo "TO_RETRY_BLOCKED …"` lines), so any
  remote-run failure that produced no JUnit landed UNKNOWN instead
  of FAILED. The marker must now start an output line after the
  Buildbot channel prefix is stripped — the echoed script source
  can never match; a regression test covers the echo case.
- **Executions list row clicks blocked by a delegated confirm** —
  the bulk-cancel form's `data-confirm` wraps the executions table;
  the delegated click handler intercepted link clicks inside it,
  fired a confirm, and blocked row navigation. Click-confirms now
  apply only to `data-confirm` on buttons/links — form containers
  use submit-time confirmation.

### Notes

- Node.js, the project's Playwright/Cypress dependencies, and the
  browsers are **pre-provisioned on the target** — nothing is
  bundled into the controller packages or the worker installer.
- Unsupported browsers are rejected up front; a missing JUnit report
  can never surface as a green run with zero tests (existing
  `REPORTS-MISSING` sentinel unchanged).
- In scope for 2.6.0: Playwright Test (Node.js), headless Cypress
  E2E and standard Robot Framework only — Playwright-Python,
  Cypress component testing, remote-browser grids, Cypress Cloud
  and Robot custom listeners are out of scope (Robot suite-level
  parallelism via Pabot IS in scope, gated on the optional
  dependency probing `opt_pabot=ok` on the target).

## [2.5.1] — 2026-11-19

Patch release — install fixes only; no schema or API changes.
Upgrades preserve all state (payload replaced, data/env/credentials
untouched, same reruns-are-safe contract).

### Fixed

- **Windows worker installer** failed on hosts without an existing
  pip: `get-pip.py --no-index --find-links wheels` reported *"No
  matching distribution found for pip"*. A pinned `pip` wheel is now
  bundled into the worker payload's `wheels/` — same fix applied to
  the Linux worker bundle's `bb-wheels/` for parity.
- **Windows controller installer** now offers a default-checked
  *"Open TestOrchestrator in your browser"* option on the finish
  page, opening `https://<addr>:<port>/` in the default browser
  (skipped automatically for silent `/S` installs).
- **Windows worker did not start after install**: the Scheduled
  Task command line was mangled twice — wrong argument order
  (`--nodaemon start`) and embedded `/TR` quotes broken by the
  NSIS→`cmd /c`→`schtasks` chain. Task registration now happens
  inside `setup-worker.py` via `subprocess` argument lists (no
  shell quoting) as `buildbot-worker.exe start --nodaemon`, and the
  task is started immediately after registration.
- **Windows worker tray icon**: a Startup-folder shortcut launches
  `worker-tray.py` (pystray + Pillow bundled offline) at user logon —
  notification-area icon showing worker state with right-click
  **Start / Stop / Quit** (controls the Scheduled Task via schtasks;
  Quit only closes the icon, never the worker). The menu also has
  **Configure…** — re-prompts endpoint/workername/password (blank
  keeps current), recreates `buildbot.tac`, restarts the task; a
  Start Menu shortcut + `start-tray.cmd` relaunch the icon after
  Quit. Uninstall kills only
  the tray process (targeted `stop-tray.cmd` — never a blanket
  `taskkill` on `pythonw.exe`). The icon now shows a small status
  dot at the bottom-right corner — green when the worker's
  Scheduled Task is running (process alive), red when it is not,
  and red with a "status check failed" note when the status query
  itself fails. Tooltip and the top menu line state "Running" /
  "Not running" as text (colour is never the only cue); the
  indicator refreshes every two seconds while the tray is open.
- **Windows controller firewall**: SYSTEM Scheduled Tasks never
  trigger the interactive "allow access" prompt, so inbound
  connections were silently dropped — remote workers could never
  reach PB `:9989` and stayed at `Awaiting registration`. The
  installer now adds inbound rules for the portal ports and
  `:9989`, removed on uninstall.
- **Controller desktop shortcut** added on install — opens the
  portal login page (`https://<addr>:<port>/`) in the default
  browser; removed on uninstall.
- **Infrastructure UI**: worker-row actions no longer overflow the
  table — secondary actions (Issue password, Drain/Resume,
  Enable/Disable, Remove) moved under a compact **Manage ▾** menu;
  the Workers card now documents the Buildbot PB endpoint
  (`<host>:9989`, not the https URL) beside the download table.

### Documentation

- All screenshots recaptured from the released codebase; step-by-step
  install walkthrough added to the Admin Manual (§4.2, one
  screenshot per step); architecture/dataflow diagrams re-rendered;
  Administrator and User Manuals also ship as PDF release assets.
- New Admin Manual **§6.9 KRE licensing** — who does what
  (Katalon licenses/activates KRE; TestOrchestrator only stores the
  API key as an encrypted credential reference, passes it as
  `-apiKey=` with log/artifact redaction, and caps concurrent KRE
  sessions per runner at `min(max_slots, license_slots)`), offline
  licences, the admin checklist, and an activation-failure
  troubleshooting order linked from §10.

## [2.5.0] — 2026-11-19

Initial public release.

### Portal and frontend

- Flask/Jinja2 portal served over HTTPS by **Cheroot, in-process** —
  no separate web-tier binary or unit. Waitress remains internal
  loopback only.
- **Admin → Network & certificates** manages TLS material, HTTPS
  listener, and the optional HTTP→HTTPS redirect listener.
  Certificate changes apply live; listener changes are staged
  through a last-good snapshot with automatic rollback.
- Session security: Argon2 password hashing, CSRF protection,
  `Secure`/`HttpOnly` cookies, forced bootstrap password change,
  role-based access (admin/operator/viewer).

### Orchestration — Buildbot 4.3.0

- **Buildbot master** on loopback REST (`:8010`) + PB (`:9989`),
  provisioned and managed by the installer and the portal —
  credentials are generated, stored encrypted, and preserved across
  reruns.
- Controller-side workers: `to-local` (local execution) and
  `to-ssh-dispatcher` (agentless SSH).
- Three execution modes, all managed from **Admin → Workers &
  runtimes**:
  1. **Local worker** — runs on the controller host.
  2. **Remote Buildbot worker** — bundled offline installer
     (Windows `.exe` / Linux script), outbound PB with per-worker
     credentials issued and rotatable through the Admin UI.
  3. **Agentless SSH** — `sshd` + the test runtime on the host;
     controller-side dispatcher launches and monitors over SSH/SFTP
     with Admin-UI host-key approval. No agent install.
- Dispatch integrity: assignment commits before the buildrequest
  exists, explicit runner/runtime picks are honored or visibly
  rejected, cancel propagates to remote process groups with
  confirmed or honestly-flagged termination, and recovery after
  disconnect resumes in-flight work without duplicates.
- Execution history is durable and never deleted by upgrades;
  cancellation intent is preserved across reconciliation.

### Evidence and reporting

- Per-execution evidence collection (logs, JUnit, artifacts) with
  configurable retention and `toctl evidence-prune`.
- Vendored **reportingLabs** report generation served with
  generation-scoped CSP sandboxing; idempotent regeneration.
- Optional git-based evidence export.
- Audit trail for administrative actions, independent of
  operational logs.

### Application licence

- The application licence is **informational only** — it never
  gates any feature. Without a valid licence the login page shows
  an informational notice and nothing else changes.

### Packaging

- Linux x86_64: tarball + self-extracting `.run`, `install.sh`
  (`toctl install`) with offline payload, install-time migrations,
  systemd unit staging, idempotent reruns that preserve data,
  credentials, and secrets.
- Windows amd64 controller: unsigned `.exe`
  (`build-scripts/build_windows.py` →
  `packaging/windows/app-installer.nsi`) — embedded Python,
  `buildbot-py` runtime (master + `to-local` + `to-ssh-dispatcher`),
  five Scheduled Tasks, persistent `%ProgramData%\TestOrchestrator`
  state, per-install CA trusted via `certutil`, data retained on
  uninstall unless `/PURGEDATA=1`.
- Windows amd64 Buildbot worker: unsigned offline `.exe` served
  from the installed portal next to its matching
  corresponding-source archive.
- Linux x86_64 Buildbot worker: `install_linux_worker.sh` + offline
  wheel closure (py3.10–3.12) + `get-pip.py` fallback in one
  downloadable bundle — the worker host needs no network.
- GPL third-party components ship as separate processes with
  licence texts, notices, and a written corresponding-source offer
  fulfilled by IT-Space Kft. (see `3rdparty/CORRESPONDING-SOURCES.txt`
  and `docs/redistribution-review.md`).

### npm ci prepare step (owner-approved semantics)

- `deps_prepare` (npm ci) defaults ON — existing node-framework
  projects keep the visible prepare step; `deps_prepare=false` in the
  run config turns it off explicitly. Lockfile required: dispatch
  refuses early when the bound root lacks `package-lock.json` /
  `npm-shrinkwrap.json`. **Security note: `npm ci` runs dependency
  install scripts on the target** — enabling it is a test-manager-and-
  above decision, audited with the lockfile hash. Timeout and output
  caps apply as for other steps. Never runs during discovery or
  preview (native collection path — pinned by test).
- The Jest probe is prepare-aware: a missing framework with npm
  present is not fatal, since the probe runs before any install.

### Native collection corrections (matrix batch findings)

- Frameworks without a collector (postman, bruno — static discovery is
  authoritative for their JSON/text structure) now get a clear early
  refusal from native collection instead of a pre-artifact failed
  execution that marked the framework project 'failed' and blocked all
  later runs (ISS-016 pattern). Run binding discovery instead.
- deps_prepare now also runs for native collection of node frameworks:
  collection is the approved repo-code execution path (UI ack), and
  jest --listTests genuinely requires project deps. Same lockfile
  requirement, lockfile-hash audit, timeout and output caps. Static
  discovery/preview remains parse-only and never executes anything.

### 2.8.0 backlog

Moved to `docs/Backlog-2.8.0.md` — owner-approved deferrals including
the unified-model items and the external-authentication epic.
