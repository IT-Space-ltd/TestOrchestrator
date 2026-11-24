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
| Unique node IDs, mutually exclusive totals, rerun history | `regression-ledger.json` — 1101 nodes: unit-gate 1009/1/2, e2e-ui 44/1 | accepted |
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
| cypress | real cypress 13.15.0 binary; matrix cell pass+fail both transports | accepted | @cypress/grep integration, per-test selection — gated/unverified |
| jest | real jest 30.5.2; matrix cell pass+fail both transports; `parse_jest` ingest of `Reports/jest.json` (fix `a3ebeeed`) | accepted | per-test (-t) selection path verified via -t validation only |
| gtest | real gtest binaries (libgtest 1.14); matrix cell pass+fail both transports; per-binary flag-support probe + result-XML guard (fix `a3ebeeed`) | accepted | suite/binary granularity only — no per-test selection proven |
| behave | real behave 1.3.3; matrix cell pass+fail both transports | accepted | — |
| pytest-bdd | real pytest-bdd; scenario-granularity cell pass+fail both transports | accepted | file/suite-granularity items fail "node id not found" — gap recorded |
| postman-newman | real newman 6.2.1; matrix cell pass+fail both transports | accepted | — |
| postman-cli | real postman-cli 1.94.0; matrix cell pass+fail both transports | accepted | — |
| bruno | real bru 2.14.1; matrix cell pass+fail both transports | accepted | — |
| KRE | real katalonc 11.7.0 + supplied API key; suite+collection pass, suite fail, missing-cred classify — both transports | accepted | execution profiles beyond default not exercised; optional cloud publication not enabled |

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
| Packaged-install UI acceptance | 44+1 sequential chromium + 12/12 supplementary (storage, retention, retrieval, Add KRE intact) | accepted | accessibility/keyboard/loading-state checks not separately exercised — **not-yet-run** |
| Add KRE unchanged | section present; KRE flow untouched | accepted | no live KRE execution (fixture only) |

## 11 — Docs

README + CHANGELOG updated this milestone (see commit history). Release docs
(`packaged-acceptance.md`, `acceptance-2.6.0.md`) carry prior-stage detail.

## 12 — Resource constraint

One disposable VM (`to-accept`), sequential stages, evidence exported to host
before teardown, no host packages/mounts/services, no production credentials.
Single-VM collapses host+worker — recorded limitation.

## Blocked / not-yet-run summary

- **Blocked**: 2 prod-key tests (boundary documented, `docs/licensing.md`).
- **Not-yet-run**: crafted malformed-report cells; adversarial executed-identity
  fixtures; accessibility/keyboard checks; independent-host partition topology;
  Windows worker matrix (Phase B — pending host hypervisor approval).
- **Recorded asymmetry**: exit-5 (no tests) / exit-127 (missing executable)
  classify specifically on SSH, generically on the registered-worker path —
  both honest failures, no false pass.
- Linux matrix evidence: `~/to-acceptance-evidence/matrix/` —
  13 frameworks × {worker, SSH-only} pass cells all green at `a3ebeeed`
  (package sha256 e5b31c97…); 26 fail cells honest `failed`; timeout/
  cancel/empty/import-error/missing-exe/worker-stopped/KRE-missing-cred
  exercised; 7 product defects fixed (extglobs, probe markers,
  Reports dir, jest spec mapping, KRE license classification,
  jest ingest, gtest flag guard).
