# TestOrchestrator 2.6.0 — acceptance evidence ledger

**Branch**: `feature/2.6.0-node-runners` (PR #4 — draft).
**Current head at recording**: `f96fcc1` — logging hardening +
cancellation-isolation fixes (application code) + ledger.
**Application revision tested by Run F**: `f96fcc1`.
**Application revision tested by Run E**: `d6c14b3`.
**Earlier tested candidate**: `57445bc` (full-suite Run C below).
Historical: all commits between `57445bc` and `34c2cca`…`adf4490` were
documentation-only, so Run C remained the tested state until
`d6c14b3`. **`d6c14b3` changed application code** — Run E below is its
full-suite evidence; the packaged-candidate suite stays a required row
in `docs/packaged-acceptance.md` §6.

**Stage 5 status: parallel + recovery scenarios exercised; PB-loss
retry/orphan correctness implemented and re-verified (`b049fab`,
pushed).** The earlier "same brid re-ran → PASSED" row proved only a
final outcome. The mechanism is now: per-attempt pidfile +
`TO_EXEC_ID` env marker (kills are env-verified), retry-prep orphan
resolution, per-attempt `attempt-<buildno>` artifact dirs, portal-side
`bb_attempts` snapshot tracking + `buildbot_retry_attempt` audit.
Re-verified live on both transports — see "Worker PB loss" below.
The original 11:12 run remains marked as the pre-fix evidence it is.

**Explicit policy chosen (per transport):**
- **SSH/agentless** → policy 1, reattach without relaunch: the remote
  `setsid` run (run.pid/pgid) persists across dispatcher death; the
  reconnecting dispatcher RESUMES it — true single-launch, verified
  (remote 3791749 resumed, new dispatcher 3791835).
- **PB workers** → policy 2, confirm-then-configured-retry: the retry
  `prep` step resolves the recorded pid — env-marker-verified kill if
  alive, "already exited" if not — before re-staging; the interrupted
  attempt is recorded (RETRY, own artifact dir, audit) and Buildbot's
  unconditional resubmit becomes the explicitly-permitted retry,
  each attempt a distinct identity+outcome.

**Retry boundaries (hardened, live-verified `a74884f2`):**
- *Confirmed termination, not just signal sent*: prep polls
  `/proc/<pid>` after TERM (3 s) then -9 (5 s); only when procfs is
  gone does the build proceed — "terminated orphaned prior attempt
  pid N (confirmed dead)". An unkillable/D-state process yields
  `TO_RETRY_BLOCKED` and the launch never happens.
- *Marker mismatch or uninspectable blocks relaunch*: a live pid
  without the execution's `TO_EXEC_ID` — including an environ that
  cannot be read — exits 70 with `TO_RETRY_BLOCKED`; the reconciler
  maps that marker to **UNKNOWN** (reservations retained, row lands
  on the reconciliation queue, `execution.retry_blocked` audited).
  The pidfile is kept as investigation evidence.
- *Retry enablement and limits are explicit*: `retry_enabled`
  (default true) and `max_attempts` (default 3, counting the
  original launch) come from `run_config`, rendered into every exec
  spec, enforced by a per-execution `.to_exec_attempt_<id>` counter
  in the builddir — attribution alone is not the policy, the counter
  is. Live: `a74884f2` retry printed `attempt 2 of max_attempts=3`,
  resolved pidfile 70011, relaunched as distinct pid 70177, PASSED;
  `bb_attempts` = [build 128 RETRY, build 129 SUCCESS].
- *Side-effect warning*: stopping an interrupted attempt cannot undo
  test actions already performed — a retry may repeat external side
  effects. Documented in Admin-Manual §18.1 with the
  `retry_enabled=false` escape hatch for non-idempotent suites.
- Regression coverage: `tests/test_retry_prep.py` (7 — real-process
  kill-confirm, foreign-pid block, cap, disabled-retry, per-exec
  counters, dead-pidfile), `test_retry_blocked_maps_unknown_and_
  holds_reservations`, `test_retry_policy_rendered_into_specs`.

**Retry policy surfacing (post-freeze fix `69e842d`):**
`retry_enabled`/`max_attempts` were rendered into specs but never
persisted into the immutable run_config snapshot — real submissions
silently defaulted to enabled/3. Fixed: snapshot stores both
(`dispatch.py` run_config), both run forms expose them with the
non-idempotent warning inline, execution detail shows the effective
policy. `test_retry_policy_persisted_in_snapshot` covers the full
create_execution→snapshot→spec chain for `retry_enabled=false`.

**Windows retry policy — implemented; real-host verification
pending.** NOT accepted. No confirmed-orphan resolution exists on
Windows, so automatic relaunch is DISABLED there — chosen option 2
(enforced disablement) of the policy set. Enforcement: (a)
`_retry_policy(posix=False)` forces `retry_enabled=false/
max_attempts=1` into the spec irrespective of run_config; (b) a
PowerShell `prep` step (`doStepIf=_win`) keeps
`.to_exec_attempt_<id>` and exits 70/`TO_RETRY_BLOCKED` on ANY
attempt > 1 — unconditional, so no spec can slip a relaunch
through. POSIX `rm`-based cleanup replaced by a PowerShell variant
on Windows (`rm` does not exist there — defect caught
pre-acceptance). Tests: `test_windows_spec_forces_retry_
disabled`, `test_win_prep_blocks_any_second_attempt`,
`test_win_and_posix_predicates_partition`,
`test_win_cleanup_uses_powershell_not_rm`. Kit row W6 is the
acceptance gate — on the real host it must verify: the
`.to_exec_attempt_<eid>` counter persists across the
cleanup/re-staging/retry sequence (file still present, contents
`2`); the second attempt is blocked in `prep` **before the test
CLI starts** (no `run`-step stdio, no pytest/robot process ever
spawned — `Get-Process` before/after reconnect); the resulting
**UNKNOWN** retains reservations and appears on `/reconciliation`
with the `buildbot_retry_attempt` audit. Until W6 passes on a real
host this row stays open.

Candidate under test: `feature/2.6.0-node-runners`, evidence below
recorded at commits `b70e73b` (slot-builders), `e859b52`
(unlaunched-cancel resolution + test fixes) and the PB-loss fix set
on live instance `/tmp/to251d` (imported tree
`/tmp/to251d/testorchestrator/`).

Environment: Buildbot master on 127.0.0.1:8010 (PB :9989), portal
:8443, runner `c260-linux-worker` (id `89413d40…`, `bbw-89413d40…`,
max_slots=2), SSH target `c251d-ssh` (`2f51617b…`, `to-ssh-dispatcher`).
Test fixture revisions are pinned per scenario. All runs dispatched
through Buildbot slot-builders (`to-target-<id>` + `to-target-<id>-s2`;
SSH `to-ssh-<id>` + `-s2`).

## Stage 5 — parallel execution

| Scenario | Evidence | Result |
|---|---|---|
| Same-runner concurrency | exec `14b68765` slot1 → `to-target-…-s2` build 1 (10:21:35→10:24:16); exec `aba78b56` slot0 → `to-target-…` build 99 (10:21:36→10:24:17). ~161 s simultaneous builds on one worker. | **PASS** — previously serialized per (builder,worker) pair |
| pytest/xdist overlap | bb:701 (earlier pass) + `6941ff8a`/`53d589d9` `-n2` runs on slots 0/1 — builds 106/8 both 11:01:18→11:02:39 | **PASS** — 4/4 cases, xdist workers concurrent per run |
| Playwright `--workers 2` | bb:711 — "Running 5 tests using 2 workers", 5/5 | **PASS** |
| Playwright shards | parent `d89c3cbe`: unit `a0e66f71` `--workers 1 --shard 1/2` ran {parallel a,b,c}; unit `0d2060a5` `--shard 2/2` ran {title check, arithmetic}. Frozen shard in unit snapshots; non-overlapping, complete coverage (5 tests). | **PASS** |
| Cypress partitions | parent `b1be38e5`: 3 spec units, units 0+1 overlapped (builds 3 @ s2 + 101 @ base), unit 2 queued → reused freed slot. Every spec assigned exactly once via frozen `unit.specs`. | **PASS** |
| Robot/Pabot overlap | bb:703 — two `robot -A` children concurrent (pabot_results/0,1,2 retained), merged output.xml/log.html/report.html + junit | **PASS** |
| Failure aggregation | parent `03de162a` → FAILED: unit `2768496e` (specfail) FAILED with junit (1 failed + 1 passed case) + failure screenshot; units `dc521f9c`, `4fe368d4` PASSED. | **PASS** — failed unit not hidden |
| Cancellation isolation | `af34121f` CANCELED mid-run (build 2 "cancelled (portal cancel request)") while `3bbc151b` ran to PASSED on slot 0 unaffected | **PASS** |
| Parent cancel (running+queued) | parent `3910f61b`: units `f0586fa5`/`631ca148` running → CANCELED (builds 4,103 cancelled); unit `4ccabb69` QUEUED → CANCELED without any build submitted; parent → CANCELED/INCOMPLETE | **PASS** — surfaced+fixed bug `e859b52` (`_resolve_unlaunched_cancels`) |
| Restart mid-parallel | portal **dispatch worker** (flask `testorchestrator worker`, pids 3770335/3770336) SIGKILLed ~11:01:4x during builds 106+8 overlap; both reconciled → COMPLETED/PASSED via durable reconcile. Killed: the portal-side dispatcher process only — master, PB workers, and remote CLIs untouched | **PASS** |
| Scheduled parallel | `sched-xdist` (once) → fired → `enabled=0`; exec `74109600` PASSED, snapshot preserved `parallel_mode=parallel, parallel=2`, frozen sha `8f0ba933`, item `pyxpar59` | **PASS** |
| Mixed-framework capacity | `max_procs=3`: pytest `-n2` (charge 2) `2e58e29d` dispatched; Robot `--processes 2` (charge 2) `9fc572e0` QUEUED (4>3); released → dispatched → both PASSED | **PASS** — process budget enforced + released |

## Worker PB loss (no master restart) — 11:12:33

Exact sequence (note: a first SIGKILL at 11:11:28 hit worker
`to-local` pid 3269820 — a *different* registered worker not serving
the build; the build was unaffected. The PB-loss interruption proper
followed at 11:12:33):

- Confirmed pytest CLI running on `bbw-89413d40` (pid 3773474)
  before interrupt; `kill -9` on worker pid 3246956
  (`/tmp/bbworker` — the process registered as `bbw-89413d40`).
  Master and all other processes untouched.
- Master log: `lostRemote`, `ConnectionLost`, worker detached from
  both slot builders; build 109 ended `results:retry` — Buildbot
  resubmitted the same buildrequest.
- Orphaned remote pytest 3773474 **survived** worker death and kept
  running unobserved (still alive at 11:13).
- Execution stayed DISPATCHED (lease renewed — genuinely uncertain,
  not silently failed/retried as a new submission).
- Worker restarted 11:13:37 → re-attached → retried build 110 ran
  the same buildrequest → success → reconcile → `5e4049aa`
  COMPLETED/PASSED.

**Historical gap on the 11:12 run (pre-fix):** the retry ran while
orphan 3773474 was still active in the same builddir — which attempt
produced the uploaded junit was not established, the orphan was
never resolved, and the retry was not recorded as a distinct
attempt. That row stands as pre-fix evidence only.

### PB-loss resolution — implemented + re-verified (post-fix)

Mechanism (all transports): `sh -c 'echo $$ > .to_exec_pid; exec
"$@"'` wrapper records the exec'd CLI pid at the builddir root;
`TO_EXEC_ID` is injected into the exec env so a later retry can
prove the recorded pid belongs to *this* execution (pid-reuse can
never hit an innocent process). Every build starts with a `prep`
step (POSIX-gated via spec `posix` flag — Windows workers get the
raw argv contract, no pidfile) that resolves prior-attempt pids:
`kill` only on env-marker match, reported either way
(`terminated orphaned prior attempt` / `already exited` / `alive
but env marker mismatch — left running`), pidfile removed, staging
dirs wiped so a lingering orphan cannot pollute the retried
workspace. Uploads go to `artifacts/<exec>/attempt-<buildno>/` so
each attempt's reports are attributable; the reconciler records
every build under the brid into `snapshot.bb_attempts` and audits
`execution.buildbot_retry_attempt`. Buildbot's automatic resubmit
(builder.py:457 `_resubmit_buildreqs`) is unconditional and cannot
be disabled — the design converts it into a *safe* resume: orphan
resolved synchronously before re-staging, workspace wiped,
attempts and artifacts distinct and audited.

- **PB worker retry** — exec `72123296`, brid 776: worker SIGKILL
  mid-`pytest` (pid 3790683, pidfile + `TO_EXEC_ID` verified);
  build 112 `lostRemote`→RETRY. Retry build 113 `prep` reported
  `prior attempt pid 3790683 already exited` (orphan self-
  terminated within ~50 s — captured stdout pipe death), wiped
  workspace, attempt-113 artifacts → PASSED. `bb_attempts` =
  [{112:RETRY,complete},{113:SUCCESS}] + retry audit event.
- **PB worker retry, longer dead-window** — exec `85bd3034`,
  brid 780: orphan 3791064 survived worker death; prep on build
  116 reported it already exited before re-staging; retry pytest
  = new pid 3791423, new pidfile — no double-execution.
- **SSH dispatcher loss (persistent remote orphan)** — exec
  `386af28a`, brid 783: dispatcher worker SIGKILL mid-run;
  remote `setsid` run 3791749 **persisted**. Retry build 634:
  prep resolved the dead local dispatcher pidfile, new
  dispatcher 3791835 reconnected and **resumed** remote run
  3791749 (same `run.pid`/pgid — no relaunch, true
  single-launch) → remote completed → collected under
  `attempt-634/` → PASSED; both attempts + audit recorded.
- The kill branch (`terminated orphaned prior attempt`) executes
  whenever an orphan outlives the restart gap — both PB orphans
  here self-terminated first; SSH remotes resume by design rather
  than being killed.

Distinct from: service restart, master SIGKILL (bb:645 earlier —
FAILED honest abort), SSH-session loss (bb:254 lineage).

## Code-level invariants verified

- Slot selection: busy slots skipped, freed slots recycled,
  `bb_slot` persisted per execution (test `test_slot_builders_and_pick`)
- `CANCEL_REQUESTED` + no `dispatch_id` + no `started_at` → CANCELED
  (never launched); parents excluded — rollup owns their outcome
  (test `test_queued_child_cancel_terminalizes_and_parent_rolls_up`)
- Combined capacity: job-slot CAS + `Σ requested_procs ≤ max_procs`
  CAS; charge model: sequential=1, parallel=requested, default
  playwright=unbounded on budgeted runner (config error), parent=0
- Rejected without dispatch: Cypress `parallel>0`, bad shard pairs,
  missing `opt_xdist`/`opt_pabot` probes in parallel mode

## CY-fail-over-SSH — current-candidate revalidation

- `ef962bb2` (binding `0ef16364`, sha `0389e85`, `c260-ssh-cypress`
  runtime on `c251d-ssh`): COMPLETED/FAILED — `spec2 failing
  intentional assertion failure` FAILED, `spec3 long-running`
  PASSED; per-case outcomes over SSH transport. bb:254 remains the
  historical record for the earlier candidate; this is the
  revalidation row, not a relabel.

## Queue & resource policies — live verified (12:10–12:19)

Evidence on live instance (`/tmp/to251d`, working tree synced —
not yet clean-package):

- **Slot capacity + wait reasons**: 3 sequential runs on
  `max_slots=2` — `f8579d42`/`870355f4` DISPATCHED (slots 0/1),
  `939da91d` QUEUED with `wait_reason="capacity: runner
  'c260-linux-worker' job slots full (2/2 in use)"`; on release it
  redrove FIFO → DISPATCHED slot 1 → COMPLETED.
- **Reservation ledger**: `939da91d` acquired `resource_reservations`
  rows `slot` idx 1 + `procs` qty 1 at dispatch; on COMPLETED both
  `released_at` set, `release_state='terminal'`.
- **Procs budget + starvation avoidance**: `max_procs=3`; strays
  `8b99b7a2`+`f82dae23` and fillers `462a79f6`/`929b0c54` (charge 2
  each) queued behind full capacity while charge-1 `997e16e0`
  (created later) was admitted — deeper-scan FIFO skips
  head-of-line-blocked jobs instead of starving them.
- **Queue deadline**: `462a79f6` `queue_deadline_at` passed while
  blocked → FAILED `error_kind='queue'` ("queue deadline exceeded —
  still waiting (…); increase runner capacity or
  queue_timeout_seconds") + audit `execution.queue_deadline_expired`.
  Deadline applies to QUEUED only; dispatched runs unaffected.
- **Schedule misfire**: schedule `1c47d7c8` 1801 s overdue vs 10 m
  interval, `misfire_policy=skip` → occurrence dropped, `next_run_at`
  advanced one interval, audit `schedule.misfire_skipped` — no
  catch-up storm, no double-dispatch.
- **Explicit invalid runner**: execution pinned to nonexistent
  runner id → immediate FAILED "no fallback to another target"
  (fail-fast for explicit targets; wildcard waits instead).
- **UNKNOWN retains resources** (code invariant): `UNKNOWN ∈
  _ACTIVE_STATES` (slot+procs charge held) and `UNKNOWN ∉
  _TERMINAL_STATES` (reservation rows stay open) — capacity stays
  blocked until operator reconciliation. A connection loss never
  frees a slot/environment while the original may still be using it.
- **Two distinct deadlines**: `queue_timeout_seconds` →
  `queue_deadline_at` → FAILED `error_kind='queue'` (only while
  QUEUED, verified above) vs `timeout_seconds` → runtime deadline
  enforced inside the invocation (`exec_timeout`, tree force-killed
  before slot release) → FAILED run outcome. Distinct kinds,
  distinct surfaces.
- **Time zones / DST — not applicable by design**: schedules are
  `once` (absolute UTC `next_run_at`) or `interval` (`now +
  interval_minutes` duration arithmetic). There is no wall-clock
  cron kind, so no schedule can be DST-shifted; every comparison is
  absolute-time UTC. If wall-clock scheduling is ever added it will
  need an explicit tz field + DST policy — recorded here so the
  requirement isn't silently forgotten.
- Regression coverage: `test_fifo_redrive_skips_blocked`,
  `test_misfire_skip_policy`, `test_reservations_*`,
  `test_queue_deadline_*` (63 passed).

## CI API + webhooks — live verified (12:26–12:30)

`/api/v1` bearer-token surface + durable outbound notifications
(migration `z8a9b0c1d2e3`; token `ci-live-check` scope `run`):

- `POST /api/v1/executions` → `abca0eac` created from discovered item
  `pyxpar59`, `client_ref="ci-live-001"` persisted, `deployed_rev`
  stamped in response.
- Idempotent replay: identical `client_ref` POST returned the SAME
  execution id with `idempotent_replay=true` — no double-launch.
- `GET /executions/<id>` → `dispatched`, `bb_slot=0`,
  `attempts=[{buildid:796, number:122}]` — Buildbot attempt chain
  visible through the API.
- Run completed PASSED; `_enqueue_terminal_notifications` fanned out;
  `webhook` outbox events delivered to a local receiver with
  `X-TO-Event: execution.completed` + `X-TO-Signature: sha256=…`
  (HMAC key in the encrypted secret store — never inline).
- Two deliveries = two genuinely-terminal executions (`68e44b0a` SSH
  + `abca0eac`) — not a double-enqueue; `notified_at` stamps prevent
  re-fan-out, and zero-endpoint sweeps mark executions so
  later-created endpoints never replay history. Upgrade backfills
  `notified_at` for already-terminal rows.
- Regression coverage: `tests/test_api_ci.py` (10) — auth 401s,
  read-vs-run scope, project scoping (403 trigger / invisible read),
  cancel, retry-chain, cases/artifacts, enqueue filter+scope,
  signed delivery, retry-on-failure.
- CSRF exemption scoped to `api_bp` only (bearer, no cookies).
- Full suite: 734 passed (env-blocked: licence-key file, 2 Playwright
  UI files, `test_cancel_kills_process_tree` pgrep-flake vs live
  `slow-kre` from SSH run `3891f37d`).

## Reconciliation UI + manifests — live verified (12:47–13:04)

- `/reconciliation` admin view lists ambiguous executions (UNKNOWN /
  stale-cancel / orphaned-DISPATCHED) with held capacity + age; real
  UNKNOWN row `4613887f` rendered (commit `adc7945`).
- Sealed evidence manifests: `_collect` writes `manifest.json` into
  report_dir, registers it `kind=manifest`; API
  `GET /executions/<id>/manifest` re-verifies every listed file
  (existence + root-containment + SHA-256).
- **Bug found + fixed** (`c7642ac`): `kre-*.log` artifacts registered
  as `logs/…` relative to report_dir but stored under workspace root —
  permanently undownloadable (404). `_collect` now mirrors logs into
  `report_dir/logs/`; live re-run `1e2edef6`: 3 artifacts, 0
  missing/mismatched, log download 200.
- History matrices (commit `cf1e932`): `/suites/<id>/matrix` and
  `/discovered/<id>/matrix` — case_ref rows × 15 recent terminal
  executions; flaky rows and persistent failures ranked first; skips
  stay skips, unresolved marked. Live item `406c580c`: 15 execs,
  real case rows.

## Backup/restore — live verified (13:06–13:09)

- `backup_state` on the live instance → `backup-20261120T120654Z.tar.gz`.
- **Bug found + fixed**: instance contains an installer-generated
  absolute symlink (`buildbot/master/master.cfg` →
  `/abs/…/data/buildbot/master.cfg`); `tarfile` `data` filter rejects
  absolute links → backups were unrestorable. `recover` now rewrites
  absolute links that resolve inside the archive to relative form and
  skips links pointing outside it.
- Live restore: 11,142 members extracted; table counts match exactly —
  executions 816, test_results 722, artifacts 2927, users 1, runners 2,
  schedules 7; link restored as relative `../master.cfg`; restored
  instance boots (`create_app`) with secret store intact.
- Regression coverage: `test_absolute_symlink_restored_relative`,
  `test_absolute_link_to_outside_member_skipped` (+14 existing).
- Orphan-evidence lifecycle (commit `ef18039`): `find_orphans` /
  `prune_orphans` existed but were never invoked — orphan dirs are
  now listed on `/reconciliation` with an explicit audited prune
  action (managed-root + no-symlink + live-ref guards re-checked at
  delete time). Live dry-run on the current instance: 0 orphans.

## Representative 2.5.1→2.6.0 upgrade — verified (13:09–13:11)

Real 2.5.x instance (`/tmp/to251c/data`, alembic `s9t0u1v2w3x4`)
copied and migrated to head `z8a9b0c1d2e3` via `flask db upgrade`
(the same `toctl db-upgrade` path the installer ExecStartPre runs):

- 7 migrations applied cleanly (runtime_kind → parent/child →
  probe_json → max_procs → bb_slot → queue policies → CI API).
- ALL pre-existing data preserved: audit_events 40, settings 12,
  users 1, outbox_events 5, projects 1, runners 1, secret_refs 4,
  suites 1 + entries, executions 5, artifacts 8, runtime_connections 1.
- All 2.6.0 structures created: resource_reservations, api_tokens,
  webhook_endpoints, wait_reason, queue_deadline_at, client_ref,
  notified_at, misfire_policy.
- **Bug found + fixed**: the `notified_at` backfill's `op.execute`
  UPDATE never committed — `transactional_ddl=False` + SA 2.x
  autobegin means raw DML needs `autocommit_block()`. Reproduced on a
  second copy, fixed, re-verified: all 5 pre-existing terminal rows
  marked notified (prevents stale-event storm on first webhook).
- Post-upgrade boot OK; ORM reads all 5 executions.
- Note: two 2.5.x-era migrations contain the same non-committing DML
  pattern, but only for inert settings cleanup — already applied on
  all deployed DBs; left as-is.

## Full-suite results — separately attributed runs

Run A — **batch full suite at `8fc0ae5`** (11m53s):
**751 passed, 11 failed, 1 skipped.** Failures: 10× modal
Playwright tests targeting the absent `:39995` preview; 1×
`test_production_key_auto_loaded` (external licence-issuer key,
absent by design). Kept as recorded — NOT re-scored.

Run B — **targeted rerun of the 10 modal tests at `8fc0ae5`** after
correcting the preview environment (seeded preview recipe below;
replaced a stale nov19 preview holding an empty fixture DB):
**10 passed in 46s.** This is a separate run — it does not retro-
edit Run A's tally.

Still open gap: `test_production_key_auto_loaded` remains
environment-blocked (external key required) — recorded as a gap,
not a pass. The 1 skipped test is a separately identified skip.

Run C — **batch full suite at `57445bc`** (post project-access +
retry-surfacing + Windows-prep changes; 8m08s):
**781 passed, 3 failed, 1 skipped.** Per-failure accounting — each
linked to its Run D outcome; no combined tally is claimed:

| Run C failure | Cause | Run D outcome | Remediation |
|---|---|---|---|
| `test_infra_controls_browser::test_second_runner_selected_persists` | Preview fixture: DB had only `preview-worker`; the test selects `option.nth(2)` (needs `rem-1`/`rem-2` remote runners) | **passed** (rerun) | fixture-only: seeded `rem-1`/`rem-2` remote runners into the preview DB — **no application code changed** |
| `test_infra_controls_browser::test_runner_selection_survives_validation_error` | Same fixture gap (same `nth(2)` selection) | **passed** (rerun) | fixture-only, same seeding — **no application code changed** |
| `test_production_key_auto_loaded` | External licence-issuer key absent — environmental by design | **still blocked** — recorded as a gap, not a pass | none possible in this environment; requires the external key |

Run D — **targeted reruns at `57445bc`** of the environment-fixed
tests: 5/5 infra pass (13s) — the whole
`test_infra_controls_browser` module, not only the two failures.
The batch tally stands as recorded; reruns are separate rows.
Historical note (superseded by the logging implementation): between
Run C and `adf4490` only docs/ledger commits landed, so Run C was
the full-suite evidence at that head. **`d6c14b3` adds application
code (logging exports + structured output)** — Run E below carries
the new full-suite result; Run C/D evidence stays attributed to
`57445bc`. The packaged-candidate full suite is retained as a
required row in `docs/packaged-acceptance.md` §6. Earlier evidence
stays attributed to its own revision (734-passed pre-retry-hardening;
751-passed batch at `8fc0ae5`; 71-targeted acceptance suites).

Run E — **batch full suite at `d6c14b3`** (logging implementation
head; 7m18s): **806 passed, 2 failed, 1 skipped.** Per-failure
accounting — no combined tally:

| Run E failure | Cause | Outcome | Remediation |
|---|---|---|---|
| `test_production_key_auto_loaded` | External licence-issuer key absent — environmental by design | **still blocked** — recorded as a gap, not a pass | none possible in this environment; requires the external key |
| `test_pipeline::test_cancel_kills_process_tree` | **Test-isolation defect — cause established**: the assertion `pgrep -f "slow-kre"` is a global process-table check; it matched the unrelated live SSH-acceptance fixture `/tmp/c251-slow-kre` (in-flight `run.sh` run) — the same mechanism previously recorded at the 734-passed run (live `slow-kre` from SSH run `3891f37d`). Cancel path itself not implicated | Failed in Run E; passed on isolated rerun; passed again post-fix with the live fixture still running | fixture fixed: pattern scoped to the test's unique `tmp_path` script. The sibling `test_process_contention` variant also hardened — `os.kill(pid,0)` can't distinguish a zombie; now polls `/proc` state for `Z`. Rerun evidence recorded below |

Run E covers the logging acceptance tests (`test_log_exports.py`,
20 tests — all pass inside the batch) plus every regression touched
by `record_audit`/`emit` callers.

**Deployment state — `/tmp/to251d`: restarted and verified.** Portal
was restarted in a dispatcher gap (no `to_ssh_exec.py`/`run.sh` in
flight — the gate held; SSH executions run as separate processes and
were untouched). Active code: `/tmp/to251d/testorchestrator/` synced
from `f96fcc1` — verified by content (`logexport.py` loads from that
tree; export routes answer 302/protected). The deployed tree carries
no git dir or build stamp, so `_revision()` reports empty on this
instance — revision identity here is the sync, not a packaged stamp.
Migration applied and verified: `z8a9b0c1d2e3 → a9b0c1d2e3f4`,
`log_export_jobs` table present.

### Logging hardening round (post-`d6c14b3`)

Review-driven fixes and evidence, all in this head's follow-up commit:

- **Export consistency**: selection boundary is now an id high-water
  mark (`max_id`, stored on the request/job) — a row inserted after
  export creation with an *older* `occurred_at` cannot leak in
  (timestamp-only cutoff had that hole; regression test added).
  `logs_export_max_rows` is enforced during generation, not just at
  count time. The two-concurrent-job limit is a DB-backed claim —
  enforced across processes, not per-worker. `.part` orphans and
  failed-job files are purged at startup and post-restart (tested).
- **Rotation collision found and fixed**: two rotations inside the
  same second produced the same rotated filename (seconds+pid) and
  the second rename clobbered the first — silent event loss.
  Rotated names now carry nanosecond uniqueness; covered by the
  concurrent-writers-during-rotation test.
- **Sink guarantees stated precisely** (`docs/external-logging.md`):
  best-effort delivery, loss/duplicates possible, local DB rows
  authoritative, `event_id` is the downstream dedup key; health
  counters are per-process and admin-visible on the Operational
  Logs page.
- **Real collector verification**: the shipped
  `deploy/otel-collector.example.yaml` was run unmodified (test paths
  aside) under `otelcol-contrib` v0.165.0 — `timestamp_utc` parsed to
  record timestamp, `severity` mapped (`warning`→`Warn(13)`),
  `event_id` + correlation fields preserved. Checkpoint resume after
  restart recovered same-file events; a file created during the
  outage correctly tails from `end` (documented loss window); live
  appends picked up. `filelog`→`file_log` rename applied (deprecation
  seen in the real run). The config provides no dedup — not
  advertised as such.
- **Redaction**: JSON-quoted secret keys (`{"secret": "x"}`) bypassed
  the free-text pattern — fixed (quote-tolerant `SECRET_RE`, Bearer
  substituted first so an `Authorization: "Bearer …"` value can't
  consume the keyword). Tests cover nested lists/dicts, mixed-case
  keys, free-text/exception-style secrets in both log types, before
  persistence, then through CSV + JSONL + audit export. Pattern-based
  limits documented — not claimed to catch every secret.

Run F — **batch full suite at `f96fcc1`** (hardening head; 7m37s):
**817 passed, 1 failed, 1 skipped.** The sole failure is
`test_production_key_auto_loaded` — the same external licence-issuer-
key environmental blocker (absent `/tmp/to-license-issuer/
private.pem`); still blocked, not passed. **Both
`test_cancel_kills_process_tree` variants pass inside the batch** —
the isolation fixes hold under batch conditions, with the live
`c251-slow-kre` acceptance fixture running concurrently. The +10
test delta vs Run E is this round's new coverage (export boundary/
cap/cleanup, sink hardening, redaction).

`TO_INSTANCE_DIR=/tmp/to-preview-data`, waitress on :39995, seeded:
User Admin/`Review-Preview-#2026!`, Project `62d2f3e1b4654e5680fd187795c454f7`,
GitBinding `authoring_writable=true`, one local Runner + pytest
RuntimeConnection, **two remote runners `rem-1`/`rem-2`
(connection_mode=remote, target_type=buildbot-worker)** for the
infrastructure browser tests, and `import testorchestrator.logs`
before `db.create_all()` so `operational_logs` exists (the
create_all path doesn't import the model — production gets it via
migrations; the modal/infra tests 500 without it). Modal buttons
need `can_author` (binding authoring flag) — an empty-seed instance
404s/omits them.

## Open
- ~~Worker PB-loss retry/orphan correctness~~ — **resolved**; see
  "PB-loss resolution — implemented + re-verified" above. Retry
  boundaries hardened (confirmed-terminate, mismatch-block,
  explicit retry_enabled/max_attempts, TO_RETRY_BLOCKED→UNKNOWN).
- Windows retry safety: **implemented; real-host verification
  pending** — enforced disablement (`d4c7e85`), acceptance gate is
  kit W6. Not claimed accepted.
- Windows matrix: Robot + pytest on a real Windows host —
  **blocked infrastructure**: no Windows host exists in this
  environment. Repeatable kit prepared and kept ready (W1–W15 incl.
  W6 retry policy, W13 paths-with-spaces, W14 service account):
  `docs/windows-acceptance-kit.md`. On host availability: run
  W1–W15, fix discovered defects, then the packaged matrix. Linux-
  actionable work that remained (logging hardening + verification,
  cancellation-isolation fix, controlled `/tmp/to251d` restart and
  active-revision verification) is tracked in this ledger — Windows
  being blocked never implied nothing was left on Linux.
- Final clean-package eight-combination smoke matrix — pending
  Windows. Procedure defined: `docs/packaged-acceptance.md`.
- ~~Final-head full suite~~ — Run C at `57445bc`: 781 passed,
  3 failed (2 preview-fixture → fixed+rerun pass; 1 external-key
  gap). Recorded separately from earlier runs. Packaged-candidate
  suite remains a `packaged-acceptance.md` §6 row.
- Logging implementation (`d6c14b3` + hardening follow-up): CSV
  export + structured output implemented and covered per
  `docs/packaged-acceptance.md` §5a — **reported implemented with
  focused coverage, not yet final-package accepted**. Run E
  (`806/2/1`) is the full-suite evidence at `d6c14b3`; Run F
  (`817/1/1`) is the evidence at hardening head `f96fcc1`. Windows-
  side logging checks fold into the W-matrix row (now W15).
- ~~`/tmp/to251d` controlled restart~~ — **done** (restarted in a
  dispatcher gap; synced tree loaded, `a9b0c1d2e3f4` applied; see
  deployment note above).

## Project access (membership) — implemented post-freeze under the
## approved access change

Authorization = role AND project membership (`User.allowed_projects`
— the existing §16 seam, semantics corrected: empty = none for
non-admins, Administrators bypass through the role). Enforcement:

- `User.project_allowed`: admin → all; others → assigned list only
  (`models.py`). No new/competing permission system introduced.
- Portal: `_project_or_404`/`_execution_or_404` per request
  (revocation on next request); executions list + filter dropdowns +
  schedules/frameworks scoped at query level; reconciliation rows
  already scoped; projects list shows a proper empty state.
- API: `api_token_required` resolves the token owner each request —
  deactivated owner → 401; `run`-scope token whose owner cannot run
  → 403; project scope = token scope ∩ owner's CURRENT membership
  (`_api_project_allowed`/`_api_project_ids`). Service tokens whose
  owner is not a user keep their own scope.
- Dispatch boundary (`_creator_still_allowed` in `run_execution`):
  pending work whose submitter lost membership/was deactivated — or
  whose `api:<name>` token was revoked/out-scoped — fails visibly
  `error_kind='access'` + `execution.access_blocked` audit; it never
  launches. Schedule-fired runs carry the creator's identity, so
  member-removed users' schedules stop launching (defined policy —
  not anonymous system work).
- Admin UI both views: System → Users → Edit → Project access
  (search/select-all/clear/role shown; admins see "All projects
  through Administrator role") and Project → Access (inverse
  matrix). Every change audited `user.project_access` with
  before/after lists. Users page flags unassigned users — the
  upgrade review workflow (nothing is silently re-granted; prior
  explicit lists are preserved).
- Backup/restore: `allowed_projects` is a users-table column —
  covered by the existing backup path (row counts verified earlier).

Acceptance: `tests/test_project_access.py` — 17 tests, 2 projects ×
2 same-role users differing assignments, isolation via URL/API/
export/artifact/ID-substitution, no role elevation, empty state,
mid-session revocation, token ∩ owner semantics, dispatch-boundary
block, admin UI roundtrips + audit. Two existing tests updated for
the corrected semantics; runbook form-posts keep retry default via
the hidden-field contract.

---

## Group A — Advanced Analytics acceptance closeout

**ACCEPTANCE: CLOSED** (source-level, at `175094f`). Qualifications
carried in the record:

- History columns represent **attempts** — retries appear as separate
  columns.
- Suite duration is **resolved-attempt wall-clock** — child durations
  are never summed.
- Turnaround means **enqueue→finished**, not results-ready feedback
  time (no such timestamp exists — documented instrumentation gap).
- First-attempt vs final pass rate has **no drill-through** — the
  executions-list filters cannot express its cohort; accepted as an
  explicit Group A limitation and now stated on the card itself.
- Live verification used **source-run Waitress** on `/tmp/manual251`
  at `175094f` — **not** packaged-candidate evidence.

**Attribution**:
- `175094f` — full-suite result (852 passed / 1 failed / 1 skipped)
  and live source-level acceptance.
- `31a2575` — subsequent inline limitation caption on the
  first-vs-final card (one display-text line; no logic or
  aggregation change).
- `cd4133f` — reported head at closeout recording.

`175094f..d10f25c` diff verified **documentation-only** (ledger
append, +86). Because of the `31a2575` caption, the current tree is
**not** entirely documentation-only relative to `175094f`; the small
template change stays identified and is covered by a targeted render
check rather than a broad rerun. The `175094f` tally is not
relabelled as having run at the current head. The six initial
regressions + fixes stay as historical evidence; the final tally is
the single full-batch result (852/1/1), not a combined rerun total.

**Feature revision**: `80cd41f` (Group A implementation; includes the
Executions Worker-filter fix — the template iterated `workers` while
the route passed `runners`, verified via `git log -S`).
**Separately identifiable changes**: `df9df45` Project Access-tab
styling; `fccd576` changelog at feature landing; `9951af0` closeout
hardening (exact drill-through, deterministic bounds, counting doc);
`2e7e882` suite-regression fixes found by the full-suite run;
`8524504`/`ecdc397`/`1c1e3de`/`1f38ca0`/`a70b7e5`/`175094f` UI
corrections from live review (Open button in JS poll rows, release
names, data-table styling restore, flex-td artifact, row alignment,
ISO T/Z timestamps).
**Candidate for this tally**: `175094f` — see full-suite row below.

### Focused evidence (automated vs manual)

| Area | Result | Method |
|---|---|---|
| Filter consistency | PASS — period/suite/environment each narrow aggregation; env filter produces the single matching column; no silent merge (`TestFilterConsistency`, 2 tests) | Automated (`tests/test_analytics.py`) |
| Intentional exception | Source-ref & status filters apply to project-dashboard analytics; the main dashboard intentionally has only the period filter — no suite/source selectors exist there to apply | Design, documented in counting doc |
| Drill-down accuracy | PASS — env cell → `/executions?project_id&suite_id&environment&final=1` (live click, browser-verified); history cell → `/executions/<id>` the exact attempt (live click); outcome segment URL carries `final=1` (unit test `test_drill_url_carries_final_flag`); empty heatmap cells have no customdata and correctly do not navigate | Live browser + automated |
| `final=1` list filter | PASS — resolved attempts only; superseded chain head excluded; `role=dispatch` returns dispatchable cohort (`test_final_filter_shows_only_resolved_attempts`) | Automated |
| Interaction behavior | PASS — counts/% link-toggle updates URL state (`cmp_mode=percent`), removable chip `comparison: % ✕` appears and removes, Clear selection present, queue wait/turnaround/both selector changes `queue=` param, Refresh re-fetches JSON (timestamp advanced), legend toggle, drag-zoom and double-click reset all work | Manual (Playwright, live `:39998`) |
| Revocation | PASS — session kept alive, membership revoked mid-session → next `/projects/<id>/analytics` denied (403/404); main `/dashboard/analytics` returns 200 with the project scoped out — no cached unauthorized data | Automated (`test_revoked_membership_denies_next_request`) |
| Dataset limits | PASS — deterministic selection with tiebreaks (count then name); truncation notices name the ordering and how to reach omitted records; bounds are display limits, not aggregation limits; CSV/table/chart share the same bounded scope; `*_truncated` flags in JSON | Automated + doc review |
| Accessibility & layout | PASS — collapsible `<details>` data tables under every chart; all controls are native `a`/`button`/`select` (no custom widgets — keyboard-reachable by construction, Refresh activated via Enter verified); 420 px viewport keeps charts usable (Plotly responsive); sparse data renders correctly on the live demo | Manual + automated (empty-dataset tests) |

### Counting clarifications (docs/analytics-counting.md)

- **Test-result history**: columns are **attempts**, not logical
  runs — the 20 most recent terminal attempts, each labelled
  `finished day · execution-id`; a retry is its own column, no
  cross-attempt merging; attempt number + full id in hover/table;
  **missing results stay missing** (empty cell — never drawn as
  skipped or passed).
- **Suite-duration distribution**: **logical-run wall-clock elapsed
  time** — `finished_at − started_at` of the final resolved attempt;
  for partitioned runs the parent's own stamps (started when the
  first unit leaves the queue, finished when all units are terminal —
  confirmed in `execution.py` roll-up). Child-unit durations are
  never summed; parallel children cannot inflate wall-clock. Chart,
  data table, CSV and counting doc agree.
- **Queue chart**: labelled `enqueue→finished` — no dedicated
  results-ready timestamp exists (instrumentation gap documented);
  drill-through opens the day's dispatchable cohort; the median/p95
  timestamp sample restriction is disclosed.
- **First-vs-final chart**: intentionally no click-through — the
  cohort is defined by the *first* attempt's finish day, which the
  list filters cannot express; documented rather than approximated.

### Revision/deployment evidence

- 16 analytics tests + 25 dashboard/bootstrap regressions: run on
  the working tree at feature revision `80cd41f` (pre-closeout).
- 21 analytics tests (16 + 5 closeout): run on the working tree of
  `9951af0`.
- Suite run A: `2e7e882`, **852 passed / 1 failed / 1 skipped** —
  flagged unreliable: application files changed mid-run.
- Full-suite run B at `175094f` (unmodified working tree at that
  revision, all Group A + fixes):
  **852 passed / 1 failed / 1 skipped** — the single failure is
  `test_production_key_auto_loaded` (`FileNotFoundError:`
  `/tmp/to-license-issuer/private.pem`), the external issuer-key
  blocker — same failure as run A, not a regression.
- Live `:39998`: Waitress serving `wsgi:app` from the branch
  worktree, `TO_INSTANCE_DIR=/tmp/manual251`, restarted per revision —
  run from source, no build artifacts; screenshots taken at the
  revision live at the time (latest = `175094f`).
- Six initial suite failures were all regressions from the UI work:
  `audit-table` class leaking the string "audit" to non-admin pages
  (renamed `data-table`), three split literal strings in
  settings/secrets guidance, users-page unassigned wording — all
  fixed and re-verified passing at `2e7e882`+.

### Status board

| Area | Status |
|---|---|
| Advanced Analytics Group A | **Source-level acceptance closed** at `175094f` |
| Advanced Analytics Group B | On hold — NOT authorized by Group A acceptance |
| Backup and Restore | Implemented; source-level tests verified at `175094f` (14/14, within that full-suite batch). Windows protection/path behavior and packaged reinstall, recovery, and upgrade/restore acceptance remain outstanding. Settings-only scope — this format does not back up execution history, reports, artifacts, or the audit trail |
| Windows W1–W15 | Real-host acceptance outstanding |
| Clean packaged candidate + final matrix | Partial — first Linux pass recorded above (install, zoneinfo §5b, backup/recover, 2.5.1 upgrade, export); 8-combination matrix + remaining §5 sweep outstanding |
| External licence-issuer-key test | Blocked — missing external private key |

### Remaining gates (unchanged, still open)

- External licence issuer-key test — `test_production_key_auto_loaded`
  needs `/tmp/to-license-issuer/private.pem` (does not exist on this
  host) — external blocker, not a regression.
- Windows W1–W15 matrix on a real host (kit ready).
- Backup & Restore — implemented and source-tested (14/14 at
  `175094f`); the following cross-cutting package/security/recovery
  gates remain open and are NOT satisfied by the eight
  framework/target execution combinations:
  - Windows backup/staging/download file protection, service-account
    access, staging cleanup, and path behavior (real host).
  - Packaged `toctl backup` → `recover` roundtrip.
  - Clean packaged reinstall → restore → login + configuration
    verification.
  - Supported older-version backup → newer packaged application
    (filtered restore path).
  - Preservation of roles and project assignments through restore.
  - Session/token invalidation, runners landing in
    needs-verification, and schedules staying inactive until
    explicitly re-armed.
  - Managed encrypted credentials decrypting after `secret.key`
    restore on the new host.
  - Failed/interrupted restore leaving a usable configuration with
    no partially applied key or settings state.
- Clean-package 8-combination smoke + parallel/recovery/security/
  upgrade/restore/reinstall gates.
- Group B charts stay on hold until this closeout is accepted.

## Advanced Analytics Group B — implementation + evidence record

Authorized after Group A closeout. Four charts added beneath the
existing dashboards; Group A definitions unchanged (first-vs-final
reuses Group A's shared `_first_final_rows` aggregation).

### What was built

- **Execution activity heatmap (Main Dashboard)** — UTC
  day-of-week × hour grid over logical runs; submitted vs started
  selector (started = first actual execution start; never-started
  excluded); each logical run counted once (retries and unit
  children deduplicated by the shared logical-run resolution);
  timezone and selected period displayed; cell drill-through opens
  an exact cohort via a bounded `activity=submitted|started` +
  `dow` + `hour` + `from_date`/`to_date` filter on the executions
  list (bucket timestamp is submitted time or first-start time, so
  the generic `created_at` filter is bypassed for this mode —
  documented).
- **First-attempt vs final pass rate (Project Dashboard)** — same
  logical-run cohort under project/suite/source-ref/environment/
  period filters, grouped by first-attempt day; hover shows
  numerator, denominator, retry count, and the count of chains
  excluded because the first attempt is non-terminal (exposed in
  chart hover, data table, and CSV). No drill-through — cohort is
  defined by first-attempt day, which list filters cannot express;
  stated inline on the card (Group A accepted limitation
  preserved).
- **Suite-duration regression (Project Dashboard)** — median
  logical-run wall-clock duration vs the immediately preceding
  equal-length period; identical suite/source-ref/environment
  filters applied to both windows; chains resolved once over the
  union of both windows so a head+retry pair cannot be counted in
  both (fixes an initial implementation bug caught in review);
  seconds and % views; N/A for missing/zero baselines;
  insufficient-sample flag below 3 samples; contributing-execution
  links for both periods; bounded display (top-12 suites, 10
  contributing links each way).
- **Evidence freshness (Project Dashboard)** — elapsed time since
  the latest usable result per suite×environment in scope; a
  completed failing result counts as evidence; last timestamp,
  outcome, and execution link shown; fresh / stale / never-observed
  states on a documented configurable threshold
  (`EVIDENCE_STALE_DAYS = 7`); lookup reaches beyond the selected
  period (disclosed via a beyond-window marker) so old evidence is
  not mislabelled; "never" only where both suite and environment
  are known to exist from configuration/history.

Shared requirements: vendored Plotly.js, existing palette,
`analytics.py`/`charts.py`, existing JSON + CSV endpoints; manual
Refresh only (not the 5 s live poll); `uirevision` preserves zoom/
legend; collapsible data tables and authorized CSV for every card;
chart/table/CSV scopes identical; deterministic display bounds
disclosed (`MAX_REGRESSION_SUITES=12`, `MAX_REGRESSION_EXECS=10`,
`MIN_REGRESSION_SAMPLES=3`, `MAX_FRESHNESS_SUITES=12`,
`MAX_FRESHNESS_ENVS=8`); role + project membership enforced before
aggregation and on every endpoint; stale-response guards retained.

### Test evidence

- `tests/test_analytics.py`: **38 passed** (21 Group A + 17 new
  Group B) — fixture-verified matrix counts, started-mode
  exclusions, dedup, baseline-union resolution, N/A and
  insufficient-sample handling, freshness states incl.
  never-observed and beyond-window lookup, CSV scope, truncation
  flags computed pre-cap.
- Affected Group A/dashboard/access regression batch: **86
  passed**; project-access batch incl. changelog/access: **78
  passed**.
- Live verification on `:39998` (source-run Waitress,
  `TO_INSTANCE_DIR=/tmp/manual251`): all cards render; activity
  cell click → exact cohort list (cell count 3 = 3 resolved
  attempts, superseded head excluded); env cell → exact filtered
  list; history cell → exact attempt; reg-mode selector and
  percent/seconds views verified; freshness table shows age cells
  + `never` row; inline no-drill note present on first-vs-final.
- Tab correctness verified in-browser: analytics figures render
  only inside `#panel-analytics`; Git bindings and Access panels
  show only their own content (a stray `</div>` + missing
  `</section>` in the extracted include had let chart markup
  escape the panel — fixed, tag-balance checked, commit
  `49080d6`).

### Evidence map — each requirement points to existing evidence

Not re-run; this maps the authorized checklist to where it was
already demonstrated.

- **Activity heatmap** — submitted/first-start counting, retry/
  child exclusion, UTC display, exact selected-cell cohort:
  fixture tests `test_activity_*` in `tests/test_analytics.py`
  (38-test file) + live click → 3-count cell ↔ 3 resolved
  attempts (superseded head excluded).
- **Project first-vs-final** — identical cohort + denominator
  policy, applicable filters, exclusion count, no-drill
  limitation: `test_first_final_*` fixtures + card caption +
  `docs/analytics-counting.md`.
- **Duration regression** — previous equal-length baseline,
  matching filters, sample counts, missing/zero-baseline N/A,
  baseline-union chain resolution: `test_regression_*` fixtures
  incl. the union-resolution case (initial two-window bug fixed
  before candidate).
- **Evidence freshness** — usable-result definition, complete
  failures count, beyond-window lookup, stale vs never-observed:
  `test_freshness_*` fixtures + `EVIDENCE_STALE_DAYS=7` +
  live `never` row.
- **Shared behavior** — membership before aggregation,
  post-revocation JSON/CSV denial, chart/table/CSV agreement,
  display limits, manual refresh, `uirevision` state:
  `test_analytics_*` permission/CSV tests + live refresh check.
- **Renderer + tab/template changes (separate trace)** — nested-
  list rendering, in-place Access/Analytics tabs, panel
  containment: `test_project_access.py` (17) + `test_changelog*`
  within the 78-test batch; live `#panel-analytics` containment
  check. Tracked under `3995f7c`/`49080d6`/`c955c79`, not under
  the four charts.

### Revision + suite tally — runs recorded separately

- Feature commits: `3995f7c` (Access tab + analytics link),
  `49080d6` (analytics tab embed + template balance), `c955c79`
  (changelog Group B + renderer nested-list + UI fixes).

| Run | Result |
|---|---|
| Initial interrupted batch at `c955c79` | **348 passed / 1 skipped / 1 error** before abort — `:39995` disposable preview unavailable (`ERR_CONNECTION_REFUSED`); environmental outage, batch NOT counted as completed |
| Standalone preview verification | **16 passed** (63 s) after preview restart against preserved seed `/tmp/to-preview-data` |
| Completed full-suite batch at `c955c79` | **869 passed / 1 failed / 1 skipped** (8 m 07 s) |

These results are recorded separately and are not combined.
The completed batch is the full-suite batch *with the known
external-key failure*: `test_production_key_auto_loaded` —
external licence-issuer private key absent
(`/tmp/to-license-issuer/private.pem`) — **blocked, not
passed**. The 1 skip is the separately identified skip. Delta
vs the `175094f` batch (852) = +17, exactly the new Group B
tests. The preview outage and recovery are recorded as
environmental evidence only.

### Packaged Linux acceptance — first pass (`f96b645b`)

Candidate artifact built from `cea6b9be` (application code
`753c0c0b` + the `f96b645b` vendored-wheel fix; build tree showed
DIRTY only for that uncommitted fix):
`dist/release/linux/testorchestrator-2.6.0-linux-x86_64.tar.gz`
(200,530,903 B, sha256
`b74a29eae0f0d2c52a8b73584af0fda3ac9b023a5ffc93fa144f05b6416291f4`)
+ `.run` — built with `TO_BUILDBOT_INTERNAL_BUILD=1` (internal
packaging test; the manifest marks it **not approved for
distribution** — GPL redistribution approval stays an explicit
decision).

**Corrected defect found by this build** — `tzdata==2026.6` was
pinned in `requirements.txt` but absent from the vendored
`3rdparty/python-wheels/` set, so the packaged offline
`--no-index` install failed validation (`No matching
distribution`). Fixed in `f96b645b` by vendoring the wheel +
notices entry; the re-run build passed.

| §5b/§4 row | Result |
|---|---|
| Install `.run` → payload/data/config, buildbot provisioned offline, DB migrated to head | **PASS** |
| Linux package zoneinfo: `ZoneInfo('Europe/Budapest')` + `ZoneInfo('Asia/Kolkata')` load | **PASS** — and with `PYTHONTZPATH` pointed at an empty dir (host db unreachable) both zones still resolve → the **bundled** tzdata is proven, not the host db |
| Missing-database degradation: `PYTHONTZPATH`=empty + `tzdata` removed | **PASS** — two explicit `usertz` warnings logged, all output `+00:00`, `all_zones()`→`[]`, picker renders UTC-only; no crash, login path unaffected |
| `toctl backup` → `.tobackup` | **PASS** (36 members) |
| `toctl recover` → scratch dir | **PASS** — DB + `secret.key` restored; `tester` keeps `Asia/Kolkata` + `['pkgp']` (**assignment preservation**); `pkg-git` secret decrypts on the recovered instance (**credential recovery** — key travels in the encrypted payload) |
| Upgrade: real 2.5.1 DB (`/tmp/manual251-data`, alembic `r8s9t0u1v2w3`, no tz column) → packaged `toctl db-upgrade` | **PASS** — all 9 migrations applied to `a2b3c4d5e6f7`; every table count preserved (3 users / 3 executions / 9 results / 1 schedule / 27 audit / 2 secrets / 10 settings); `users.timezone`=UTC; `notified_at` backfilled; `runtime_kind`=`kre`; `/login` 200 on upgraded data |
| Export/logging on the package | **PASS** — audit CSV via the installed app carries `timestamp_utc` (`Z`) + `timestamp_local` + `timezone`; secure-cookie + Referer enforcement intact |
| `flask diag` / `health` / `install-info` | **PASS** (`health` → ok; diag no mismatch) |

Still open on this package: 8-combination execution matrix,
parallel/recovery/security §5 sweep, service-level file-mode/journal
rows — they need the systemd-installed services and run hosts, not
just the payload.

### Status board (updated)

| Area | Status |
|---|---|
| Advanced Analytics Group A | **Source-level acceptance closed** at `175094f` |
| Advanced Analytics Group B | Implemented; source-level evidence above at `c955c79` — **acceptance review pending; does not close any gate below** |
| Backup and Restore | Implemented; source-level tests verified at `175094f` (14/14 within that batch). Windows/package gates outstanding. Settings-only scope |
| Windows W1–W15 | Real-host acceptance outstanding |
| Clean packaged candidate + final matrix | Partial — first Linux pass recorded above (install, zoneinfo §5b, backup/recover, 2.5.1 upgrade, export); 8-combination matrix + remaining §5 sweep outstanding |
| External licence-issuer-key test | Blocked — missing external private key |

Live `:39998` remains source-run Waitress at `c955c79` — not
packaged-candidate evidence. No merge, no publication.

## Per-user display time zones — implementation + evidence record

Authorized work item: per-user IANA time-zone preference applied to
display and analytics while machine-facing instants stay UTC.

Implementation commits: `4a9d8779` (feature + focused tests),
`f2142c81` (null-guard fix + Group B first-attempt-day assertion +
changelog). Application candidate for the completed full-suite
batch: **`f2142c81`**.

Post-`f2142c81` commit chain (each classified — code changes
application behaviour or markup; docs touches evidence/prose only):

| Commit | Kind | Content |
|---|---|---|
| `7f754ea3` | docs | This ledger section (`f2142c81..7f754ea3` is ledger-only — confirmed by `git show --stat`) |
| `57428d34` | code | `usertz` picker curated from ~600 `available_timezones()` to 313 primary zones read from `zone1970.tab` (TZPATH or bundled `tzdata`, hardcoded fallback) + hint text + test — all in scope |
| `45fa907c` | code | Picker becomes a grouped native `<select>` (`_tz_select.html` include, region optgroups, "Saved" group for off-list zones); routes pass `tz_groups`; datalist include deleted; all in scope |
| `04a1a0ac` | code | Users-table timezone cell becomes a per-row grouped `<select>` + Save posting to `save_user_timezone`; `next=users` redirect added; test — all in scope |
| `d34d75a5` | code | Cell becomes click-to-edit: hidden checkbox `tzt-<uid>` + `tr:has(.tz-toggle:checked)` CSS swap between plain-text view and the select/Save/Cancel form; CSS-only, no JS — in scope |
| `5f0128f2` | code | Edit/Cancel labels restyled `ghost`→`secondary` (the ghost style rendered invisible on the table) + `cursor: pointer` — in scope |
| `0ba42be0` | code | `user_access` page reordered so project-access leads and the timezone card follows; access Edit link → `secondary`; cell/select widened — in scope |
| `e1cf50c0` | code | Timezone card removed from the access page entirely (access page = assignments only; zone shown read-only in the facts header); `tz_form`/`tz_groups` dropped from that route; cell widened further — in scope |
| `9d7cfc27` | docs | CHANGELOG wording |
| `a5fd9787` | code | Users-table Edit controls right-aligned via `space-between` (`.access-cell` class added to the project-access cell; ACTIONS column untouched) — in scope |
| `3b0d6e6e` | code | `usertz` resilience: module `UTC` falls back to `datetime.timezone.utc` at import if no zone database; `coerce_zone` logs a diagnostic; `all_zones` degrades to `[]`; `.tz-edit` wraps on narrow screens; 5 structural/resilience tests — in scope |
| `22fbe7c4` | docs | Acceptance docs only (this file, `packaged-acceptance.md` §5b, `windows-acceptance-kit.md` W16) |
| `753c0c0b` | code | Picker labels lead with the city ("Budapest — Europe/Budapest (UTC+01:00…)") so native-select type-ahead finds zones by city — fixes the searchable requirement in Chromium + Firefox — in scope |

`3b0d6e6e..22fbe7c4` is confirmed **docs-only** (3 `.md` files) —
the pushed head added no code beyond `3b0d6e6e` until `753c0c0b`.
Every code commit above is timezone/UI work — none are unrelated
features. The **899/1/1 batch stays attributed to `f2142c81`**;
the 188-passed affected batch and 38 focused tests are `3b0d6e6e`
evidence and are not carried to `22fbe7c4`/`753c0c0b` — see the
suite-accounting table for the next batch revision.
Revision closeout: **`753c0c0b`** is the application candidate —
browser type-ahead verification + the completed full-suite batch;
**`f4629343`** is the reported remote head (its ledger/doc change
kept separate — no code). **`:39998` is a source-run deployment
at `753c0c0b`, not packaged evidence.**

Recorded limitations (kept visible; no further selector/a11y work
in this closeout): the native `<select>` provides city-prefix
type-ahead, **not** arbitrary substring search; option-label UTC
offsets are *current* offsets, not fixed year-round values; focus
returns to the document top after Save; the invisible keyboard-
focus indicator on the hidden toggle checkbox is an explicitly
**deferred accessibility defect**, not an accessibility pass.

### What was delivered

- `users.timezone` IANA column — migration `a2b3c4d5e6f7`,
  server-default `UTC`; every existing user keeps identical
  display (Alembic path tested). The picker is a grouped
  `<select>` of ~140 curated major-city zones under region
  optgroups (UTC / Europe / Africa / Americas / Asia / Atlantic /
  Oceania & Pacific) whose labels lead with the city name —
  `Budapest — Europe/Budapest (UTC+01:00 now — varies by
  date)` — **this replaced the earlier searchable `<datalist>`
  on every surface** (Create User, the Users-list inline
  click-to-edit cell, and `/account` self-service). The native
  select's type-ahead matches the option-text prefix, so city-
  first labels are what make typing find a zone: verified in
  Chromium and Firefox — `budapest` → `Europe/Budapest`,
  `kolkata` → `Asia/Kolkata`, `utc` → `UTC` (`753c0c0b`; the
  region-prefixed labels before it matched only "europe/…"
  prefixes — recorded as a defect in the searchable
  requirement, fixed, not a scope change). The admin project-access
  page is access-only — the zone shows read-only in its facts
  header. Any valid IANA identifier outside the curated list is
  still accepted server-side; a saved off-list zone stays
  selectable under a "Saved" group. Browser detection suggests
  only, never overrides. Backend validates IANA identifiers;
  admin edits audit `user.timezone` without touching role or
  memberships; non-admins cannot edit others.
- Shared `usertz` helpers — safe validation + UTC fallback,
  `fmt_local*` with numeric offset (never `Z`), DST-correct
  local-day→UTC bounds, repeated-local-time disambiguation.
- Localized display across dashboards, execution lists/details,
  attempt history, audit trail, operational logs, schedule and
  upcoming displays, releases, admin pages, log-export jobs and
  app-generated report summaries. Raw runner stdout/stderr,
  downloaded logs and third-party artifacts untouched.
- Analytics (Group A/B policies unchanged) bucket by the
  viewer's local calendar day / weekday / hour; date filters
  become local-midnight→UTC bounds; drill-down cells match the
  same conversion; payloads + CSV carry the zone
  (`timezone` field / `tz` column) so a preference change
  refreshes rather than mixing zones.
- Schedules keep stored UTC fire instants — preference changes
  move no schedule; the form states execution zone (UTC) vs the
  viewer's display zone.
- Log-export CSV keeps `timestamp_utc` and adds
  `timestamp_local` + `timezone` columns; `filters_json` records
  the zone requested.
- Settings backup round-trips the preference; pre-timezone
  backups restore UTC silently; invalid identifiers restore UTC
  with an explicit attention warning.
- `tzdata` pinned so packaged Windows/Linux installs carry IANA
  data for `zoneinfo` (Windows build resolves pinned wheels).

### Focused tests (`tests/test_timezone.py`, 30 tests)

IANA validation + fixed-offset/nonsense rejection; invalid-zone
UTC fallback; numeric offset + no `Z`; non-whole-hour zone
(Asia/Kolkata +05:30); DST spring-forward gap + fall-back
repeated local times producing distinct offset-bearing strings;
local-day bounds across DST vs UTC; create-with-zone, invalid
rejection, admin edit, non-admin denial, self-service, audit
event; two viewers same event in different zones; executions
date-filter as local day; activity heatmap local dow/hour
bucket; drill cohort matching the local cell (and NOT the UTC
cell); analytics CSV `tz` column; freshness CSV UTC + local
columns; queue-wait AND first-vs-final first-attempt-day local
bucketing; schedule fire-instant invariance after a preference
change; schedule form discloses UTC execution zone; log-export
local columns; Alembic upgrade defaulting existing users to
UTC; backup round-trip / legacy-without-field / invalid-value
warning+fallback. **Result: 30 passed** (focused run at
`4a9d8779`, re-run inside the `f2142c81` batch).

Later focused results — kept separate, not added to the totals
above: **33 passed** at `d34d75a5` (picker curation + inline-save
tests), then **38 passed** at `3b0d6e6e` (+5 structural/resilience
tests: per-row toggle ids unique and disjoint from the
reset-password toggles; Edit/Cancel are non-submitting labels so
Cancel can never POST or audit; non-admin denied the Users page;
missing zone database → UTC output + logged diagnostic).

### Affected regressions

Dashboard, project dashboard, analytics, log exports,
operational logs (incl. live tail), schedules + plans, schedule
targets, settings backup, backup regressions, project access:
**172 passed** at `4a9d8779` — recorded as `4a9d8779` evidence
(that run predates the null-guard fix). Re-run at **`3b0d6e6e`**
across the same 14 files — recorded as three separate rows:

| Step | Result |
|---|---|
| Batch run 1 (`3b0d6e6e`) | 109 passed, then `test_stale_response_dropped_on_pause` failed `ERR_CONNECTION_REFUSED` — `:39995` was intentionally stopped (only `:39998` was asked to stay up); **environmental, not a code failure** |
| `:39995` restarted on preserved `/tmp/to-preview-data` seed | env recovery — no code change |
| Batch run 2 (`3b0d6e6e`, incl. live tail) | **79 passed → 188 total**, all green |
The 7 playwright modal tests that caught the template null-guard
defect re-ran green standalone (10/10 in the two modal files) at
`f2142c81`.

### Users-table click-to-edit cell — verification record

The cell exists on `/system/users` only (admin-gated; the access
page is access-only, `/account` is the user's self-service).
Mechanics: hidden per-row checkbox + `for`-matched labels, state
shown via CSS `tr:has(.tz-toggle:checked)` — **no JavaScript
participates**; the grouped `<select>`, Save (`type=submit`) and
Cancel (label) are a plain POST form to the existing audited
`save_user_timezone` route (`next=users` redirects back).

Browser verification at `3b0d6e6e` on scratch source-run instance
`:39997` (copy of the `:39998` data) **with JavaScript disabled** —
all 15 checks passed: login; ≥2 rows with tz cells; select hidden
by default; Edit reveals the grouped select; Cancel visible;
opening one row leaves other rows in view mode; Cancel hides the
select **and fired no request** (verified via request capture — no
audit write is possible); Save POSTs, redirects to `/system/users`,
persists the zone (`tester → Asia/Kolkata`) and returns to
text + Edit; Space on the hidden checkbox toggles the editor
(keyboard operable); tester (non-admin) gets no Users page/Edit;
420 px viewport: editor wraps. Audit table confirmed
`user.timezone: tester: UTC -> Asia/Kolkata` written by Save and
**no** event for the Cancel interactions. Focus after Save
returns to the document top (plain page navigation — same as
every other non-JS form on the page).

Accessibility notes (accepted for now, queued for a later
a11y pass): focus after Save returns to the document top —
plain page navigation identical to every non-JS form on the
page; the hidden toggle checkbox is keyboard-focusable
(Space toggles the editor, verified) but its focus ring is
invisible while `opacity:0` — a visible-focus treatment is a
candidate improvement; the type-ahead fix (`753c0c0b`)
improves keyboard findability of zones.

Structural tests at `3b0d6e6e` additionally prove: toggle ids
(`tzt-<uid>`) are unique per row and disjoint from the
reset-password toggles (`reset-<uid>`, separate class/id space —
no collision possible); the only `type=submit` inside a tz form
is Save; a non-admin is denied the page outright; missing
`tzdata` yields UTC + a logged warning.

### Localized vs non-localized surfaces (existing evidence)

- **Localized** (viewer zone, numeric offset): execution lists +
  details + attempt history, live log-viewer timestamps, audit
  trail, operational logs, schedule lists/forms + upcoming-fire
  displays, releases, admin/system pages, log-export job pages,
  app-generated report summaries, dashboard + project-dashboard
  charts (axes, hover, tables, heatmap buckets — analytics cache
  key includes the viewer zone, proven by the two-viewer test),
  CSV local columns carrying the offset + zone name.
- **Deliberately not localized**: raw runner stdout/stderr,
  downloaded execution logs, third-party report artifacts
  (source-generated content is preserved verbatim); CSV `*_utc`
  columns and machine-facing ISO/`Z` fields stay UTC; stored
  schedule fire instants unchanged (form discloses execution
  zone vs display zone — `test_schedule_form_keeps_utc_semantics`,
  `test_preference_does_not_move_schedule`).
- **Backup**: `test_older_backup_without_zone_defaults_utc`,
  `test_invalid_restored_zone_warns_and_falls_back`,
  `test_timezone_roundtrips_through_backup`.

### Suite accounting — recorded separately, not combined

| Run | Result |
|---|---|
| Full-suite batch at `4a9d8779` (first candidate) | **892 passed / 8 failed / 1 skipped** — 7 failures were a real defect this change introduced: dropped `se`/`c.stats` null guards in `project_detail.html` → 500 on the project page → modal-open timeouts; NOT counted as clean |
| Fix verification at `f2142c81` | 10/10 modal playwright tests passed standalone |
| Completed full-suite batch at `f2142c81` | **899 passed / 1 failed / 1 skipped** (8 m 29 s) |
| Completed full-suite batch at `753c0c0b` | **907 passed / 1 failed / 1 skipped** (10 m 07 s) |

The sole `753c0c0b` failure is also
`test_production_key_auto_loaded` — the same external-issuer-key
blocker; delta vs `f2142c81` = +8, exactly the timezone tests
added since (picker curation/groups/inline + 5 structural +
label-format assertions). The sole `f2142c81` failure is
`test_production_key_auto_loaded` — external licence-issuer
private key absent (`/tmp/to-license-issuer/private.pem`) —
**blocked, not passed**. The 1 skip is the separately
identified skip. Delta vs the `c955c79` batch (871 collected)
= +30, exactly the new timezone tests. The `4a9d8779` defect
and its `f2142c81` fix are recorded as development-cycle
evidence — the fix is not a ledger-only change.

Preview note: the `:39995` disposable instance was restarted
onto `f2142c81` and its `create_all`-style DB gained
`users.timezone` via the migration-equivalent additive ALTER
(the migration itself is Alembic-tested; the instance has no
`alembic_version` table).

### Packaged Linux acceptance — first pass (`f96b645b`)

Candidate artifact built from `cea6b9be` (application code
`753c0c0b` + the `f96b645b` vendored-wheel fix; build tree showed
DIRTY only for that uncommitted fix):
`dist/release/linux/testorchestrator-2.6.0-linux-x86_64.tar.gz`
(200,530,903 B, sha256
`b74a29eae0f0d2c52a8b73584af0fda3ac9b023a5ffc93fa144f05b6416291f4`)
+ `.run` — built with `TO_BUILDBOT_INTERNAL_BUILD=1` (internal
packaging test; the manifest marks it **not approved for
distribution** — GPL redistribution approval stays an explicit
decision).

**Corrected defect found by this build** — `tzdata==2026.6` was
pinned in `requirements.txt` but absent from the vendored
`3rdparty/python-wheels/` set, so the packaged offline
`--no-index` install failed validation (`No matching
distribution`). Fixed in `f96b645b` by vendoring the wheel +
notices entry; the re-run build passed.

| §5b/§4 row | Result |
|---|---|
| Install `.run` → payload/data/config, buildbot provisioned offline, DB migrated to head | **PASS** |
| Linux package zoneinfo: `ZoneInfo('Europe/Budapest')` + `ZoneInfo('Asia/Kolkata')` load | **PASS** — and with `PYTHONTZPATH` pointed at an empty dir (host db unreachable) both zones still resolve → the **bundled** tzdata is proven, not the host db |
| Missing-database degradation: `PYTHONTZPATH`=empty + `tzdata` removed | **PASS** — two explicit `usertz` warnings logged, all output `+00:00`, `all_zones()`→`[]`, picker renders UTC-only; no crash, login path unaffected |
| `toctl backup` → `.tobackup` | **PASS** (36 members) |
| `toctl recover` → scratch dir | **PASS** — DB + `secret.key` restored; `tester` keeps `Asia/Kolkata` + `['pkgp']` (**assignment preservation**); `pkg-git` secret decrypts on the recovered instance (**credential recovery** — key travels in the encrypted payload) |
| Upgrade: real 2.5.1 DB (`/tmp/manual251-data`, alembic `r8s9t0u1v2w3`, no tz column) → packaged `toctl db-upgrade` | **PASS** — all 9 migrations applied to `a2b3c4d5e6f7`; every table count preserved (3 users / 3 executions / 9 results / 1 schedule / 27 audit / 2 secrets / 10 settings); `users.timezone`=UTC; `notified_at` backfilled; `runtime_kind`=`kre`; `/login` 200 on upgraded data |
| Export/logging on the package | **PASS** — audit CSV via the installed app carries `timestamp_utc` (`Z`) + `timestamp_local` + `timezone`; secure-cookie + Referer enforcement intact |
| `flask diag` / `health` / `install-info` | **PASS** (`health` → ok; diag no mismatch) |

Still open on this package: 8-combination execution matrix,
parallel/recovery/security §5 sweep, service-level file-mode/journal
rows — they need the systemd-installed services and run hosts, not
just the payload.

### Status board (updated)

| Area | Status |
|---|---|
| Advanced Analytics Group A | Source-level acceptance closed at `175094f`; time-dependent behaviour re-verified under viewer zones — local-day bucketing covered at `f2142c81`, re-verified at `3b0d6e6e` |
| Advanced Analytics Group B | Implemented; source-level evidence at `c955c79` + zone-aware re-verification at `f2142c81` — **acceptance review still pending; does not close any gate below** |
| Per-user time zones | Implemented — **completed full-suite batch with the known external issuer-key failure; source-level time-zone verification complete** (907 / 1 / 1 at `753c0c0b`, uncombined; the missing issuer key stays an environment-blocked test failure, not a pass). Windows + packaged pending — packaged rows defined in `packaged-acceptance.md` §5b |
| `usertz` fallback hardening | Source tests + **verified on the installed Linux package** (§5b missing-db row: warnings + UTC fallback, no breakage); Windows package verify still pending (W16) |
| Backup and Restore | Implemented; source-tested + **packaged backup→recover verified** (36 members; assignments, timezone and decryptable secrets preserved). Windows gate + portal-staged-restore package sweep outstanding. Settings-only scope |
| Windows W1–W16 | Real-host acceptance outstanding; W16 (zone selection/display/local-day filter/CSV + packaged `zoneinfo` load of Europe/Budapest + Asia/Kolkata) added to the kit — pending real-host execution |
| Clean packaged candidate + final matrix | Partial — first Linux pass recorded above (install, zoneinfo §5b, backup/recover, 2.5.1 upgrade, export); 8-combination matrix + remaining §5 sweep outstanding |
| External licence-issuer-key test | Blocked — missing external private key |

Live `:39998` remains source-run Waitress — not packaged-
candidate evidence. No merge, no publication.

### Package and revision boundaries

`testorchestrator-2.6.0-linux-x86_64.tar.gz` — 200,530,903 B
(~200.5 MB), SHA-256
`b74a29eae0f0d2c52a8b73584af0fda3ac9b023a5ffc93fa144f05b6416291f4`
— built at `f96b645b`. Marked **internal-test, scratch-prefix only,
not a distribution candidate** (built with
`TO_BUILDBOT_INTERNAL_BUILD=1`). `f96b645b` contains the vendored
`tzdata-2026.6` wheel + notices entry — **packaging/build-only, no
application-code change vs `753c0c0b`** (diff = wheel binary,
`3rdparty/licenses/THIRD-PARTY-NOTICES.txt`,
`3rdparty/python-wheels/`). The 907/1/1 batch stays pinned to
`753c0c0b`. The missing wheel was a **corrected build defect**
caught by the build's own offline-install validation.

Commit classification since the tarball: `8aee8735` docs (ledger),
`21ab2963`..`22fee4c5` **code** (scan-driven fixes below). Any
later change makes the `f96b645b` tarball **stale** — the final
candidate must be rebuilt from final head with its own hash, suite
run and revision attribution.

### Upgrade provenance (verified — original untouched)

Source `/tmp/manual251-data/testorchestrator.db` re-inspected after
the packaged upgrade: alembic `r8s9t0u1v2w3`, no `users.timezone`
column, counts identical (3 users / 3 executions / 9 results /
1 schedule / 27 audit / 2 secret_refs / 1 project / 1 suite /
10 settings) — **the packaged upgrade ran on the copy under
`/tmp/to251-upgrade`, not the original**. The migrated copy is at
`a2b3c4d5e6f7` with the timezone column. No running service points
at the copy (`:39998` is source-run on a different DB). No
approval-boundary incident for `/tmp/manual251-data`.

### Packaged portal-restore rows (on the `f96b645b` package)

`toctl recover` is a verbatim file-level restore; the portal
`apply_restore` path (Settings backup) was additionally exercised
on the packaged code against a staged target instance with a real
decrypted payload (4 users / 1 project / 1 runner / 2 schedules /
api token / 4 secret_refs, `replace` mode, actor `admin`):

| Row | Result |
|---|---|
| Roles + memberships preserved | **PASS** — `tester`→`TESTER`+`Asia/Kolkata`+`['pkgp']`; `manager`/`po`/`Admin` roles intact |
| Sessions invalidated | **PASS** — every user's `session_version` incremented (prior sessions die on next request) |
| API/submit tokens revoked | **PASS** — `ci` token `revoked_at` set; target's live token dropped in replace mode; 0 submit tokens resurrected |
| Runners need re-verification | **PASS** — `health=unknown`, `check_status=pending`, `check_at=None`, `check_error=""` |
| Schedules safe-rearmed | **PASS** — past single-fire `past-sched` **disabled** + attention note; future interval `fut-sched` stays enabled |
| Interrupted restore → usable config | **PASS** — corrupted payload (duplicate username → mid-transaction IntegrityError) rolled back atomically; prior config identical before/after, still usable |

Still open: **clean reinstall from `.run` → restore → login**
(`toctl backup→recover`/`apply_restore` are not a clean reinstall);
8-combination matrix; §5 packaged security sweep; service-level
file-mode/journal rows (need a systemd-installed service —
**approval required**, not installed).

### Packaged exports (on the `f96b645b` package)

| Row | Result |
|---|---|
| Audit CSV | **PASS** — `timestamp_utc`/`timestamp_local`/`timezone` (prior pass) |
| Operational-logs CSV | **PASS** — `200`, `testorchestrator-operational-…-inline.csv`, `timestamp_utc` column family |
| Analytics CSVs ×5 | **PASS** — `activity`/`project_outcomes`/`first_final`/`queue_wait`/`turnaround` all 200, each appending the `tz` column |

### Source-analysis scans (read-only, at `8aee8735`)

Isolated tool dir `/tmp/scantools` (not the project runtime):
`vulture==2.14`, `bandit==1.8.3`, `pip-audit==2.9.0` (OSV backend),
`jscpd@4.0.5` (npx). Scope: first-party Python (`testorchestrator/`),
`tests/` separately, `testorchestrator/static/js/`, templates.
Excluded: `static/vendor/plotly.min.js`, `3rdparty/`, generated
files, `migrations/` boilerplate, installer payloads.

**Vulture** — 365 raw → 204 after `ignore_decorators` (routes, CLI,
filters, fixtures, errorhandlers) → whitelist module
`build-scripts/vulture_whitelist.py` (each group commented with its
consumer); `--min-confidence` left at default. Dynamic lookups
(`getattr` with built names — `ParsedRun` tuple reads, WTForms
`validate_<field>`, flask `from_object`) checked by hand.

**Triage table:**

| ID | Tool/rule/ver | Location | Sev/conf | As reported | Classification | Action |
|---|---|---|---|---|---|---|
| VULT-1 | vulture unreachable-code 2.14 | secrets_store.py:215 | 100% | `return True` after `return` | Real defect | fixed `21ab2963` |
| VULT-2 | unused import | dispatch.py:2700 | 90% | `import shutil as _sh` | Real dead code | fixed `eedc0f83` |
| VULT-3 | unused param | charts.py:437 | 100% | `stale_days` never used | Real dead code | fixed `7d8dd677` (+caller) |
| VULT-4 | unused var | charts.py:358 | 60% | `dname` loop var | Real dead code | fixed `fb43469f` |
| VULT-5 | unused var | logexport.py:287 | 60% | `live_names` set | Real dead code | fixed `00d49aff` |
| VULT-6 | unused func | main/routes.py:432 | 60% | `forbidden` — **missing `@app_errorhandler(403)`** | **Real defect** (403s got default page) | fixed `1fb43c8e` + test `test_ab05_403_renders_error_template` |
| VULT-7 | unused func | dispatch.py:996 | 60% | `procs_within_budget` | Dead — same rule enforced atomically in `_assign_runner` CAS | fixed `da1862d1`+`236c6608` |
| VULT-8 | unused func | network.py:91 | 60% | `port_available` | Dead | fixed `176062f7` |
| VULT-9/10 | unused class | buildbot.py:49, buildbot_cfg.py:31 | 60% | `SubmissionLost`, `BuildbotConfigError` | Dead — never raised/caught | fixed `61e0ea15` |
| VULT-11 | unused func | charts.py:84 | 60% | `palette()` | Dead | fixed `dc963183` |
| VULT-12/13 | unused | portal/forms.py:48, readiness.py:253 | 60% | `PlanForm`, `blockers()` | Dead | fixed `762e9452` |
| VULT-14..18 | unused const | reporting/results/dashboard/dispatch/kre.py | 60% | 5 module constants | Dead | fixed `c9e8f9e6` (+`alg2`→`_alg2`) |
| VULT-19 | unused func | usertz.py:203 | 60% | `local_day` | Dead — superseded | fixed `633b3c2b` |
| ASSET-1/2 | manual scan | plan_detail.html, it-space-logo.placeholder.svg | — | orphaned template + dev asset | Dead — zero refs by name/string/template | removed `ffbdb60c` |
| DEFER-1 | vulture | buildbot.py adapter methods ×3 | 60% | `worker_connected`/`reconfig_pidfile`/`dispatcher_builder_name` | Deferred — documented adapter API surface; zero in-repo callers but removal is an integration-contract decision | whitelisted w/ reason |
| DEFER-2 | vulture | adapters/updater.py | 60% | `NotConfiguredError`/`Adapter` | Deferred — deliberate 17-line placeholder seam, no importers | whitelisted w/ reason |
| FP-* | vulture | ~200 entries | 60% | routes/CLI/forms/ORM cols/config attrs/listener args | False positive — framework-registered or serialized | whitelist groups documented |
| SEC-1 | bandit B202 1.8.3 | updater.py:255 | **High/High** | `tarfile.extractall` | **False positive** — custom filter rewrites links then delegates to `tarfile.data_filter` (rejects traversal/absolute); member names validated | documented; no change |
| SEC-2 | bandit B601 | ssh_check.py:158,178 | Med/Med | paramiko `exec_command` | **Real defect** — `{x!r}` repr is not a shell escape (both-quote strings break/inject); admin-config values only | fixed `759eaa5d` → `shlex.quote` + test `test_workdir_with_quotes_survives_quoting` |
| SEC-3 | bandit B314 ×9 | authoring/gitsync/results/runner_readiness XML | Med | ElementTree untrusted parse | Accepted risk — JUnit XML arrives from the runner trust boundary (same actor can already run test code); no external-entity resolution in stdlib ET; defusedxml recommended future hardening | deferred, owner: hardening pass |
| SEC-4 | bandit B104 | frontend.py:225 | Med | bind `::`/`0.0.0.0` | Accepted — Cheroot IS the public frontend; Waitress stays loopback-only by design | none |
| SEC-5 | bandit B105/107/110/310/404/603/607 | misc | Low | hardcoded 'Admin'/'' pw, try-except-pass, urlopen, subprocess | FP/accepted — usernames not passwords; subprocess list-form args; CLI-local urlopen | none |
| DEP-1 | pip-audit OSV | paramiko 2.12.0 | High | PYSEC-2026-1758 / CVE-2023-48795 Terrapin | **Real** — SSH transport prefix-truncation on agentless path | **fixed** `22fee4c5` → paramiko 3.5.1 (pin+wheel); 10 SSH tests pass |
| DEP-2 | pip-audit OSV | paramiko | Med | PYSEC-2026-2858 / CVE-2026-44405 SHA-1 RSA | Accepted risk — no upstream fix yet; pinned fingerprints + publickey auth bound exposure | deferred to upstream fix |
| DEP-3/4 | pip-audit OSV | buildbot 4.3.0 | Low | GHSA-jqqh/mj3x (CVE-2009-2959/2967 XSS) | **False positive** — 2009 advisories fixed ≥0.7.11; 4.3.0 unaffected (OSV range mislabel) | none |
| JS-1 | manual | plotly.min.js v3.3.0 | — | bundled version | CVE-2023-46308 affects <2.25.2 only (not affected); #8168 proto-pollution fixed upstream in 4.3.0 — accepted risk, figures are app-generated not user-supplied | noted |

**jscpd baseline** (token-based, `jscpd@4.0.5`, defaults):
app Python 62 files — 11 clones, 0.68% lines / 1.02% tokens;
tests 84 files — 83 clones, 3.19% / 4.36%;
templates 50 files — 29 clones, 4.23% / 3.66%;
JS 10 files — 7 clones, 11.49% / 11.32%.
Baseline recorded, not a zero-clone target. Security-ranked:
**pytestfw↔robotfw↔nodefw counting/normalization clones** are the
top risk (counting-policy duplication that can drift — deferred as
ordinary refactor; adapters are parallel implementations);
execution.py column blocks are structural ORM noise; JS clones are
dashboard↔project analytics rendering (no authz); template clones
are form markup. No authorization/redaction/escaping clones found.

Scan limits: vulture can't see framework/dynamic refs (whitelisted
above); bandit flags patterns not exploitability; pip-audit covers
Python deps only (Plotly handled manually); no claim of
vulnerability-free or dead-code-free code.

### Manual security review notes (this-cycle additions)

- Runner command construction: dispatch SSH path uses
  `shlex.quote` (`qwd`); ssh_check repr-quoting now fixed (SEC-2).
- Backup/restore extraction: `apply_restore` payload uses
  `_restore_filter`→`data_filter` containment (SEC-1 verified safe).
- Authorization on new routes: analytics CSV gated by
  `project_allowed` scope (existing); op-logs export ADMIN-only;
  `forbidden` 403 handler now actually registered (VULT-6).
- Secrets: log/export redaction unchanged; backup payload excludes
  sessions/tokens — verified on the package (rows above).
- Session/cookie: secure cookies + Referer enforcement verified on
  the packaged instance.

### Post-scan candidate results

**Full suite at `22fee4c5` (scan-fix head): 911 passed / 1 failed /
1 skipped** (9m55s), uncombined — sole failure remains
`test_production_key_auto_loaded` (missing external issuer key —
environment-blocked, not a pass). Delta vs `753c0c0b`'s 907 = +4 =
exactly the scan-fix tests (3-role `test_ab05_403_renders_error_template`
+ `test_workdir_with_quotes_survives_quoting`).

**Final internal-test candidate:** built at `22fee4c5` (working tree
contained the not-yet-committed wheel+whitelist+ledger; committed
identically at `53a0808e`):
`testorchestrator-2.6.0-linux-x86_64.tar.gz` — 201,043,529 B,
SHA-256 `ab07227ac3274c5069e0ae85f3198b0e943f6b3f901623417b6b7abd991fa1ba`;
`.run` SHA-256 `7e0660d6f65d9da7c0caa69aa4dc69cc8705bb631e7aa2883ad6d93509522952`.
Still internal-test, scratch-prefix only. Extracted check: package
carries `paramiko-3.5.1` wheel + pin and `tzdata-2026.6` wheel.

**Scans re-run at final head:** Vulture clean (all real findings
fixed; only whitelisted/deferred groups remain); Bandit — ssh_check
now `shlex.quote`'d (B601 pattern still reported, sanitization
verified manually — Bandit cannot see it); pip-audit — **Terrapin
cleared by paramiko 3.5.1**; residuals = 2× 2009-Buildbot FPs +
PYSEC-2026-2858 (no upstream fix, accepted).
