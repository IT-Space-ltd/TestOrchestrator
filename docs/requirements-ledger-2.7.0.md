# Requirements & evidence ledger — 2.7.0 (draft, PR #5)

Status values: **implemented** (code+tests), **accepted** (verified on disposable
VM / packaged install), **blocked** (cannot be exercised under the security
boundary), **not-yet-run**, **unsupported** (out of contract).

Head: `0967ae6a`. Package under test: `testorchestrator-2.6.0-linux-x86_64.tar.gz`
sha256 `4903b2e8…` (product rev `c7fe5c71`). Evidence root:
`~/to-acceptance-evidence/` (+ `packaged-ui/evidence/`).

## 1 — KRE boundary

| Requirement | Implementation | Verification | Status | Limitation |
|---|---|---|---|---|
| KRE registration/dispatch/invocation unchanged | untouched code paths; `dispatch.py` `_fp_item_gate` exempts `kind="kre"` from exec-readiness gate | `test_framework_discovery`, `test_execution_units` (all KRE sites pass unmodified); packaged UI shows "KRE installations" section | accepted | buildbot-path KRE failures now get license/config classification from run log — new error-kind surface only, no behavior change to invocation |
| No production issuer key | `tests/test_licensing.py` prod-key tests blocked | 2 nodes `blocked` in ledger | blocked | requires issuer private key pairing shipped pubkey — prohibited; test-key (`key_id:"test"`) path covers signing mechanics 16/18 |

## 2 — Regression accounting

| Requirement | Verification | Status |
|---|---|---|
| Unique node IDs, mutually exclusive totals, rerun history | `regression-ledger.json` — unit-gate 1009/1/2; e2e-ui 44 passed/1 skipped/0 failed on final payload @3bd9e4b8 (2026-11-26) | accepted |
| Overlap explained | ledger `overlap_note`: browser cases inside `tests/` (not disjoint); e2e-ui separate harness dir | accepted |

## 3 — Framework inventory

Runtime kinds implemented: `kre` (untouched), `pytest`, `robot`, `playwright`,
`cypress`, `jest`, `gtest`, `behave`, `pytest-bdd`, `postman` (newman/postman-cli
engine split), `bruno`. FRAMEWORK_KINDS registry: `execution.py`.

| Requirement | Verification | Status | Limitation |
|---|---|---|---|
| Advertised capabilities enumerated per kind | adapters `pytestfw/robotfw/nodefw/kre/postmanfw/behavefw/brunofw/gtestfw.py`; docs `integration-contracts.md` | implemented | per-version capability matrix is documented per adapter, not consolidated |
| Unsupported combinations unavailable | `nodefw._BROWSERS` server-side validation; engine gates (postman) | implemented | browser list is a fixed allowlist |

## 4 — Execution contract

Configure→readiness→checkout→discovery→selection→dispatch→execute→reconcile→
ingest→store→retrieve→cleanup.

| Requirement | Verification | Status | Limitation |
|---|---|---|---|
| Saved settings reach remote invocation | `kre-invocation.log` records sanitized argv (verified in packaged run); run_config snapshot immutable per execution | accepted | provenance recording is argv+config snapshot, not a formal config manifest |
| Discovery ≠ execution; dispatch gate on exec readiness | `execution_readiness.py` + `_select_runner_runtime` gate; 9 unit tests + packaged UI validate flow | accepted | KRE exempt by design |
| Uncertain remote state → UNKNOWN, never auto-rerun | `test_retry_blocked_maps_unknown_and_holds_reservations`; UNKNOWN reconciliation UI exercised in packaged suite | accepted | reconciliation is manual by design |
| Execution/collection/storage/publication outcomes independent | `test_publication_storage_independence` (c7fe5c71) | accepted | — |

## 5 — Worker and SSH transports

| Requirement | Verification | Status | Limitation |
|---|---|---|---|
| Both transports exercised independently | 8 framework cells ×2 transports packaged-accepted (PB attach + agentless SSH w/ host-key approval) | accepted | single-VM topology — same host hosts both endpoints; not independent-host partition proof |
| Cancellation/process-tree, reconnect, late messages | `test_buildbot_dispatch`, `test_ssh_dispatch` suites (incl. retry-block marker, staging-leak sweep) | implemented | cancellation acceptance on real remote workloads is partially fixture-based |
| Host-key approval, transfer integrity, workdir handling | packaged UI: approve-then-test flow; prior-stage defects fixed (00627ec3/b1a8a7ec: workdir mkdir, cred-wrapper staging, staging sweep) | accepted | — |

## 6 — Selection correctness

| Requirement | Verification | Status | Limitation |
|---|---|---|---|
| Selected-vs-executed evidence | junit parse → TestResult reconciliation; cell runs record item+runtime in snapshot | implemented | sentinel-emitter fixtures (per-item executed-identity reconciliation independent of importer) not yet built — **not-yet-run** for adversarial identity cases |
| -k/-m are filters not identities; granularity | `node_id`/`granularity` columns; `_fp_item_gate` rejects non-selectable candidates | implemented | — |

## 7 — Framework-specific documentation corrections

Per-adapter contract depth is partially delivered. Honest per-framework state:

| Framework | Depth delivered | Status | Not yet covered |
|---|---|---|---|
| pytest | native collection via `-m pytest`, junit ingest, PYBIN probe, xdist opt gate, plugin REQUIRED_LIBS | implemented→accepted (packaged cell) | argument-file mechanism for large selections; per-node-id dispatch granularity exercised in unit tests only |
| robot | real robot 7.5.1 packaged run; real-framework matrix cell (pass+fail, worker+SSH) | accepted | template rows, listeners, remote library — unsupported |
| playwright (JS) | real playwright 1.65.1 browsers; matrix cell pass+fail both transports | accepted | --test-list, project/repeat identities not verified end-to-end |
| playwright-pytest | real pytest-playwright run; matrix cell pass+fail both transports | accepted | — |
| cypress | real cypress 13.15.0 + 16.3.0 binaries; matrix cell pass+fail both transports; installed-package dispatch (16.3.0, ex 439cddb5/e1b3b3b3) | accepted | per-`it()` selection needs the optional `@cypress/grep` plugin — Cypress has no native list/per-test selector; out of 2.7.0 scope by design (`--spec` file granularity verified) |
| jest | real jest 30.5.2; matrix cell pass+fail both transports; `parse_jest` ingest of `Reports/jest.json` (fix `a3ebeeed`) | accepted | per-test (-t) selection path verified via -t validation only |
| gtest | real gtest binaries (libgtest 1.14 + MinGW); matrix cell pass+fail both transports; per-binary flag-support probe + result-XML guard (fix `a3ebeeed`); per-test + parameterized-instance selection proven — `<exe>||Suite.Test` → exact `--gtest_filter` (ISS-018: Windows PB ex 10ad9dbb/16af2b94, installed pkg ex 23d77887/edcb6a20/38064e38) | accepted | — |
| behave | real behave 1.3.3; matrix cell pass+fail both transports | accepted | — |
| pytest-bdd | real pytest-bdd; scenario-granularity cell pass+fail both transports | accepted | file/suite-granularity items fail "node id not found" — gap recorded |
| postman-newman | real newman 6.2.1; matrix cell pass+fail both transports | accepted | — |
| postman-cli | real postman-cli 1.94.0; matrix cell pass+fail both transports | accepted | — |
| bruno | real bru 2.14.1; matrix cell pass+fail both transports | accepted | — |
| KRE | real katalonc 11.7.0 + supplied API key; suite+collection pass, suite fail, missing-cred classify — both transports AND all three remote topologies (Windows PB worker, Linux PB worker, Linux SSH-only) through TestOrchestrator dispatch with **managed `credential_ref` delivery** and target-native launchers (`2ab52aed`+`d4fa8967`, managed-delivery `9fe5e8c1`, kill-tree `178593b4`) | accepted | execution profiles beyond default not exercised; optional cloud publication not enabled |

Phase B (Windows 11 KVM, SYSTEM session-0 PB worker) re-exercised every
framework above on the Windows transport: all probes ready, pass/fail
cells green/honest for pytest, pytest-bdd, behave, robot, jest,
playwright, playwright-pytest, cypress 16.3.0, newman 6.2.3, bru 4.4.0,
postman-cli. gtest Windows exec was config-gated at that stage —
superseded by ISS-012 (staged `.to_gtest_run.py` driver, verified
live on Windows PB including parameterized selection, ISS-018).
KRE verified **through TestOrchestrator dispatch** on all three
remote topologies (see §KRE-remote below) in addition to the earlier
direct on-guest baseline (TS1 pass, TS2 fail, TSC1 collection).

## 8 — Failure & security matrix

| Requirement | Verification | Status |
|---|---|---|
| Injection/traversal/symlink boundaries | `test_storage` (19/19), symlink-escape + approved-roots in packaged store flows | accepted |
| Canary-secret leakage, env-override policy | redaction + `credential_ref`-only secrets; `_redact_values` argv/log scrub | implemented |
| Missing tools, invalid config, timeout/cancel, empty selection, malformed reports | unit suites per adapter; licfail + UNKNOWN + offline-worker flows packaged-accepted | accepted (partial — not every adapter×case) |

## 9 — Runtime & storage management

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Readiness states incl. project-validation-required/ready-execution/stale | `execution_readiness.py`, `READINESS_HELP`, per-project Validate UI | 9 tests + packaged UI flow | accepted |
| Separate artifact/metadata/log retention, preview, confirmed sweep, audit | `retention.py` + migration `m1a2b3c4d5e6` + UI cards | 8 unit + 18/18 local + 17/17 S3 + 18/18 NFS VM acceptance | accepted |
| Bounded share I/O during mount outage | `run_bounded` executor (2 workers, 20s) | 9/9 NFS-boundary acceptance | accepted |
| S3 streaming: caps, ENOSPC, disconnect, checksum, crash sweep | `download_artifact` fallback + tests | 24/24 unit; live-acceptance earlier stage | accepted |
| Git publication independence/eligible-only/no dupes | pre-existing + `test_publication_storage_independence` | 12/12 vs current rev | accepted |

## 10 — Packaged UX

| Requirement | Verification | Status | Limitation |
|---|---|---|---|
| Packaged-install UI acceptance | 44+1 sequential chromium + 12/12 supplementary (storage, retention, retrieval, Add KRE intact) | accepted | accessibility partially closed: `tests/test_accessibility.py` — 5/5 pass —
  verifies every form control on the infrastructure, runtime-wizard, secrets,
  project-storage and admin pages is labeled (server-rendered checks).
  Keyboard-interaction and loading-state checks remain with the e2e-ui phase
  (Phase 6) — still **not-yet-run** there |
| Add KRE unchanged | section present; KRE flow untouched | accepted | no live KRE execution (fixture only) |

## 11 — Docs

README + CHANGELOG updated this milestone (see commit history). Release docs
(`packaged-acceptance.md`, `acceptance-2.6.0.md`) carry prior-stage detail.

## 12 — Resource constraint

One disposable VM (`to-accept`), sequential stages, evidence exported to host
before teardown, no host packages/mounts/services, no production credentials.
Single-VM collapses host+worker — recorded limitation.

## ISS-022 — blocked Windows retry no longer relaunches (2026-11-26, `4ecabb9f`)

Found by the Windows PB worker-termination cell and fixed same-day:

- **Defect**: prep correctly refused the automatic retry (`TO_RETRY_BLOCKED`,
  exit 70) but the build continued — buildbot `ShellCommand` defaults
  `haltOnFailure=False` — so fetch-source/run executed, pytest ran to
  completion and the execution showed `completed`; the no-relaunch policy
  violation was invisible. Portal-side the marker scan also missed the
  Windows step (`prep_1`, buildbot dedups duplicate step names), so even
  a halting build would have misclassified as a plain failure.
- **Fix**: `haltOnFailure=True` on all pre-run gates; retry-block check
  ordered before the results-present branch; scan `prep` + `prep_1`;
  stream-prefix stripped. 14 regression tests.
- **Verified end-to-end on Windows PB** (execution `4a586585…`, builds
  343/344): worker killed mid-run → buildbot retried → retry halted after
  prep (no fetch-source, no run) → execution `UNKNOWN`/incomplete with
  the retry-blocked message — exactly the W6-kit specified behavior.
- **NOTE**: the final payload (`312e5408…`, head `3bd9e4b8`) predates this
  fix. Shipping it in 2.7.0 requires a rebuild + payload-verify cycle.

## Final-payload acceptance (2026-11-26, head `3bd9e4b8`)

Final payload sha256 `312e5408bbdd5020692da2060b7900b6e0211c176dcff92337a2825903ba0fa5`,
byte-verified vs source. On the acceptance guest:

- **e2e-ui: 44 passed / 1 skipped / 0 failed** (skip = designed
  bootstrap-rerun skip). All 10 framework cells green on real engines
  through both transports.
- **ISS-021 fixed** (`9508bf0d`): pasted ssh keys were CRLF-corrupted
  by HTML textarea normalization; storage now normalizes for ssh-kind
  secrets. Regression test in tests/test_secrets_store.py.
- **CI API tokens verified** vs the authorization model + 3 new
  regression tests (`4a605e8b`) — forged overrides, owner shrink,
  deactivated owner. 19/19 pass. NOTE (corrected): token expiry was later added in this
  same release — migration `p5c6d7e8f9a0`, default 90 days, explicit
  never-expires opt-out; expired tokens deny like revoked ones. This
  statement originally read 'no token expiry exists' and was stale
  the moment the expiry feature landed.
- **Fresh-install PASS** (clean /opt + instance dir, 5 units active).
- **Upgrade PASS on copies of real 2.6.0 data** (`data.bak-260`):
  secret ciphertexts byte-identical, derived grant correct,
  migration_pending never bypasses default-deny enforcement,
  idempotent re-upgrade, resume from mid-state,
  upgraded DB boots the full stack. API-token survival was verified
  with tokens seeded onto the copy before upgrading (the 2.6.0 data
  itself carried no tokens) — the seeding is deliberate test data,
  not a production claim.
- **Operational finding (candidate issue)**: no remote cleanup of
  ssh-run workdirs — /tmp tmpfs filled on the guest (1.5G residue),
  breaking SFTP staging and export downloads. Manual cleanup only.
- **Candidate issue (unproven)**: probe-poll may stamp verdicts before
  the trailing DirectoryUpload lands probe markers; all probes settled
  naturally in the final run once environment causes were removed.

Detail: `~/to-acceptance-evidence/CONSOLIDATED-REPORT-2.7.0.md` §J.

## Blocked / not-yet-run summary

- **Blocked**: 2 prod-key tests (boundary documented, `docs/licensing.md`).
- **Not-yet-run**: crafted malformed-report cells; adversarial executed-identity
  fixtures; accessibility/keyboard checks; independent-host partition topology.
- **Recorded asymmetry**: exit-5 (no tests) / exit-127 (missing executable)
  classify specifically on SSH, generically on the registered-worker path —
  both honest failures, no false pass.
- **KRE on remote PB workers — FIXED** (`2ab52aed`, `d4fa8967`; was
  recorded as unsupported): the credential resolver is staged per
  execution inside the source tar / SFTP'd on SSH targets; the script
  is portable (Windows job-object kill, POSIX process-group
  kill). Readiness probes validate interpreter + staged helper on
  the actual target. Accepted through TestOrchestrator on all three
  remote topologies at `d4fa8967`:
- **Managed credential delivery — FIXED** (`9fe5e8c1`, `178593b4`):
  the interim Python helper and the operator-placed target key file
  are gone. `credential_ref` resolves a `runtime`-kind secret
  per execution; the portal stages a 0600 file and delivers it via
  Buildbot FileDownload (`.to_kre_cred`) or SFTP (`run.cred`) —
  removed on every terminal path. The launcher is now
  `kre_cred_exec.sh` (`sh`) / `.to_kre_cred_exec.ps1`
  (`powershell -File`) — no helper Python on any target, staged +
  sha256'd per run, output scrubbed at source. POSIX kill fixed:
  KRE shares the launcher group (Buildbot killpg / SSH group kill
  reach it; setsid had shielded it) and pid-directed signals kill
  the whole tree. Credential failures classify `config` (unknown
  ref, wrong kind) / `infrastructure` (undecryptable) / `license`
  (genuine KRE rejection). Re-accepted on all three topologies with
  zero placed files: Linux PB + SSH (probe `helper_launcher=sh`,
  TS1/TS2/TSC1, timeout+cancel with **zero orphans**, wrong-kind +
  unknown-ref → `config`, no-cred → `license`, bad-suite →
  `config`, 2-way concurrency, fixed-string key scan clean) and
  Windows PB (probe `helper_launcher=powershell`, `-apiKey=***`
  scrubbed in KRE's echoed argv, FileDownload+cleanup verified,
  timeout `exec_timeout=1` killed the tree — follow-up run clean).
  - Windows 11 PB worker (SYSTEM session-0): probe green, TS1 pass
    (2 TestResult rows), TS2 honest `TC3 FAILED`, collection pass,
    missing-cred→`license`, timeout 20s→`infrastructure`, cancel→
    `CANCELED`, missing-exe→`config`, zero orphans/leftovers,
    zero key leakage (fixed-string scan).
  - Linux PB worker (Ubuntu 26.04 multipass): probe green, TS1/TS2/
    collection correct, missing-cred→`license`, timeout 8s→
    `infrastructure` + pgid-kill verified (no orphan katalonc/java),
    cancel→`CANCELED`, missing-exe/bad-suite→`config`.
  - Linux SSH-only (separate runner, no PB involvement): probe green
    (sftp+helper_exec ok), TS1/TS2/collection green, missing-cred→
    `license`, timeout→`infrastructure` + remote pgid killed,
    cancel→`CANCELED` + remote kill confirmed, missing-exe/bad-suite
    →`config`, **disconnect/recovery**: port-22 DROP + VM restart
    mid-run — remote setsid run survived, dispatcher reconnected
    (18 logged retries), resumed, collected → `COMPLETED/PASSED`
    (bb:166), no duplicate execution. Remote workdirs retain
    run.sh/exit_code for reattach by design; no key material in them
    (fixed-string scan). Package rebuilt at `d4fa8967`, sha256
    `2e46ac30…` — shipped payload verified byte-identical to HEAD
    for all six changed files.
- Linux matrix evidence: `~/to-acceptance-evidence/matrix/` —
  13 frameworks × {worker, SSH-only} pass cells all green at `a3ebeeed`
  (package sha256 e5b31c97…); 26 fail cells honest `failed`; timeout/
  cancel/empty/import-error/missing-exe/worker-stopped/KRE-missing-cred
  exercised; 7 product defects fixed (extglobs, probe markers,
  Reports dir, jest spec mapping, KRE license classification,
  jest ingest, gtest flag guard).
- Windows matrix evidence: `~/to-acceptance-evidence/matrix-win/` —
  Windows 11 (26300) KVM guest, SYSTEM session-0 buildbot worker;
  12 runtime probes ready; 11 pass cells COMPLETED exit 0; 11 fail cells
  honest FAILED; timeout/cancel/empty/import-error/missing-exe/KRE-
  missing-cred exercised; gtest Windows exec was config-gated then
  (superseded — ISS-012 ungated, verified live incl. param
  selection ISS-018); 6 product defects fixed (`00ea5722`: probe
  posix flag, probe.cmd cmd-semantics rewrites, win cleanup exit code,
  ELECTRON_RUN_AS_NODE env-block leak, real postman/bruno/gtest probes,
  robot 251-exit probe).
