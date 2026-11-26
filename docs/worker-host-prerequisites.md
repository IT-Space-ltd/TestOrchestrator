# Worker-host prerequisites (production deployments)

What a buildbot-worker / ssh target host needs to execute framework
runs. These are the PRODUCTION rules — the disposable acceptance
guests use shortcuts (world-writable `/opt/cypress-cache`, global
`npm install -g`) that must never be copied into production.

## Toolchain

- Pin the toolchain per framework: node LTS for Cypress/Playwright/
  Jest/Newman/Bruno, Python 3.12+ for pytest/pytest-bdd/behave, the
  Robot Framework interpreter version pinned in the project. Pinning
  is per-project policy; the orchestrator executes whatever the
  runtime connection names — version drift on the worker is a
  licensing/evidence problem, not just a flake source.
- Install framework CLIs per-project (npm ci / venv) — never global
  `npm install -g` for project tooling. Global installs couple
  unrelated projects to one mutable toolchain and leak versions
  across tenants.

## Caches

- Browser and binary caches (Cypress binary cache, Playwright
  browsers) belong to the SERVICE ACCOUNT the worker runs as, in a
  per-user or per-service directory (`~/.cache` or a service-owned
  path). Never a world-writable shared directory: any local user can
  then replace cached browser binaries — a supply-chain primitive
  inside every test run.
- npm/pip caches likewise per-user; a shared cache across service
  accounts must be group-owned with 02770, never 0777.

## Filesystem hygiene

- No world-writable shared directories anywhere in the run path
  (cache, install, workdir, artifact staging).
- The worker account needs write only to: its workdir tree, the
  cache dirs above, and the artifact staging area — nothing else.

## Network

- Workers initiate outbound to the master (PB) — no inbound listener
  is required beyond what the deployment chooses for ssh targets.
- KRE executions reach the KRE cloud endpoint or the configured
  license server; offline mode is per-runtime (licensing modes doc).
