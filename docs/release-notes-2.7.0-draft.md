# TestOrchestrator 2.7.0 — Release notes (DRAFT, pre-release)

Status: draft for the release gate. Not tagged, not published.
This document is finalized only after the final clean build, the
exposure scan, and owner sign-off.

## Headline

2.7.0 adds repository discovery: TestOrchestrator learns which tests
exist in your repositories, per framework, and lets you select, run
and schedule them with evidence. The Node.js frameworks Jest,
Postman/Newman and Bruno join the existing runners. Schedules gain
target kinds matching the run form. KRE licensing gains explicit
online/offline/private modes. CI API tokens gain expiry.

## Required security and behaviour statements

### 1. Jest dependency preparation executes install scripts

Native Jest collection and Jest dependency preparation run
`npm ci` **without** `--ignore-scripts` — install scripts of the
dependency tree execute on the target. This happens **only on an
explicit administrator action** and is gated by the same controls as
every dependency preparation: the test-manager-or-admin role gate, an
audit event including the lockfile hash, timeout caps, the schedule
visibility toggle, and refusal when no `package-lock.json` is present.
The deliberate exception: when `node_modules` is vendored in the
repository, no install runs at all. Static discovery and import
preview never install or execute anything — see the next statement.

### 2. Static discovery is parse-only — wording clarification

Earlier pre-release wording could be read as if discovery never
executed repository code under any circumstances. The precise
contract: **static** discovery and import preview are parse-only,
always — no install, no repo code execution, no network requests.
**Native collection** is a separate, explicit, admin-only action that
runs the framework's own listing tool on an isolated runner — it is
the approved repository-code execution path, and for Jest it performs
dependency preparation first under the controls above. Native
collection never runs automatically, never on a schedule, and is
refused with a clear message for Postman, Bruno and Katalon, where
static discovery is authoritative.

### 3. Licensed-key exposure — licensed cells not run

During the acceptance cycle a Katalon license key was exposed in test
artifacts. The key is a floating license and cannot be rotated without
invalidating existing installations. 2.7.0 therefore ships a dispatch
pre-flight guard that blocks any execution presenting the licensed key
on a target, before anything is staged. The licensed acceptance cells
— the SSH-credentialed cell, the POSIX private-license-server cell and
the two-session overlap cell — **were not run** for this release, by
owner decision. Deployments needing live KRE execution must resolve
the exposure with Katalon first.

## Upgrade notes

- In-place upgrade from 2.6.0 is supported; migrations are additive
  and rollback-verified. Existing runtimes migrate to licensing mode
  `online` unchanged. Existing CI tokens migrate to no-expiry and
  stay valid. Secrets created before 2.7.0 keep working and are
  listed for scope review (`migration_pending`).
- Known limitations are listed in the changelog's 2.7.0 section,
  including the Buildbot-master SQLite state remaining local-only.

## Verification summary (updated at final build)

- Unit suite: counts recorded in the gate ledger on the final head.
- Framework matrix, Option A checks, acceptance evidence: gate ledger.
- Manuals coverage gate: 500/500 UI inventory items documented.
