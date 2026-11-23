# Changelog

## [Unreleased] — 2.6.0 (draft)

Feature release — Playwright Test, headless Cypress E2E and Robot
Framework as first-class runners on the existing Buildbot/SSH
execution paths.
Schema changes: `runtime_connections.runtime_kind`
(`kre`|`playwright`|`cypress`|`robot`, default `kre` — existing
connections upgrade unchanged) and `users.timezone` (IANA name,
default `UTC` — existing users keep identical display).

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
  project's libraries. Out of scope for 2.6.0: parallel execution
  (pabot), custom listeners, keyword-level portal browsing.

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
  and Robot parallel/listener extensions are out of scope.

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
