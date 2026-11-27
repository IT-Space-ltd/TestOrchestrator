# Manuals Revision Report — item / source / effort / risk

Head at planning time: `c807b3889ff05ebf8b4cc9323dcaf52f5bae5c38` (build #6, sha256 `f33d5b69…`).
Owner requirements: 5-year-old simplicity, one action per step, numbered screenshot
callouts with alt text, "if you don't see this" recovery rows, worked examples,
common-mistakes boxes, extended coverage gate, tutorial test cells on the installed package.

## A. Chapter list and screenshot plan

### Admin Manual

| # | Item (chapter/section) | Source of truth | Effort | Screenshots | Risk |
|---|---|---|---|---|---|
| A1 | Server install on Linux (.run + tarball), every prompt and screen, terminal output | Final-build install on fresh Linux guest (existing pipeline) | L | 14–18 | Med — installer screens must match final build exactly; diff-check loop |
| A2 | Server install on Windows: UAC, license/destination/options, progress/finish, Windows Services, first login, uninstall, upgrade | Real Windows guest install of final build | L | 16–20 | High — Windows guest availability inside one-VM rule; longest capture; needs owner approval for VM swap |
| A3 | Worker install Linux + Windows: registration with master, config fields, success/failure states | Live worker install on final build; failure state forced by wrong token | M | 10–12 | Med — failure states need deliberate misconfig, scripted |
| A4 | Status screenshots: infrastructure/runtimes pages, probe states (checking/ready/failed/missing), worker online/offline, service status both OS, health checks — healthy + unhealthy with explanation | Fresh guest + forced unhealthy states (stop service, disconnect worker) | M | 12–14 | Med — unhealthy states are staged, must be reverted cleanly |
| A5 | Upgrade from 2.6.0 step-by-step + backup/restore | Real 2.6.0→2.7.0 upgrade cell (already required for release) | M | 8–10 | Low — doubles as release evidence |
| A6 | deps_prepare chapter (exists, keep + screenshots of lockfile refusal/audit output) | Existing content + live refusal example | S | 3–4 | Low |

### User Manual

| # | Item | Source | Effort | Screenshots | Risk |
|---|---|---|---|---|---|
| U1 | "Your first run" tutorial: login → project → plan → run → results, one action per step | Live run of matrix fixture on final build (jest smoke) | L | 16–20 | Med — depends on final-build matrix stability; reuse jest-positive cell data |
| U2 | Per-framework walkthroughs: Pytest, Robot, Behave, Jest, Postman, Bruno, Katalon static discovery — input values to type, expected results | Matrix fixture executions (already scripted) | XL | 7 chapters × 8–12 = 56–84 | High — largest volume; mitigate with scripted capture pipeline, one capture pass per framework |
| U3 | Worked examples: projects, plans, suites, schedules, artifacts, history with sample data | Same live instance | M | 18–24 | Med |
| U4 | Error and empty states per page | Staged on same instance (empty project list, failed run detail) | M | 10–14 | Low |
| U5 | Common-mistakes box per task | Known support-style issues + mistakes hit during matrix work itself | S | 0 (text) | Low |

**Screenshot total estimate: 150–200.** All scripted, synthetic data only, head+sha256 recorded per shot in `capture-manifest.json`.

## B. Coverage gate extension (checker script)

New failure conditions, each counted in output:
1. Any tutorial step (numbered step line in a tutorial chapter) without a `![alt](shot)` reference within its block.
2. Any image embed without alt text.
3. Any referenced screenshot file missing on disk; any screenshot file in `shots/` unreferenced in the manuals.
4. Any inventory item (page/field/option/button/setting from the generated real UI inventory) undocumented — existing behavior, unchanged.
5. Record per-screenshot provenance (head+sha256) in capture manifest; scan fails if manifest missing entries.

## C. Tutorial test cells

Each tutorial executed on the installed final-build package with unique IDs:
- `TUT-U1-first-run`, `TUT-pytest`, `TUT-robot`, `TUT-behave`, `TUT-jest`, `TUT-postman`, `TUT-bruno`, `TUT-katalon`, `TUT-admin-linux-install`, `TUT-admin-worker-install`, `TUT-admin-windows-install`, `TUT-admin-upgrade-2.6.0`.
- Pass criteria: every documented step reproducible verbatim against the live UI (scripted where possible, checklist-verified otherwise); evidence = capture manifest + cell log.

## D. Capture schedule (one-VM rule)

| Phase | VM | Content | When |
|---|---|---|---|
| 1 | Linux guest (existing to-accept-linux) | Fresh final-build install, matrix fixture, all User Manual + Linux Admin shots, unhealthy states | After freeze + final clean build |
| 2 | Same | Worker install, probe states, upgrade 2.6.0→2.7.0 (already a release cell) | Same window |
| 3 | Windows guest (swap: Linux VM stopped first — one running at a time) | Windows install/uninstall/upgrade, worker install, service status | After Linux capture complete; **owner approval requested before VM swap** |
| 4 | — | Screenshot-diff re-check of installer screens against final build; re-shoot only if differing | Before final package |

Circularity: docs ship inside the build. Installer-screen shots depend only on installer behavior, not bundled docs — the diff-check verifies a rebuild didn't change them.

## E. Risks / decisions needing owner input

1. **Windows guest**: provisioning a Windows VM inside the one-VM rule may need host resources/licensing — confirm before provisioning.
2. Volume: U2 alone is 56–84 screenshots; the scripted capture pipeline is mandatory, manual capture is not repeatable.
3. "5-year-old" style applied to reference/appendix chapters would harm accuracy — proposal: full simple style in tutorials/how-tos; reference tables stay terse. Flagging for confirmation.

Writing starts after this report; no content blocked on owner input begins first.
