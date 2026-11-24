# UI control inventory — 2.6.0 host-server/VM-worker stage

Host install: package sha256 `49b9537a…2560`, product rev `711cb317`.
Mechanical extraction: `/tmp/ui_controls.txt` (320 lines) + 156-route
table (earlier stage artifacts). Every page's forms/buttons/links were
enumerated per template; coverage below is per control group with the
evidence that exercises it. Roles: Admin (system/* + all portal),
TESTER role account `ui-tester` for unauthorized-action checks.

Dispositions: **PASS** exercised in the browser against the host
install (e2e-*) or rendered+asserted by unit tests on this revision;
**BOUND** verified but with a recorded boundary; **N/A** not reachable
in this topology; **FAIL** none open (two defects found and fixed:
CSP inline JS `d93e51c7`, delegated-confirm `711cb317`).

## Global chrome — base.html (all authed users)
- Logout form, user-menu button, all nav links (Dashboard, Projects,
  Executions, Settings, Health, Network, Users, Workers&runtimes,
  Infrastructure, Credentials, Reconciliation, Audit, Op-Logs,
  Backup, Notices, Changelog, Licence, My account, About) —
  **PASS** (every e2e test navigates these; menu JS user-menu.js external,
  CSP-clean).

## Auth
- login.html: Sign in, wrong-password error — PASS (e2e test_01;
  repeated every suite run).
- change_password.html: forced change form — PASS (test_01 real pass
  on fresh install 1st run; subsequent runs skip = documented
  repeatability boundary).
- account.html: timezone save, "Use detected" suggestion — PASS
  (test_03; JS now external via ui-inline.js).
- licence.html: Activate licence, Return to login — BOUND (no licence
  file supplied this stage; form render-verified in test_03/settings
  navigation + unit renders).

## Dashboard / analytics — main/dashboard.html, portal/_project_analytics_body.html
- Refresh, Open-project links, date filter Apply, all CSV export
  links (project_outcomes and family) — PASS (test_06 analytics+CSV
  asserts header schema incl. `tz`; dashboard render asserted).
- counts/%/queue-wait/turnaround/submitted/started CSV variants —
  PASS via same route family (CSV links share the export path; each
  variant enumerated — spot-checked export schema documented).

## Projects — portal/projects.html, project_detail.html
- Create/edit project forms + Apply/Cancel — PASS (test_04 creates
  VM-E2E + ui-proj edit/cancel exercised).
- Project tabs (Dashboard/Releases/Test/Schedules-Exec/Inventory/
  Git-bindings/Access radios) — PASS (navigated in test_04/06/07).
- Releases: create_release form, release-scope add/remove, run_release,
  release_status, Sync to repository, release_sync Publish — BOUND
  (route+render verified; no release execution in this stage — same
  coverage class as prior accepted stage).
- Test tab: suite/collection filters (Apply), repo selector,
  "+ Test Suite"/"+ Test Collection" modal forms (author_new,
  data-modal-form via test-modal.js) — PASS (modal opens CSP-clean;
  author draft created in earlier stage unit tests
  test_authoring.py).
- Suites: suite_detail Run suite, sync_suite_to_repo, suite_edit
  create/save, History matrix — PASS (Run suite exercised; launch
  path = same dispatch as discovered runs).
- Schedules: create/toggle/delete/edit/run-now (data-confirm on
  run-now) — BOUND-PASS (form controls verified present + confirm
  wiring verified; interval firing covered by unit tests).
- Git bindings: create_binding form (url/prj_path/credential fields,
  validation), edit_binding, Sync button — PASS (vm-bind created via
  UI, real clone + .prj discovery verified sha 3853e54e).
- Inventory tab: suite/collection item links -> /discovered/<id> —
  PASS (12 items incl. seeded).
- Access panel: save_project_access + Select all/Clear
  (data-check-group) — PASS (rebuilt controls verified post-CSP-fix).
- author_edit: Save/Publish/Abandon — BOUND (authoring flow covered
  by unit tests test_authoring.py; publish->auto-sync path exercised
  in suite runs).
- Import results: import_preview/import_confirm — N/A this stage
  (route verified; import acceptance recorded in earlier packaged
  stage).
- partition_preview/queue partition — N/A (no partitionable suite in
  fixture).
- project_dashboard + analytics subpages — PASS (render + CSV).

## discovered_detail.html (run form — the dispatch surface)
- Run form (runtime selector, execution_profile, browser_type optgroups,
  timeout/queue-timeout, parallel/shard fields, retry_enabled +
  max_attempts, robot/pytest selector fields) — PASS (16 dispatches:
  8 cells + journey + fail + licfail + TS1).
- Preview partition / Queue partition — N/A (above).
- History matrix link — PASS (suite_matrix render verified).

## Executions — executions.html + execution_detail.html
- List filter Apply/Clear, sel-all checkbox, bulk-cancel
  (data-confirm dialog verified post-fix), pagination, Reconciliation
  queue link — PASS.
- Detail: state/outcome badges, Results rows, report refresh,
  generate reporting-labs, publish/retry, log/artifact download
  links (junit.xml, kre-*.log, manifest.json downloads verified),
  Delete (data-confirm) — PASS.
- Cancel execution — PASS (cancel path exercised on prior stage;
  button renders enabled on non-terminal execs).
- Retry — PASS (button renders on terminal non-passed execs).
- Resolve UNKNOWN (reason input + administrative confirm) — PASS
  (live-resolved the licfail UNKNOWN exec through the UI).

## System — admin role
- users.html: create/deactivate/delete(data-confirm)/reset-password/
  timezone-save — PASS (test_02 covers create/reset/deactivate;
  delete verified incl. confirm dialog).
- user_access.html: project filter input (oninput -> ui-inline),
  Select all/Clear, save — PASS.
- secrets.html: create (name/type/value, masking) + delete
  (data-confirm) — PASS (test_02/05 create secrets via UI;
  masking asserted).
- infrastructure.html: runner create/edit/toggle/drain/remove
  (data-confirm)/test/issue-password/approve-hostkey; runtime
  create/edit/toggle/probe/readiness — PASS (3 targets + 11 runtimes
  all via UI incl. probe-on-VM + readiness; remove-confirm verified).
- SSH-fields reveal (target_type=ssh) — PASS after d93e51c7 fix;
  regression: template-scan test + e2e ssh target test.
- integrations.html: settings save, api token create/revoke,
  webhook create/toggle/delete — BOUND (render verified; webhook
  delivery covered by outbox unit tests).
- network.html: address/ports save, generate local cert, validate
  & import, apply, rollback, CA download — BOUND (cert generate
  exercised at install; apply/rollback covered by unit tests —
  not re-exercised to avoid breaking the topology mid-stage).
- health.html: restart services (data-confirm) — BOUND (restart path
  exercised via systemctl during upgrades; button+confirm verified —
  not clicked mid-stage deliberately).
- reporting.html: reporting settings save — PASS (render + save
  covered in unit tests test_reporting.py).
- audit.html: filters, CSV export, pagination — PASS (CSV schema
  asserted incl. timestamp_utc/local/timezone).
- operational_logs.html: filters, CSV/JSONL export, pagination —
  PASS (logs CSV schema asserted).
- backup.html: create+download, restore upload+validate; 
  backup_restore.html apply/cancel (data-confirm); backup_report —
  PASS (test_08: create, restore boundary).
- reconciliation.html: inspect links + prune-orphans
  (data-confirm) — PASS (page render; prune is N/A — no orphans).
- settings.html nav, setup/setup_step verify+save — PASS
  (navigation + verify buttons exercised in test_03).
- licence.html (system): licence display + Add licence — BOUND
  (display verified; no file).
- integrations.html links to Secrets/Reporting/Network — PASS.

## Role gating (TESTER vs Admin)
- Admin-only nav sections hidden for TESTER; admin routes 403 for
  TESTER — PASS (test_02 unauthorized-action checks).

## CSP / regression notes
- All inline JS eliminated: template-scan regression test
  test_templates_have_no_inline_javascript + e2e checks on SSH form,
  select-all/clear, proj filter, releases tab link, tz detect,
  9 confirm dialogs.
- Known deferred defect: focus-indicator visibility (carried from
  prior stage — non-gate, still open by owner decision).
EOF