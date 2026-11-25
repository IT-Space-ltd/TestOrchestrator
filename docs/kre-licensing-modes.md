# KRE licensing modes — online, offline, private

Basis: official Katalon documentation reviewed 2026-11-25 (see
`~/to-acceptance-evidence/KRE-LICENSING-REQUIREMENTS.md` for URLs,
versions, and the exact requirement text this implements).

## Modes (explicit, per-runtime)

`runtime_connections.licensing_mode` — one of:

| mode | invocation | credential requirement |
|---|---|---|
| `online` (default) | `-apiKey=<secret>` against admin.katalon.com | `credential_ref` or legacy `credential_file` REQUIRED |
| `offline` | NO `-apiKey`; KRE verifies .lic files under the execution account's `~/.katalon/license` on every run | managed `license_refs` (license-kind secrets) OR operator-placed .lic files |
| `private` | `-apiKey=<secret>` + `-serverUrl=<url>` (KRE v8.3.5+) | credential REQUIRED **and** `license_server_url` REQUIRED |

Existing runtimes keep `online` — their behaviour is identical to
the pre-change gate. An unrecognised value is gated as `online`
(never silently weakens the credential requirement).

**There is no "hybrid" execution mode.** Katalon uses *hybrid* for an
organisation holding a mix of online and offline licenses — i.e.
different licensing modes within the same installation. That is
supported by registering runtimes with different modes; a single
runtime always uses exactly one mechanism. No silent switching
during execution, no undocumented fallback. If automatic
online→offline fallback is ever desired it is a separate capability
requiring officially supported semantics, an explicit admin policy,
predictable failure handling, and dedicated acceptance tests.

## Offline provisioning (secure lifecycle)

- `.lic` bodies live in the encrypted secret store as `license`-kind
  secrets — one file per named secret (one .lic = one concurrent
  offline session, Katalon floating model). Secret-scope grants
  (project/runtime/runner) apply identically to license secrets;
  a denied scope fails BEFORE decryption.
- Delivery per run: the portal stages a 0600 tar pack
  (`<eid>.licpack.tar`) under the staging dir; PB transports it via
  FileDownload into the restricted `.to_lic` drop dir
  (0700 / SYSTEM+Admins DACL); SSH SFTP-puts it into the run
  workdir. Never inside source.tar, properties, argv, logs, or
  artifacts.
- Install: a target-native step installs each file into the
  execution account's `~/.katalon/license` as `to-<sha256:12>.lic`
  (0600). **The to-* prefix is the ownership contract** — we only
  ever write our own digest-named files; operator-owned .lic files
  are never overwritten, moved, or deleted. A `.to_managed` ledger
  in the same directory records `<sha256>  <name>  user=<acct>` per
  managed file.
- Persistence: installed licenses are durable machine-bound state
  and **persist across runs** — the per-run `.lic` copies in the
  workdir/drop dir are wiped (same contract as `.to_kre_cred`), the
  installed copies are not. Re-delivery of identical bytes is a
  content-addressed no-op.
- Lifecycle: expiry/renewal/replacement is an operator action —
  replace the license secret value (a new digest → a new file; the
  stale file remains TO-managed in the ledger) or remove the file
  manually on target retirement. TO never removes shared license
  material while an authorized execution may depend on it.
- We do not generate, forge, or modify Katalon-issued .lic files.

## Readiness under the actual execution identity

The KRE probe (TO_LIC_MODE env) reports, on the real target account:

- `exec_user` / `exec_profile` — the OS account (machine ID binds to
  hardware **and** osDependentUsername; Windows SYSTEM/session-0 ≠
  interactive user).
- `licensing_mode`, `license_dir`, `license_files` count,
  `license_file=<name> sha256_12=<prefix>` per file, `managed_marker`.

Presence ≠ provisioning-OK ≠ KRE-accepted: the probe never attempts
activation; only a real execution proves acceptance (KRE's own
verdict, classified `license` on failure).

## Concurrency vs licensing

Kept separate by design:

| concept | where |
|---|---|
| configured runtime concurrency | `runtime.concurrency` (scheduling) |
| worker capacity | `runner.max_slots` |
| declared offline entitlement | number of `license_refs` (managed) / probe `license_files` |
| observed licensed sessions | real execution evidence |

One .lic file admits one concurrent offline session — n parallel
sessions need n .lic files in the license dir. `runner.license_slots`
remains the admin-declared cap; TO does not claim entitlement
discovery.

## Failure classification

- `to_license:` provisioning markers (write/perm/transport →
  infrastructure; content/ownership → config).
- KRE's offline verdict ("no KRE and TestCloud license available")
  → `license`, never a false PASS (ISS-013 classification; ISS-014
  guarantees interrupted runs can never report PASSED).
