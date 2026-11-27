# Manuals 2.7.0 — Step 0 audit and plan

## Audit of existing manuals

| Aspect | Finding |
|---|---|
| Location | `Manuals-Doc/User-Manual.md` (820 lines), `Manuals-Doc/Admin-Manual.md` (2233 lines) |
| Format | Markdown, single file per manual, numbered chapters, fenced command blocks, glossary-style term definition inline |
| Screenshots | `Manuals-Doc/Screenshot-Doc/{admin,user}/` + `Screenshot-Index.md` with per-frame provenance |
| Version | Written for 2.6.0 — pre-dates repository discovery, node frameworks, deps_prepare, licensing modes, tree view, schedule target kinds, secrets scoping, token expiry |
| **Build shipping** | **NOT in the installer** — `scripts/build_bundle.py` INCLUDE ships only `docs/`, `README.md`, `CHANGELOG.md`. Owner requires docs inside the final build → build script change needed (small, low-risk). Decision: add `Manuals-Doc` to INCLUDE under category `docs`, excluding nothing — screenshots are part of the manual. |
| Build pipeline | No build step — Markdown is the shipped format (kept: no reason to change; beginner audience reads rendered or plain markdown fine, and the portal does not embed docs) |

## Chapter outline (2.7.0)

### User Manual (update in place)
1. Introduction — updated for 2.7.0 feature set; glossary chapter added
2. Projects and repositories — extended: repository bindings, sync, discovery status
3. Frameworks and framework projects — NEW chapter: per-framework settings, discovery modes (static vs native), inventory
4. Discovery and inventory — NEW chapter: static parse-only discovery, native collection, rediscovery, selectable items, stale entries
5. Running tests — updated: per-framework run fields (jest patterns, postman env/folder/iterations, bruno env/tags), runtimes and readiness
6. Suites, releases, plans — carried forward, schedule target kinds added
7. Scheduling — updated: target kinds, timeout/overlap semantics, deps_prepare toggle visibility
8. Results, artifacts, history — updated: artifact collection, outcome kinds
9. Historical-result import — carried forward
10. Reports and evidence — carried forward (2.6.0 analytics only; NO 2.8.0 Reports menu)
11. Roles — role-specific visibility appendix
12. Troubleshooting + FAQ + quick-start — NEW per owner spec

### Admin Manual (update in place)
1–3. Architecture/prerequisites/package verification — carried forward, hash-verification updated
4–5. Linux/Windows install + upgrade incl. from 2.6.0 — updated, migration list extended
6. Execution targets — extended: node framework runtime prerequisites (node, newman, bru, npm)
7. Users, roles, admin role gate — NEW chapter
8. Secrets, credentials, scope settings — NEW chapter (scope_json, migration_pending)
9. Runtimes + deps_prepare — NEW chapter: install scripts run (no --ignore-scripts), lockfile required, audit events, timeouts, schedule toggle, vendored node_modules exception (deliberate)
10. Schedules, Buildbot, SSH runners, Windows specifics — updated
11. KRE licensing modes — NEW chapter: online/offline/private; licensed-key exposure statement matching release notes; cells not run
12. Backup/restore, logs/diagnostics, hardening, reverse proxy — carried forward
13. CI API tokens — extended: expiry semantics
14. Troubleshooting with real error messages — extended with discovery/dispatch errors
15. Configuration reference — updated: all new config keys

## Screenshot plan
- Capture on the frozen final build on the guest, reproducible script
  (`Manuals-Doc/capture/capture.py` — playwright against the portal,
  seeded synthetic data only), head+sha256 recorded in the index.
- Consistent 1440x900 window, default theme, numbered callouts, alt
  text per image, success AND error states for each key flow.
- Refresh once, after freeze, before the final clean build.
- Priority frames: login, navigation, project detail, binding config,
  discovery status, inventory tree, run form per framework (4),
  schedule form, execution detail incl. artifacts, runtime config,
  deps_prepare admin controls, secrets admin, users admin, import
  preview, reports. Error states: probe failed, validation errors,
  collect refused, deps refusal, license blocked.

## Coverage gate
- `scripts/gen_ui_inventory.py` — DONE: 53 templates, 228 fields,
  56 selects, 151 buttons in `docs/ui-inventory-2.7.0.json`.
- `scripts/check_manual_coverage.py` — fails if any inventory item is
  missing from the manuals (field/select-option/button/page name
  match). Inventory count + result reported with the final build.
- Each tutorial executed on the installed package as a test cell with
  unique ID, evidence in the ledger.

## Item/source/effort/risk table

| # | Item | Source | Effort | Risk |
|---|---|---|---|---|
| 1 | User Manual core update (ch 1–2, 5–9) | existing manual + templates/routes | L | low — mostly carried forward |
| 2 | User Manual NEW chapters (3–4 frameworks/discovery, 12 troubleshooting/FAQ) | discovery/*.py, dispatch.py, routes | XL | medium — largest new surface |
| 3 | Admin Manual carried chapters (1–5, 10, 12, 15) | existing manual + install scripts | M | low |
| 4 | Admin Manual NEW chapters (7 users/roles, 8 secrets, 9 deps_prepare, 11 licensing, 13 tokens) | system/routes.py, secrets_store.py, dispatch.py | L | medium — security wording must match release notes exactly |
| 5 | Field-level entries (228 fields, 56 selects) | ui-inventory json | XL | high-effort mechanical; mitigated by systematic per-page passes |
| 6 | Screenshot capture script + frames | guest frozen build | L | medium — depends on freeze; reproducibility pinned |
| 7 | Coverage checker script | inventory json + manuals | S | low |
| 8 | Tutorial execution cells | guest installed package | M | medium — depends on working matrix |
| 9 | build_bundle.py include change | build script | S | low — additive |
| 10 | Glossary | both manuals | M | low |

## Writing rules compliance notes
- 2.8.0 items (Reports menu, PostgreSQL wizard) will NOT be written as
  available. The unified Test tab: documented only if shipped in 2.7.0.
- Fixed-string exposure scan covers manuals + screenshots pre-sign-off.
