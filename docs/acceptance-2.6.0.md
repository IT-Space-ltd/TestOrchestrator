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

### Clarifications on the post-scan candidate

**Revision gap — none.** `22fee4c5..bcd98319` contains zero
application-code changes (`git diff --name-only`: only
`paramiko-3.5.1` wheel, `build-scripts/vulture_whitelist.py`,
`docs/acceptance-2.6.0.md`). The 911/1/1 suite and the tarball
cover head `bcd98319`'s application code exactly. Scan re-runs
covered the working tree at that application code.

**Scan re-runs at final head — full set:** Bandit 1.8.3 re-run:
104 issues, sole High remains B202 tarfile (documented FP —
`data_filter` delegation verified); the two ssh_check B601 remain
pattern-reported (Bandit cannot see `shlex.quote` sanitization —
verified manually). jscpd re-run: app Python unchanged — 11 clones,
104 lines / 1403 tokens (1.02%). Vulture whitelist =
`build-scripts/vulture_whitelist.py`, 88 lines / 58 entries, each
group commented with its consumer; "clean" = every remaining
finding maps to a whitelist group or a deferred row in the table.

**`shlex.quote` POSIX scope — correct as-is.** The agentless SSH
code path serves **Linux targets only** (`to_ssh_exec.py` runs a
POSIX `run.sh`; `ssh_workdir` is `/`-separated; the 8-combination
matrix has a "Linux SSH target" column and **no Windows-SSH cell** —
Windows targets are PB workers only, whose `npx.cmd`/`npm.cmd`
selection lives on the non-SSH `node_exec_spec` path). Quoting
verified on real `/bin/sh`: 11 hostile workdir strings (spaces,
`'`, `"`, both-quote mix, `$HOME`, backticks, `$(…)`, `;`, newline,
`*`, `&`) — every one materialized as the exact literal directory,
no expansion/splitting.

**403 handler — recorded as a user-visible fix.** Behavior change:
requests that previously got Flask's default HTML 403 page now get
`error.html` (same status code). API clients unaffected —
`api_bp.errorhandler(HTTPException)` takes blueprint precedence and
returns the JSON error envelope (new test
`test_api_403_stays_json_envelope` proves status+JSON body+no HTML).
No route relied on the old default page — `abort(403)` sites only
assert status codes in existing tests; error.html is a static
generic template (code + generic message, no internals, no
Traceback).

**Real SSH transport check (packaged paramiko 3.5.1).** Real TCP
session: `Transport` → `start_client` → host-key verify against the
server's pinned key → `auth_publickey` → `exec_command` → SFTP
write/read — repeated for OpenSSH-format **rsa-2048, ed25519 and
ecdsa-256** client keys; all pass. Server side is paramiko (test
fixture) — **an OpenSSH-server interop check needs a real sshd;
none is installed on this host and no docker daemon exists** —
recorded as the residual gap. SHA-1 RSA acceptance recorded with
its exact condition: paramiko 3.5.1 still negotiates `ssh-rsa`
(SHA-1) signatures; in this codebase exposure is bounded because
the client only authenticates to hosts whose **pinned** fingerprint
is pre-verified (`ssh_host_key_fingerprint`) and auth is
publickey-only — but the SHA-1 capability itself is upstream and
unfixed (PYSEC-2026-2858, no fix version).

### Packaged full suite — final candidate

`pytest tests/` with `PYTHONPATH` pointed at the extracted
`testorchestrator-2.6.0-linux-x86_64` package (imports verified to
resolve to the packaged copy): **912 passed / 1 failed / 1 skipped**
(9m52s), uncombined — sole failure remains the external issuer-key
blocker. The +1 vs the source-run 911 is the newly added
`test_api_403_stays_json_envelope`.

**Still open:** `.run` clean-install→restore→login (installer
targets `/opt` — needs root, same approval boundary as the systemd
rows; proposal recorded in `packaged-acceptance.md`); Linux-only
matrix rows + §5 packaged sweep (need the installed running stack —
same `.run`/service boundary); Windows W1–W16; issuer key; Group B
review.

## 2026-xx follow-up: corrections, tray indicator, remaining boundaries

### Installer-mode reconciliation (was: ".run blocked")

`install.py` accepts `--payload` (default `/opt/testorchestrator`),
`--data`, `--config`, `--https-port`, `--http-port`,
`--no-service-start`. Two real modes:

| Mode | Requirement | Rows |
|---|---|---|
| Non-root scratch prefix (`--payload /tmp/… --no-service-start`) | none — verified: `.run` installed to `/tmp/to26-final-inst` non-root, provisioned Buildbot, generated `web.env`, migrated DB | clean-install→restore→login (app-level rows runnable non-root) |
| `/opt` + systemd units | root + a service manager | `/opt` install, unit lifecycle, journal, service-user file modes — **blocked on systemd-capable environment** |

"Blocked" now only marks the root/service-manager/Windows-host
boundary. The earlier claim that the whole `.run` path was blocked
was too broad — corrected.

### Run labeling

- **911 / 1 / 1** — source-tree suite at `22fee4c5`.
- **912 / 1 / 1** — extracted-package `PYTHONPATH` run at
  `22fee4c5` application code (NOT an installed-app run). The +1 is
  `test_api_403_stays_json_envelope` — test code, no application-
  code gap. The 1 failure in both runs is the blocked
  production-issuer-key test — not a pass. Tallies kept separate.

### PYSEC-2026-2858 triage

Package `paramiko==3.5.1` (vendored wheel). Advisory: SHA-1
`ssh-rsa` signature support remains reachable (upstream has no
fixed release as of this record). Classification: **accepted
risk**, bounded by: (a) agentless SSH authenticates with pinned
host keys and publickey-only auth — no `ssh-rsa` user-key path is
exercised by `to_ssh_exec.py`; (b) exposure requires a target
that insists on `ssh-rsa` host signatures, which `ssh_check.py`
does not prefer. Re-check on next paramiko release. NOT a clean
dependency-scan result.

### License test-keypair finding — trust route absent

`licensing.py` trusts keys only via `_load_production_key()`
(reads `release/licence_pubkey.pem` beside the package) and
`register_key(key_id, pem)` — an **in-process** test hook used by
`tests/test_licence_enforcement.py`. No configuration or
environment route exists to make a *running packaged install*
trust a test issuer key without editing the shipped key file.

Per the instruction ("do not add a bypass; ask first"), the
packaged-install license cases are **blocked on a decision**:
either a documented test-only trust route is approved and added,
or the packaged rows stay blocked and only in-process coverage
(the existing 40+ license tests) stands. In-process cases already
covered by the suite: valid/expired/not-yet-valid, tampered char /
payload / signature, wrong `key_id`, malformed, missing fields —
all with `key_id="test"`.

Production-issuer test stays blocked on the legitimate external
key; OrchGenerator (external) not invoked.

### Disposable systemd environment — blocked on tooling

Approved environment cannot be created on this host: **no
systemd-capable runtime exists** — `systemd-nspawn`, `debootstrap`,
`qemu-system`, `lxc`, `podman`, `docker`, `machinectl` all absent.
Installing any of them is itself a host-level change outside the
approved scope. The plan is written in
`docs/packaged-acceptance.md` and ready to execute the moment a
VM/container tool is provided (or an external disposable host).

### Worker tray status indicator — implemented

`5611dc8a`: `packaging/windows/bb-worker-payload-src/worker-tray.py`
(pystray + PIL, Windows-only — no Linux tray exists). Design note:
"running" = the `TestOrchestratorBuildbotWorker` scheduled task
reports Running (process alive; explicitly not master-connectivity).
Unknown/error → red + "status check failed" tooltip, never green,
never crashes. Daemon thread polls `schtasks` every 2 s, updates
icon/title/menu only on change. Dot ≈¼ icon width, bottom-right,
thin white outline; base artwork untouched; no new dependencies.

Tests: `tests/test_worker_tray.py` — 20 display-free cases,
16/20/24/32/48 px, both states, transitions, unknown/error, dot
bounds + outline + untouched corners — all pass. Real-host rows
added: **W17** (tray states/themes/DPI + screenshots), **W18**
(licensing on Windows). Docs: Admin-Manual §6.1 + CHANGELOG.

### `.run` non-root install → restore → login — PASS

On `/tmp/to26-final-inst` (`--payload` scratch prefix, `--no-service-start`,
non-root): install provisioned Buildbot + `web.env` + migrated DB;
app bound `:38445` (Cheroot) + `:8080` loopback (Waitress — stale
`/tmp/to251d` instance stopped to free the loopback port). Seeded
`restore-admin`, `create_backup` → wiped user → `apply_restore`
replace mode → user restored with password intact → HTTPS
`/login` 302→`/` 200. Old `/tmp/test-backup.tobackup` passphrase
unknown — cycle used a fresh backup instead; format identical.

§5 live-instance membership/RBAC spot-checks: suite-backed items
(`tests/test_project_access.py` 17 tests) covered by the packaged
912-run; interactive two-project live verification pending the
final candidate.

### Post-tray head — fresh verification cycle (5611dc8a…37b10cf2)

- Full suite at `37b10cf2`: **932 passed / 1 failed / 1 skipped**
  (932 = 911 + 1 API-403 + 20 tray tests). Sole failure =
  `test_production_key_auto_loaded` — external issuer-key blocker,
  not a pass. Kept separate from the 911 and 912 runs.
- Rebuilt internal-test candidate at `37b10cf2`:
  tarball 201,047,132 B sha256
  `917e35eee15c34bc63e30b40430181d15f922df27b9a87ac82579e754e2fca22`;
  `.run` 201,049,136 B sha256
  `62f7531233e7af5b3822f2ff6bfd85b2755c4ac6f34881358e501c3e2d1d6ff4`.
  Supersedes `ab07227a…1ba` (stale for final claims).
- Scans re-run at `37b10cf2`: Vulture — 0 non-ORM findings (128
  residual = documented dynamic ORM-column reads; 4 framework
  callbacks added to whitelist, now 62 entries); Bandit — 104
  (same triage: B202 FP, 2×B601 pattern-flagged with `shlex.quote`
  verified); pip-audit — 3 residuals (2× Buildbot 2009 FPs +
  PYSEC-2026-2858 accepted-risk); jscpd — 11 clones / 1.02% tokens.

### License rows — test-keyed scratch install (decision 1)

Method per instruction: copy of `/tmp/to26-final-inst` →
`/tmp/to26-lickey`; shipped `licence_pubkey.pem` (sha256
`213b2896…3eba`) replaced with a throwaway Ed25519 test public key;
private key lived in `/tmp/to-test-issuer/` only (outside repo and
package) and was **deleted** with the scratch copy afterward.
Codes minted `TO1` format, `key_id="prod"`, real Ed25519
signatures. Results labeled **test-keyed scratch install** — they
do not prove the production key path.

| Row | Result |
|---|---|
| Valid key | PASS — activated; stored row shows `licence_id`, `customer` (holder), `valid_from`/`valid_until`; audit logs id+customer only |
| Expired key | **Accepted, then classified** — `add()` stores it ("Licence activated… valid 2020→2021"); `status()` reports expired. Not a rejection — renewal-window design stores history; licence is informational (§12.4) |
| Not-yet-valid key | Same — stored, `status()` classifies `not-yet-valid` |
| Tampered: one char changed | PASS — `malformed code` (base64 decode fails) |
| Tampered: payload edited | PASS — `invalid signature` |
| Tampered: signature replaced | PASS — `invalid signature` |
| Wrong issuer key | PASS — `invalid signature` (fresh Ed25519 pair) |
| Missing field (`customer=""`) | PASS — `missing customer` |
| Empty/garbage code | PASS — `malformed code`, no crash |
| Licence survives backup→restore | PASS — stored row + code identical after `apply_restore` (`licences` is settings-scoped) |
| Secrets in logs/exports | PASS — no private-key material in stored rows; activation audit logs id+customer only |
| Enforced limits | N/A — licence is informational, gates nothing by design |
| Private key hygiene | Deleted; never in repo/package/logs |

**Spec-vs-code difference reported:** "expired key rejected" —
actual behavior is *accepted into the store and classified
expired/not-yet-valid* by `status()`; activation messaging reflects
the declared window. Same for not-yet-valid (future renewals are
intentionally storable). The production-issuer row remains blocked
on the legitimate key.

### Confirmations requested

- Candidate `917e35ee…ca22` app code = `37b10cf2`;
  `git diff 37b10cf2..aee96d87` = `docs/acceptance-2.6.0.md` only
  (ledger). Tray fix `a9d3d942` + docs `8fe6476b` postdate the
  build → **Windows-side tray payload code in the candidate is
  stale by one commit** (tooltip text); Linux tarball unaffected by
  docs but flagged honestly — Windows package rebuild owed.
- Tray deps: `pystray` + `pillow` **already shipped** in the
  Windows worker payload (`build-scripts/_common.py:319`) — no new
  dependencies added. "Running" = process alive; a live-but-
  disconnected worker shows green — limitation stated in §6.1
  manual text and tooltip claims process state only (`— Running`
  / `— Not running`), never connectivity.

### D1–D5 records

**D1 — tray tooltip coverage.** `test_tooltip_text_per_state`
(asserts "Running"/"Not running"/"status check failed" per state
and that "connected" never appears) + `test_status_text_and_
unknown_is_red` — both in `tests/test_worker_tray.py`. Covered by
the 21-test targeted run at `a9d3d942`; the 932/1/1 full-suite run
predates `a9d3d942`, so full-suite coverage of the tooltip fix is
owed at F3 (recorded, not assumed).

**D2 — how the API key reaches KRE.** Only mechanism: `-apiKey=`
argv (vendor-documented; `docs/integration-contracts.md` already
records this as residual exposure). No vendor-supported env/file
alternative confirmed; `run_invocation` has an `env_extra`
injection seam if one emerges. Standalone tests used argv
(`tests/test_pipeline.py:523-538` asserts `-apiKey=FAKEKEY-…` in
child argv and `***REDACTED***` in logs). Exposure: key visible in
child argv to same-UID users (`/proc/<pid>/cmdline`, `ps`) for
process lifetime — never in logs/artifacts/audit/exports/UI.
§6.9 now carries the exposure + host-hygiene recommendations.

**D4 — expired/not-yet-valid behaviour.** Documented in Admin
Manual §12.4: accepted at activation (signature+format validated,
not the window), stored as history, classified by `status()`;
UI shows `expired`/`not-yet-valid`; at expiry the login-page
notice reappears; nothing gated. Marked current design pending
owner confirmation. No code change.

**D5 — run/revision ledger (uncombined):**

| Run | Where | Revision | Tally | Failure |
|---|---|---|---|---|
| Suite | source tree | `22fee4c5` | 911/1/1 | issuer-key (external) |
| Suite | extracted pkg PYTHONPATH | `22fee4c5` app code | 912/1/1 | issuer-key |
| Suite | source tree | `37b10cf2` | 932/1/1 | issuer-key |
| Tray targeted | source tree | `5611dc8a` | 20/0 | — |
| Tray targeted | source tree | `a9d3d942` | 21/0 | — |

| Tarball | Built at | Status |
|---|---|---|
| `b74a29ea…f4` (200,530,903 B) | `f96b645b` | stale — pre-tray, internal-test only |
| `ab07227a…1ba` (201,043,529 B) | `22fee4c5` | stale — pre-tray |
| `917e35ee…ca22` (201,047,132 B) | `37b10cf2` | current Linux candidate; Windows tray payload inside predates `a9d3d942` — Windows rebuild owed at F2 |

## Final candidate — F1–F6 (frozen head `8c14b9d0`)

**F1 freeze.** Last application-code change = `a9d3d942` (tray
tooltip). Everything after = docs/ledger. Frozen head `8c14b9d0`.

**F2 artifacts (all internal-test, unsigned where applicable):**

| Artifact | Bytes | SHA-256 |
|---|---|---|
| linux tarball | 201,054,308 | `3881cbb225d991eb5761596036fe01844c0fa68fc4aaa784300e43230efab1e4` |
| linux `.run` | 201,056,312 | `8cb6b8162502de60b3a9eded599f0c866b46ca0d2b7f79780bb3eefb595f812b` |
| windows setup (UNSIGNED) | 115,931,700 | `941608f547c9072fc94c2806400ce4ff79a45bf98d38a25d6f729ae6bb8840c0` |
| Buildbot sources | 4,708,367 | `5d4f87d7eb65ba158e7f8fddf1b791af5a4b721d16d0e9bebfd1cc88e578305c` |

Windows build note: first attempt raced the NSIS output vs the
staging glob — clean retry succeeded; artifact carries the
`a9d3d942` tray code. W1–W18 kit (`docs/windows-acceptance-kit.md`)
hands over with the Windows payload — **run by the product owner**.

**F3 suite at `8c14b9d0`: 933 passed / 1 failed / 1 skipped**
(932+1 = `test_tooltip_text_per_state`). The 1 failure =
`test_production_key_auto_loaded` — **blocked** on the legitimate
external issuer key, not a product failure.

**F4 scans at `8c14b9d0`:** Vulture 0 non-ORM findings (128
dynamic-attr residuals, whitelisted classes); Bandit 104 (same
triage: B202 FP, 2×B601 pattern-only); jscpd 11 clones/1.02%;
pip-audit unchanged (deps frozen since `22fee4c5` — paramiko
3.5.1 triage stands). All same as recorded — no new findings.

**F5 stale marks:** `b74a29ea…f4` (f96b645b), `ab07227a…1ba`
(22fee4c5), `917e35ee…ca22` (37b10cf2) — all stale; superseded by
`3881cbb2…b1e4` at `8c14b9d0`.

**F6 consolidated gate table:**

| Row | Status | Boundary |
|---|---|---|
| Linux package (scratch prefix, install→restore→login) | PASS | — |
| Full suite at frozen head | 933/1/1 | 1 = issuer-key blocker |
| Scans at frozen head | Same triage | — |
| Tray dot source + 21 unit tests | PASS at `a9d3d942` | — |
| Admin docs: KRE licensing §6.9, §12.4 licence behaviour, argv exposure | PASS (docs) | — |
| License flow (test-keyed scratch) | PASS — expired/future accepted-then-classified (documented §12.4) | prod key path unproven by design |
| `systemd-analyze verify` ×5 units | PASS | — |
| User-level service lifecycle + journal (VM8 fallback) | PASS | system-level rows remain |
| V1–V9 system-level rows (`/opt` install, units, modes, journal, reinstall, upgrade, OpenSSH, §5, matrix, installed-package suite) | **BLOCKED** | no VM tool + RAM 3.6G<4G; awaits owner confirmation to `snap install multipass` (host changes listed) |
| W1–W18 (Windows host) | **Run by the product owner** | real Windows host |
| Production issuer-key test | **BLOCKED** | legitimate external key |
| Expired-licence behaviour decision | Pending owner | §12.4 documents current design |
| Group B acceptance review | Pending owner | — |

### F-cycle correction — true frozen head `192dbc12`

Commit-order correction to the F-section above: the `install.py`
service-user fix (`192dbc12`) was committed AFTER `25f2cfe8`, so the
real frozen head is **`192dbc12`**. Two interim builds ran on the
`8c14b9d0` working tree *with* the uncommitted fix (dirty flag) —
their artifacts `3881cbb2…b1e4` / `8cb6b816…812b` /
`941608f5…40c0` are correct-content but wrong-provenance and are
**stale**.

Rebuilt cleanly at `192dbc12`:

| Artifact | Bytes | SHA-256 |
|---|---|---|
| linux tarball | 201,055,155 | `124b5567ae0d0719c80781d8ed68f7499c8e8ab6a1e7c2e755ddaaa2976ee0fe` |
| linux `.run` | 201,057,159 | `d4e3e5ee2d6f726ab1967d5f2be3ed30999485223ce342b9de8fa58835d5c543` |
| windows setup (UNSIGNED) | 115,931,700 | `941608f547c9072fc94c2806400ce4ff79a45bf98d38a25d6f729ae6bb8840c0` (rebuilt at `192dbc12`) |
| Buildbot sources | 4,708,345 | `347550aa843b2c65c8893fd54160d84fa93c193352c0316617bae9b211812d12` |

F3 note: the 933/1/1 suite ran at `8c14b9d0`;
`git diff 8c14b9d0..192dbc12 -- testorchestrator/ tests/` is **empty**
— suite-covered code identical; `scripts/install.py` is not
pytest-covered and is exercised end-to-end by the VM V1 row on the
`124b5567` tarball.

## VM e2e acceptance — `to-accept` (Multipass, Ubuntu 26.04.1, disposable)

Package: `testorchestrator-2.6.0-linux-x86_64.run` sha256 `df6b2d22…f53`
(tarball `76179316…`); head `64879207` (install.py + build_bundle fixes).
VM restored to `to-accept.baseline` before install.

### Install + services (real root `/opt` install, first PASS after two defect fixes)
- V1 install → `/opt`: **PASS** — all 5 units active+enabled;
  `testorchestrator` user created by installer (uid 999).
- V2 lifecycle: stop→inactive, start→active, restart→active,
  kill -9 → auto-restart ~4 s → portal 200: **PASS**.
- V3 modes: `/var/lib/testorchestrator` 755 to:to; `secret.key` 600;
  `web.env` 640; `certs/` 700; `release.json` 644 (post-fix): **PASS**.
- V4 journal: lifecycle lines present, zero secret/apiKey strings: **PASS**.
- Portal: HTTPS :443 → 200; HTTP :8080 → 301 to HTTPS.

### Worker + framework e2e (real Buildbot PB, real systemd worker)
- `install_linux_worker.sh` from shipped worker tarball
  (`TestOrchestrator-Buildbot-Worker-4.3.0-linux-x86_64.tar.gz`,
  offline wheels + get-pip fallback): **PASS** — venv, `buildbot.tac`,
  `to-buildbot-worker` unit enabled+started, PB attach confirmed in
  master log (`bb-vm-worker attached to to-target-…`).
- worker + KRE (fake katalonc → JUnit; credential via worker-local
  `credential_file`, `credential_ref` correctly rejected for remote):
  execution `0c132764` → **completed**.
- worker + Robot Framework (**real** robotframework 7.5.1 in worker
  venv, real `.robot` case): execution `e0bede36` → **completed**.
- worker + Cypress (fake `npx` → JUnit): execution `d11100bc` → **completed**.
- worker + Playwright (fake `npx` → JUnit; needs sibling `npm` for the
  `npm ci` deps step — real node supplies it): `a0ab61f3` → **completed**.

### Agentless SSH + KRE — DEFECT FOUND (reproducible 3/3)
- Host-key pinning verified: `TO-SSH: host key verified SHA256:o8/M…`
  on the real OpenSSH_10.2p1 sshd.
- BUT the staged `source.tar` (`buildbot/staging/<eid>.tar`) is
  present ~1.8 s after dispatch and **gone before the dispatcher's
  `sftp.put` at ~2.5 s** → `to_ssh_exec` FileNotFoundError → run goes
  UNKNOWN with reservations retained (safe reconciliation path, no
  silent rerun — correct failure semantics).
- Executions `ec0394ea`, `28a5e8b7`, `347abc8e` all hit it.
- Root cause not yet pinned; likely a staging lifecycle race
  (`clear_staging` is only called at finalize + readiness — suspect a
  reconcile path). **Real defect — needs fix + retest.**

### Notes / boundaries
- bb-wheels cover cp310–cp312 only; VM's system python3 is 3.14 →
  worker install needs a 3.10–3.12 interpreter (used uv-installed
  CPython 3.12.16). Script floors at 3.10 with **no ceiling** — on
  3.13+ hosts offline install fails mid-way. Finding for docs or a
  version ceiling.
- Bundled `python-runtime` is fixed-prefix — cannot create venvs
  (expected; it is the app runtime, not a general interpreter).
- UNKNOWN executions hold runner slots until reconciled (by design —
  verified: second SSH run queued on `capacity: job slots full 1/1`).
- Fake runtimes (katalonc/npx) validate orchestration + collection;
  real framework binaries remain product-owner acceptance scope.

## Root-cause correction — SSH+KRE "staged-tar loss" (was misdiagnosed)

Deeper tracing on the VM showed the earlier hypothesis was wrong: the
tar was deleted by *normal* `_collect_buildbot` → `clear_staging`
finalization at ~3.9 s — AFTER the build had already failed. The real
exec-time failure was `to_ssh_exec` rc=2 with remote-side
`FileNotFoundError` (no local path — the paramiko SFTP signature).

Actual defects found and fixed (`00627ec3`, `b1a8a7ec`):

1. **Remote workdir not creatable** — fixture `/tmp/to-ssh` was
   root-owned; `mkdir -p <workdir>` failed but `_prepare` ignored the
   exec rc, surfacing only an opaque sftp.put failure. Fix: mkdir +
   write-probe up front → actionable `RuntimeError` naming the workdir
   and SSH user. Regression tests: unwritable + existing-read-only
   workdir (tests/test_ssh_dispatch.py).
2. **Cred wrapper never staged** — `credential_file` runs invoke
   `remote_cred_wrapper` default `/tmp/kre_cred_exec.py`, which nothing
   installed on the remote → run.sh exit 127. Fix: `_prepare` sftp-stages
   the bundled `kre_cred_exec.py` into the run dir (explicit
   `remote_cred_wrapper` still honored, not overwritten). Tests: staged
   + scrubbing, explicit-path honored.
3. **Stale staging leak** — pre-dispatch `_fail` paths (credential
   gates, version gates) left `<eid>.tar`/`.cred` forever. Fix: clear
   staging on post-submit terminal state + terminal-owner sweep in
   `reconcile_buildbot_runs` (live DISPATCHED/QUEUED tars untouched).
   Tests: pre-dispatch fail clears, sweep keeps live.
4. **Worker installer python ceiling** — `>=3.10` floor only, bundled
   wheels cp39–cp312 → py3.13/3.14 hosts failed mid-install (VM hit on
   system python 3.14.4). Fix: derive supported range from wheel ABI
   tags, refuse up front with the range + found version; `--online`
   warns only. Tests: 4 cases incl. stub-versioned python3.
5. **buildbot-venv interpreter symlink into extraction dir** —
   install.py created the venv with `sys.executable` = the .run
   `/tmp/to-install-*` python, deleted after install → master dies
   203/EXEC on first restart (services only LOOKED healthy — the
   restart was never exercised). Fix: `create_buildbot_venv_offline`
   bases on `bundled_python(payload)`. Tests: interpreter-base contract.

Fixture defects corrected (not product): `/tmp/to-ssh` ownership,
fake-katalonc ignoring `-reportFolder`, missing `npm` sibling to fake
`npx`, robot venv pointing at system 3.14 (real venv on CPython 3.12.16
via uv), vm-setup.sh ordering (project tree before optional steps).

## VM e2e acceptance RERUN — head `b1a8a7ec`, package `63f991ab…7d37`

`.run` sha256 `63f991abe2ae1185607f81ecee1644331de9e874a78d532ba2faf33f8cf87d37`
(tarball `a39cf1a9…347f`), internal-test build `b1a8a7ec`.
Fresh baseline restore → install → full matrix:

- `/opt` install + all 5 units active+enabled; service user created;
  modes correct (`secret.key` 600, `web.env` 640, `release.json` 644).
- **Master + worker restart after install: all units active** —
  venv-symlink fix verified (previously restart-killing).
- Worker-install gate: `python3 3.9-3.12 required — bundled wheels
  carry only those ABI tags (found: Python 3.14.4)` rc=2, before any
  privileged action: **PASS** (finding 4 verified).
- Worker install under CPython 3.12.16 → unit active; PB attach:
  `bb-vm-worker attached to to-target-…`: **PASS**.
- SSH+KRE (agentless, host-key pinned, wrapper staged, remote cred
  file): `de843ee9` → **COMPLETED**; junit.xml + run.out + manifest
  collected; staging dir empty post-run.
- worker+KRE: `18258373` → **COMPLETED**.
- worker+Robot (real RF 7.5.1): `61cefdb9` → **COMPLETED**.
- worker+Cypress: `786cd852` → **COMPLETED**.
- worker+Playwright: `b4e56e6b` → **COMPLETED**.
- Suite at `b1a8a7ec`: **945 passed / 1 skipped / 1 blocked**
  (issuer-key `test_production_key_auto_loaded` — labeled blocked,
  needs production issuer key).

Superseded packages: `124b5567…e0fe`, `76179316…` / `df6b2d22…f53`,
`2b804b8c…1019` / `e1eda0b5…4c82` — all stale vs `b1a8a7ec` build.

## V7 SSH key interop + V5 + V6 — final head `53bea796`

`.run` sha256 `322e3e9557907e52fb73ff9a3310f96a10b6be55499a8ff01b995e99a820af2b`
(tarball `c3ce118f…09f1`, sources `29d5a23f…0d9a`), internal-test build
`53bea796`.

### V7 OpenSSH interop — PASS
- ed25519, ECDSA (nistp256), RSA-3072 client keys each completed the real
  `to_ssh_exec` connect path on the VM sshd: pinned host key verified,
  pubkey auth, exec, SFTP round-trip.
- Password authentication rejected (publickey-only retained).
- Test keys removed per row.

### V5 uninstall/reinstall — PASS
- Uninstall removed payload only; data/history/users/secret.key intact.
- Reinstall → login served; prior project/history rows present.

### V6 2.5.1 → 2.6.0 upgrade — PASS at `53bea796` (found + fixed one more defect)
- 2.5.1 tarball install + operator repairs (service user, data chown,
  `release.json` 644) → running 2.5.1 with `buildbot-venv/bin/python3`
  → `/tmp/to251/...` (pre-fix stale-venv state, still resolvable at
  upgrade time).
- Seeded `v6-marker-project-2.5.1`; stopped services; ran `.run --yes`.
- **Defect found during V6**: `00627ec3`/`b1a8a7ec` only rebuilt the
  venv when the interpreter symlink was *dangling*; here it still
  resolved to `/tmp/to251` → `_buildbot_venv_ok` correctly fired the
  rebuild, but `python -m venv` **does not rewrite existing bin/
  symlinks** (only pyvenv.cfg) — `bin/python3` stayed on `/tmp/to251`,
  home= corrected. Deleting `/tmp/to251` post-upgrade left it dangling
  → units activating/dead. `dc26fb6b` added the outside-payload check;
  `53bea796` rmtree's the env before recreating.
- After upgrade at `53bea796`: `bin/python3` →
  `/opt/testorchestrator/3rdparty/python-runtime/...python3.12` (inside
  payload), `import buildbot` = 4.3.0, all 5 units active.
- Deleted `/tmp/to251`, restarted all units → all active, web 200.
- Marker `v6-marker-project-2.5.1` + `Admin` user preserved; secrets
  preserved (`web.env`).

### Targeted suite at `53bea796`
- 36 passed (installer payload incl. `_buildbot_venv_ok` matrix,
  linux worker install gates, SSH dispatch, buildbot dispatch/staging).

Superseded package: `63f991ab…7d37` / `a39cf1a9…347f` — stale vs
`53bea796` (venv-rebuild gap on upgrade).

## Strict matrix at `02ee37b2`, package `5b8a12c6…7f7d`

`.run` sha256 `5b8a12c6f973f36218db4c5aed4a71fd072564a94ae422343d44526556bd7f7d`
(tarball `5d07c782…8b7c`, sources `636182a4…8f2d`). Clean baseline →
full matrix on the venv-hardening head:

- `/opt` install: all 5 units active+enabled; `buildbot-venv/bin/python3`
  resolves INSIDE payload; **zero "Unknown user" journal lines**
  (step-1d confirmed: the two earlier lines were the pre-fix install
  only); modes 600/640/644 verified: **PASS**.
- Worker gate: py3.14 refused upfront (`3.9-3.12 required …`), no
  privileged action: **PASS**.
- Worker install under CPython 3.12.16: unit active, PB attach
  `bb-vm-worker attached to to-target-4e710f…`: **PASS**.
- SSH+KRE `db595cfc`: **COMPLETED** — host-key pinned, wrapper +
  source staged remotely, remote run, JUnit collected. First attempt
  UNKNOWN by design: `kre_cred_exec` rejected fixture cred file mode
  644 (permission gate working); resolved operator-side, re-ran.
- worker+KRE `9bae78dc`: **COMPLETED** (same designed cred-mode gate
  on first attempt).
- worker+Robot `b81e642f` (real RF 7.5.1): **COMPLETED**.
- worker+Cypress `b5d31598`: **COMPLETED**.
- worker+Playwright `0c974a81`, `ffcd9d95`: **COMPLETED** (two
  dispatches, both green).

Superseded packages: `322e3e95…af2b`, `b12fb834…`, `63f991ab…7d37` —
stale vs `02ee37b2`.

## Scan rerun at `a9cabfb2` (post strict-matrix head)

| Tool | Baseline | Rerun | Verdict |
|---|---|---|---|
| vulture | 2.14, ~200 FPs whitelisted | 2.16, **129 new hits** — all 60%-conf unused-attr, post-2.5.x ORM cols/serialized attrs (verified read via routes/queries; whitelisted w/ consumer comment) | **1 real new finding**: `verified_capabilities` column (`execution.py:306`) — declared, zero readers/writers → **DEFER-3** (drop needs migration; schema-stability decision for owner) |
| bandit | 1.8.3 triage SEC-1..5 | 1.8.3, same classes; new locs `dispatch.py:734` (B601 — `shlex.quote`d remote_workdir, SEC-2 pattern correctly applied) and `dispatch.py:2172` (B310 — admin-configured webhook `urlopen`, SEC-5 class) | consistent, no new issues |
| pip-audit | 2.9.0 OSV DEP-1..4 | 2.9.0 on clean requirements env: **1 vuln** — paramiko 3.5.1 `PYSEC-2026-2858` = recorded DEP-2 accepted risk (SHA-1 RSA, no upstream fix; DEP-1 Terrapin confirmed resolved by 3.5.1 pin) | consistent |
| jscpd | 4.0.5 baseline | 4.0.5: app py 62f/11 clones/0.68%/1.02% **identical**; templates 50f/29/4.23%/3.66% **identical**; JS 10f/7/11.49%/11.32% **identical**; tests 86f/83 clones/3.11%/4.25% (same clone count, +2 new test files → slightly lower %) | consistent |

## V8 — §2 Linux matrix + §5 sweep at `02ee37b2`, package `5b8a12c6…7f7d`

### §2 eight-combination matrix — Linux cells (this run)

| Framework | Linux PB worker | Linux SSH target | Windows PB worker |
|---|---|---|---|
| Playwright | `0c974a81`/`ffcd9d95` COMPLETED | `f9da4548` COMPLETED | W-kit (product owner) |
| Cypress | `b5d31598` COMPLETED | `68fd2d38` COMPLETED | W-kit (product owner) |
| Robot | `b81e642f` COMPLETED (real RF 7.5.1) | `50568837` COMPLETED (real RF) | W-kit — **required**, owner |
| pytest | `cfc26095` COMPLETED (real pytest 9.2.0) | `23da805a` COMPLETED (real pytest) | W-kit — **required**, owner |

All 8 Linux cells PASS on package `5b8a12c6…7f7d`. SSH cells ran over
real sshd with pinned host key + pubkey auth to `ubuntu@127.0.0.1`.
KRE cells (`db595cfc` SSH, `9bae78dc` worker) ran earlier in the same
session — KRE is not part of the §2 matrix (it gates on Katalon, not
the release matrix).

### §5 packaged security sweep

- Journal: zero plaintext secrets/API keys; only 2 historical systemd
  "unknown user" lines from the PRE-FIX install (13:23), **zero
  recurrence** on fresh install at `02ee37b2`.
- File modes: `secret.key` 600, `web.env` 640, `release.json` 644,
  certs dir 700 — verified on fresh install.
- Payload absolute-path scan: all `venv/bin` + `buildbot-venv/bin`
  shebangs resolve inside `/opt/testorchestrator`; zero `.pth` files
  with outside-payload paths; unit ExecStart/WorkingDirectory all
  payload/data-contained.
- §5b tzdata: `ZoneInfo('Europe/Budapest')` + `('Asia/Kolkata')` load
  from the bundled package interpreter.
- CSRF/RBAC/token-bounding/revocation rows: suite-covered
  (`test_project_access.py` 17 tests green this revision).

## D5 — revision boundary (uncombined)

- Suite at `02ee37b2` (code == `a9cabfb2` == `124347c7`, docs-only
  deltas): **950 passed / 1 skipped / 1 failed-blocked**
  (`test_production_key_auto_loaded` — external issuer key absent).
- Strict 5-case matrix + worker install: package `5b8a12c6…7f7d`,
  head `02ee37b2`.
- V8 8-cell Linux matrix: same package, same session.
- Stale: `322e3e95…` (`53bea796`), `63f991ab…` (`b1a8a7ec`),
  `e1eda0b5…`, `df6b2d22…`, `124b5567…`, `76179316…`, `2b804b8c…`,
  `6957accc…`, `a39cf1a9…` — every earlier tarball/run superseded.
- Windows payload at `124347c7`: setup exe `7d74e5d0…b2d7` unsigned,
  internal-test build — delivered with W1–W18 kit; W-rows run by the
  product owner.

## FINAL CANDIDATE — head `124347c7`, consolidated gate table

**Artifacts (internal-test build, `TO_BUILDBOT_INTERNAL_BUILD=1`):**
- `.run` `08284bdb9c1884a6c1be338d9640085111abdd14186309b3a59397b0f6c3d18b`
- tarball `05ca313db54b83b98c8ea92e15ca7f69572532bb5058f6f2e16c37b71a2a8f0e`
- bb sources `3ca1c41c9d3e7562125f8e0fc2361b529e68af64ca1f6b724b141bca5cc36819`
- Windows setup `7d74e5d0d29a23f322ff1eb65a2182e54e01fab2ec6ad09f1e450e32a9ddb2d7` (UNSIGNED)

Matrix/upgrade verification ran on `5b8a12c6…` (`02ee37b2`); code is
byte-identical to `124347c7` — delta is Manuals-Doc + ledger +
whitelist only.

| Row | Result | Boundary |
|---|---|---|
| Fresh `/opt` install, 5 units, modes, venv-inside-payload | PASS | `02ee37b2` package |
| Worker install (py3.14 gate refuse + py3.12 install + PB attach) | PASS | `02ee37b2` package |
| §2 Linux cells ×8 (worker+SSH × pw/cy/robot/pytest) | PASS | `02ee37b2` package; SSH cells real sshd+pubkey |
| KRE worker + SSH dispatch (cred-file, wrapper, scrub) | PASS | same; fake katalonc = orchestration proof, not Katalon product |
| V5 uninstall/reinstall preserve | PASS | earlier `53bea796` package |
| V6 2.5.1→2.6.0 upgrade (venv rebuild, data preserved) | PASS | `53bea796` package — final fix verified |
| V7 SSH key interop (ed25519/ECDSA/RSA; password rejected) | PASS | dispatcher-level, key-type matrix |
| Lifecycle kill -9 → auto-restart | PASS | `02ee37b2` |
| §5 sweep (journal, modes, path containment, CSRF/RBAC/token suite) | PASS | VM + suite |
| §5b tzdata | PASS | bundled interpreter loads zones |
| Suite | **950 passed / 1 skipped / 1 BLOCKED** | `test_production_key_auto_loaded` — external issuer key absent by design |
| Scans (vulture/bandit/pip-audit/jscpd) | consistent w/ triage + DEFER-3 dead col | `a9cabfb2` rerun |
| W1–W18 Windows kit | **run by the product owner** | payload `7d74e5d0…` delivered |
| `test_production_key_auto_loaded` | **BLOCKED** | `/tmp/to-license-issuer/private.pem` absent — not provisioned, per instruction |

No merge, no tag, no publication; PR #4 stays draft.

## VM10 / VM11 — environment teardown

- `multipass delete to-accept --purge` → `multipass list`: **no
  instances**. Purge removes the instance, its disk image and the
  `to-accept.baseline` snapshot.
- Host throwaway key `~/.ssh/id_to_accept{,.pub}` deleted; the
  in-VM key `~/.ssh/to_agentless` died with the VM.
- No `qemu`-`to-accept` process remains.
- Boundary: `/var/snap/multipass/…/vault/instances/` is root-only;
  directory listing not verified without sudo — `multipass list`
  (the authoritative client view) reports zero instances.

## UI acceptance phase — post-`124347c7` defects + rebuild + Playwright suite

### Product defects found by the browser suite (fix + test each)

1. `e8ac8ff0` — duplicate runner name POSTed through the portal raised
   SQLite `UNIQUE` → HTTP 500. Now a visible flash + redirect; regression
   test in `tests/test_execution_targets.py`.
2. `1b3fa5fb` — Buildbot units shipped without `User=` (ran as root):
   UI-issued worker PB passwords never reached the running master
   (SIGHUP from the `testorchestrator` web process → EPERM under
   `NoNewPrivileges`), so issued workers stayed "awaiting registration".
   Units now run as the service user; `iT-space-logo.png` package mode
   0700→644 (PermissionError on portal pages).

### Rebuild — package at `1b3fa5fb`

- `.run` `34a73313d06b86966e10ceb967ddbb6690f75b4bb11370ead25590fa4afa19f7`
- tarball `435213a82e3caac78c361996ea4cde5c24c8fa88d2d14d0e7fd04470301a2915`
- **Stale**: `08284bdb…`/`05ca313d…`/`3ca1c41c…` (head `124347c7`) and all
  earlier artifacts. Windows payload `7d74e5d0…` is stale too — the
  runner-duplicate fix is app code; rebuild before W-kit delivery.

### Flow 9 recheck — 2.5.1 → `34a73313` upgrade on `to-ui` VM

- 2.5.1 install (documented operator repairs: service user, data-dir
  chown, release.json mode) → marker project seeded → upgrade →
  **marker preserved, login 200, all 5 units active, buildbot units now
  `User=testorchestrator`, release.json `source_rev=1b3fa5fb`**.
- Boundary: `enable --now` returned nonzero when the host OOM-stalled
  the guest mid-install; units were enabled and verified active after
  recovery — a host-resource incident, not an installer defect.

### Playwright suite — `tests/e2e-ui/` committed `a27fad40` (tooling)

Label: **browser** chromium+firefox · **package** `34a73313…f7` ·
**revision** `1b3fa5fb` · VM `to-ui` (Multipass, 8 GB, Ubuntu 26.04).

| Run | Result |
|---|---|
| chromium #1 | 26 passed, 1 skipped |
| chromium #2 | 26 passed, 1 skipped |
| chromium #3 | 26 passed, 1 skipped |
| firefox | 26 passed, 1 skipped |

**Flake rate 0/104.** The consistent skip is
`test_login_and_forced_password_change` — bootstrap already consumed on
this install (the flow itself passed on its first execution, which is
what consumed it). `test_cert_warning_negative` verifies the browser
blocks the self-signed cert with `ignore_https_errors` off.

**Flow results:** 1 bootstrap/TLS PASS · 2 users+403 PASS ·
3 settings PASS (logging settings are env-level `TO_LOGS_*`, no portal
form — boundary, documented in `docs/external-logging.md`) ·
4 project/credential/binding PASS · 5 runner+PB-issue+worker
install+online PASS · 6 dispatch/wait-reasons/detail/exports PASS ·
7 UNKNOWN reconciliation + license-kind + offline-worker PASS ·
8 backup `.tobackup` + restore boundary PASS · 9 upgrade PASS (above).

**Not covered:** live KRE execution with a real Katalon key (needs owner
approval — credential plan + removal). Discovery is `.prj`-centric by
design; the pytest fixture item/binding/runtimes are seeded test data via
a VM-local script — all *user actions* go through the browser only.
Known deferred defect (not failed): invisible keyboard-focus indicator.
