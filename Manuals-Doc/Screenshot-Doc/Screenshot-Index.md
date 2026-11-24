# Screenshot Index — TestOrchestrator 2.6.0

- **Provenance (2.6.0 recapture):** `admin/infrastructure.png`,
  `admin/runner-new*.png`, `admin/runtime-new*.png`,
  `user/project-inventory.png`, `user/discovered-suite-run.png`
  were captured from the **2.6.0
  codebase** (head `faf4d822`) on a seeded documentation instance —
  framework runtime kinds, both transports, and the externalized-JS
  SSH-fields reveal are visible. Remaining frames retain the 2.5.x
  provenance below.
- **Captured:** Chromium headless at 1440×900 against two live
  instances: a **fresh install** (bootstrap state, `install-*` frames)
  and a **populated instance** carrying real project/execution history.
  `install-transcript.png` is a terminal rendering of actual
  `install.sh`/`install.py` output lines from the 2.5.0 package.
- **User point of view:** all `user/` frames are captured as the
  non-administrator account `manager` (role **Test Manager**) — the
  sidebar shows only what a regular user sees. `admin/` frames are
  captured as Administrator and used only for administrator-context
  captions.
- **Recapture (2.5.1 docs pass):** `user/` frames re-captured on the
  populated 2.5.1 instance — earlier frames had been taken as
  Administrator on a development tree and included a *Method Not
  Allowed* error page (`schedules.png`), a development-version
  infrastructure page (`admin/infrastructure.png`), a duplicate
  (`release-new.png`/`schedule-new.png` were the same frame), and a
  `login.png` that showed the unsupported-version notice (the
  seeded licence did not verify; a valid documentation licence now
  seeds the instance, and `login-unsupported.png` is a genuine
  no-licence capture). `execution-rlabs.png` shows the generated
  report file itself — the portal serves reports sandboxed, so the
  frame is the report document, not the portal chrome.
- **Environment:** isolated documentation installs
- **Data notes:** project "Katalon-cert Demo" is a real Katalon
  project with **genuine Katalon 11.7.0 report output** (imported);
  the live run used a clearly-labelled **fixture** KRE stand-in.
  All users, credentials, and values are demonstration-only — no
  real secrets appear in any frame.

## user/ — application usage

| File | Shows |
|---|---|
| `login.png` | Sign-in page |
| `dashboard.png` | Dashboard: live tiles, project summary, outcome/duration charts |
| `projects.png` | Projects list |
| `project-detail.png` | Project dashboard tab: executions stats, inventory state (94 cases · 14 suites · 3 collections), synced SHA |
| `project-dashboard.png` | Project overview (tabs: Dashboard, Releases, Test, Schedules-Executions, Inventory, Git bindings) |
| `import-new.png` | Historical-result import form (binding, revision, result directory) |
| `import-preview-duplicates.png` | Import preview: resolved commit, `duplicate` decisions with matched executions, collection-grouping warning |
| `discovered-suite-run.png` | Suite item (`smoke.robot`): Run form — profile, release, worker, runtime picker, browser, Robot/pytest option fields (2.6.0) |
| `project-inventory.png` | Project Inventory tab: discovered suite items across frameworks (2.6.0) |
| `discovered-collection.png` | Test-suite collection item |
| `execution-history.png` | Executions list with full filter bar (imported + live origins, outcomes) |
| `execution-detail-imported.png` | Imported execution: provenance (importer, repo, commit, source path, parser), 4 results incl. supplemented suite |
| `execution-detail-failed.png` | Imported rerun with one failed case (`<failure>` message) |
| `execution-detail-live.png` | Live worker run (fixture KRE): worker, run id, runtime, results |
| `execution-rlabs.png` | reportingLabs generated report (4 passed, environment card) |
| `suite-new.png` | New suite form: name, description, source binding, two-panel case selector (6 selected) |
| `suite-detail.png` | Suite detail: ordered entries, version/hash, run controls |
| `release-new.png` | New release form: name, description, start/target dates |
| `release-detail.png` | Release detail: scope table (1 suite + 1 collection), `not yet executed` states, scopeable-only picker |
| `schedule-new.png` | New schedule form: target selector, kind, UTC first run, interval, profile/browser/runner/runtime/overlap |
| `schedules.png` | Schedules list: next run, enabled toggle, run-now, edit |
| `about.png` | About page |

## admin/ — system pages

| File | Shows |
|---|---|
| `settings.png` | Settings landing: task-oriented configuration areas |
| `health.png` | Health & services status |
| `network.png` | Network & certificates configuration |
| `users.png` | User administration: roles, temp-password reset, deactivate, create |
| `infrastructure.png` | Workers table (runner, mode, slots, agent, drain) + KRE installations (remote executable, `Remote — not verified`) |
| `secrets.png` | Credentials: named secret references, system-managed coordinator credential — values never shown |
| `integrations.png` | Integrations configuration |
| `logs.png` | Operational logs |
| `audit.png` | Audit events |
| `changelog.png` | Changelog view |
| `runner-new.png` | Add execution target form: name, type radios (This host / Buildbot worker / Agentless Linux SSH), OS/arch (2.6.0) |
| `runner-new-ssh.png` | Add-target form with *Agentless Linux SSH* selected — SSH host/port/user/workdir/secret fields revealed (2.6.0; previously dead under CSP) |
| `runtime-new.png` | Register-a-test-runtime form: Runner type dropdown (KRE / Playwright / Cypress / Robot / pytest), name, execution location (2.6.0) |
| `runtime-new-remote.png` | Same form with *On another machine* — remote-runner picker, executable/workspace paths, credential fields (2.6.0) |
| `user-new.png` | Create user form: username, display name, role radios, temporary password |
| `licence.png` | Licence administration: status, activated-licence table, add-code field — informational status display; demonstration licence only |
| `login-unsupported.png` | Login page with no valid application licence — exact notice *"This version is not supported"*, form fully usable |
| `install-transcript.png` | Terminal: checksum verification, package extraction, `install.sh` run — payload/data/config paths, worker-asset staging, offline venvs, Buildbot master + worker provisioning, unit enablement, readiness check |
| `install-bootstrap.png` | First sign-in — forced bootstrap-password replacement ("Set your password") |
| `install-dashboard.png` | Fresh install — dashboard at first login, no data yet |
| `install-users.png` | Fresh install — user list containing only the bootstrap Admin |
| `install-infrastructure.png` | Fresh install — empty workers/KRE tables; **Remote worker installers** table (Windows `.exe` + Linux bundle, pinned 4.3.0 + SHA-256) |
| `install-health.png` | Fresh install — Health & services at first boot |
| `reporting.png` | Reporting settings: reportingLabs toggle, log retention bounds, git evidence-export fields |
| `storage-layout.png` | Real `du`/`ls` of the instance data dir — per-directory footprint for capacity planning |
| `evidence-prune.png` | `toctl evidence-prune` dry-run output — the supported orphan-evidence cleanup |
| `dr-restored-executions.png` | DR restore proof — execution history intact on a restored copy of the instance |
| `dr-restored-release.png` | DR restore proof — release + scope intact on the restored instance |
| `dataflow-diagram.png` | Rendered data-flow diagram for §1 — **generated asset, not a UI capture**; source `dataflow-diagram.mmd` (also embedded as a mermaid block in the manual) |
| `architecture-diagram.png` | Rendered component/deployment diagram for §1 — **generated asset, not a UI capture**; source `architecture-diagram.mmd` |

**Not captured:** destructive-action
confirmations (deletion/cancel dialogs were exercised via code paths,
not staged for capture).
