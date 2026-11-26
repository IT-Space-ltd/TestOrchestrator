# 2.8.0 backlog

Moved from CHANGELOG.md (owner decision). Owner-approved deferrals from
2.7.0 — no schema or dispatch changes in 2.7.0.

1. **Product-defined collections** (new `Collection`/`CollectionEntry`
   tables, execution-unit fan-out reusing the dispatch units machinery,
   capacity semantics for parallel member suites vs `license_slots` and
   the runtime parallel-session cap, overlap/timeout wording). Partial
   start: start the placeable units, queue the rest, and emit one clear
   message on the collection execution when capacity is exhausted.
   Effort ~1–2 weeks incl. live cells. Risk: high — touches the dispatch
   hot path. Needs its own matrix pass.
2. **Suite generalization to non-Katalon frameworks** (`framework` and
   `framework_project_id` columns on suites, `item_id` references on
   entries, save-time validation, backfill of existing app suites to
   `framework="katalon"`). Effort ~1 week. Risk: high — migration
   correctness on customer data; every existing schedule/plan must
   resolve identically post-migration (same audit pattern as ISS-025).
3. **Plan polymorphism** (plan entries referencing collections as well
   as suites). Depends on item 1. Effort included above.

4. **Single source of truth for parallelism** — `Plan.parallelism` vs
   the collection run mode (`parallel`/`sequential`) can contradict;
   one must win, documented and enforced. Effort ~2–3 days. Risk:
   medium — changes run semantics for existing plans; needs a
   migration/validation pass and owner-facing wording.
5. **Stale-entry healing policy** — 2.7.0 renders stale badges warn-only
   and never drops; decide auto-drop vs keep-with-warning as a product
   policy (per project? per binding?). Effort ~2–3 days. Risk: low
   technically, medium product-wise — dropping discovered entries is
   user-visible data loss if wrong.
6. **Per-runner dependency cache for node frameworks** — strictly an
   optimization layer under the prepare step's visibility rules
   (`npm ci` remains the supported workflow). Risks recorded from the
   Option-A analysis: cache poisoning is supply-chain-critical (persists
   across runs/projects), concurrent-population locking, unbounded disk
   growth/eviction, cross-project contamination, symlink attacks on a
   shared cache. Effort large. Risk: high.
7. **Option-A items not wired in 2.7.0** — none open at backlog time
   (role gate, lockfile-hash audit, timeout caps and the form toggle all
   landed); re-verify at 2.7.0 close and move any residue here.
8. **Distinct timeout classification** — executions ending by timeout
   currently land in generic failure/UNKNOWN buckets; give timeout its
   own terminal classification (and reporting filter) so it is never
   conflated with a test failure. Effort ~2–3 days. Risk: low; reporting
   queries and e2e expectations must be re-validated.
9. **Secret-level authorization for non-runtime consumers** (git, SSH,
   Buildbot) with enforcement at association time — 2.7.0 records this
   as an accepted residual risk: any operator who can reference a
   secret on a binding/target effectively uses it. Effort ~1 week.
   Risk: medium — touches every association path; needs negative
   authorization tests per consumer type.
10. **`authoring.cleanup_abandoned` and `NotConfiguredErrorAdapter`**
    remain documented seams — no code change in 2.7.0; decide their
    futures (implement, remove, or keep-as-seam) deliberately.
    Effort ~1–2 days each. Risk: low.
11. **Paramiko decision** — after final acceptance: vendored/pinned
    paramiko in the installer vs system package vs dropping the SSH
    transport dependency. Effort ~1 day. Risk: low.
12. **Real provider acceptance for Azure and GCS + the live storage
    pipeline** — 2.7.0 evidence is emulator-only by owner decision;
    real-provider acceptance cells and the end-to-end storage pipeline
    remain open. Effort ~2–3 days plus provider access. Risk: medium —
    real credentials, cost, and network egress in CI.
13. **Licensed two-session overlap** — blocked on entitlement while
    only one Katalon seat exists; run when two seats are available.
    Effort small once unblocked. Risk: low.
14. **Windows `.tocred` ACL-break delivery-permission cell** — prove
    credential file delivery permissions on Windows targets.
    Effort ~half a day in the Windows window. Risk: low.
15. **e2e-ui harness for dedicated e2e controllers and remote
    tunnels** — the current harness assumes a local controller;
    remote/tunnel topologies need harness support. Effort ~2–3 days.
    Risk: low.
16. **Production-key licence test** (`test_production_key_autoloaded`)
    — needs a production-shaped key fixture; cannot run with synthetic
    keys. Effort small once a fixture key exists. Risk: low.

### Epic: external authentication and user administration (Admin → Users)

Owner-specified epic; stand-in testing only in the single allowed VM
(Keycloak for OIDC/SAML, OpenLDAP or Samba AD for LDAP), results
labelled "stand-in, not live-provider accepted". Migration invariant:
existing local users and tokens keep working unchanged, with a rollback
path.

17. **Providers — generic OIDC** with presets for Microsoft Entra ID and
    Google Workspace; **LDAP/AD over LDAPS or StartTLS** with a
    least-privilege bind account; **SAML 2.0** after those. Effort:
    OIDC ~1 wk, LDAP ~1 wk, SAML ~1 wk. Risk: high — auth-critical
    surface; needs the security requirements (item 27) proven per
    provider with negative tests.
18. **Google Workspace checks** — validate the `hd` claim against the
    allowed domain, reject accounts without it, require
    `email_verified`. Effort ~1 d. Risk: low; negative tests per rule.
19. **Entra ID** — tenant restriction; role mapping through app roles
    first with group claims as fallback; document the group-count
    limits for SAML and OIDC (overage claims). Effort ~2 d. Risk:
    medium — overage-claim behaviour differs per flow.
20. **Role and project mapping** — IdP groups/app roles → product roles
    and project scopes, with a mapping preview before saving. Effort
    ~3–4 d. Risk: medium — wrong mapping grants excess privilege;
    preview is the mitigation, needs UI tests.
21. **Account linking and provisioning** — link by stable subject ID,
    never by email alone; create users on first sign-in; SCIM
    create/update/deactivate later. Effort ~3 d (+SCIM ~1 wk later).
    Risk: high — email-only linking enables account takeover when an
    IdP reassigns an address; test impact: takeover-negative tests.
22. **Break-glass local admin** + optional enforce-SSO-for-everyone-
    else setting. Effort ~1 d. Risk: medium — misconfiguration can
    lock out all admins; needs a recovery path test.
23. **MFA** — rely on the IdP for SSO users; TOTP for local accounts.
    Effort ~3–4 d. Risk: medium.
24. **Sessions and tokens** — idle and absolute timeouts, forced
    logout, deactivated users lose sessions and API tokens. Effort
    ~2–3 d. Risk: medium — token invalidation must not break worker
    authentication; regression tests over the API surface.
25. **Local accounts** — password policy, lockout, login rate limiting.
    Effort ~2–3 d. Risk: low.
26. **Audit** — sign-ins, failures, role changes, provider
    configuration changes. Effort ~1–2 d. Risk: low; extends the
    existing audit machinery.
27. **Security requirements** — OIDC: `state`, `nonce`, PKCE, issuer/
    audience/signature validation. SAML: signed assertions, audience
    check, clock-skew handling. LDAP: certificate validation, filter-
    input escaping. HTTPS only; all claims and directory attributes
    treated as untrusted. Effort: embedded in 17–19. Risk: high if
    skipped — these are the acceptance gates for each provider.
28. **Admin UI** — source badge per user (local/LDAP/OIDC), last login,
    disable, "test connection" button, claims diagnostic; same
    accessibility standard as other admin forms. Effort ~3–4 d. Risk:
    low; accessibility tests required.
29. **Secrets** — client secrets and bind passwords as `SecretRef`
    names only, never plain values, never in logs. Effort ~1 d.
    Risk: low; reuse the secrets-store machinery.
30. **Testing plan** — Keycloak + OpenLDAP/Samba AD stand-ins in the
    one allowed VM, labelled "stand-in, not live-provider accepted";
    optional single real Entra/Google check if a test tenant is
    supplied. Effort ~2–3 d harness. Risk: low.
31. **Migration** — existing local users/tokens unchanged, rollback
    path required. Effort ~1–2 d. Risk: high if wrong — customer
    lockout; migration and rollback tests mandatory.

### Epic: Reports main menu (owner-specified)

Top-level Reports menu: build, save and export reports with charts.
Prerequisite per owner: check the existing analytics page first —
reuse its data layer, do not duplicate; any new server-side dependency
for charts/PDF/docx/xlsx needs explicit owner approval before adding.

32. **Report builder** — choose report type, filters, charts and
    sections; preview, save the definition, export. Effort ~1 wk.
    Risk: medium — new UI surface, needs the same accessibility
    standard as other forms.
33. **Starter report types** — execution summary; pass-rate and
    duration trends; top failing and flaky tests; failure analysis by
    error kind (config/infrastructure/license/test failure); plan,
    suite and collection results; runner and runtime utilization;
    schedule reliability; framework comparison; traceability where
    requirement/issue links exist; admin audit and compliance report.
    Effort ~2–3 wks for the full set (can ship incrementally). Risk:
    medium — each type needs its numbers verified against the execution
    data model; flaky-test detection needs a defined heuristic.
34. **Filters** — all combinable, with saved filter sets: time range
    (presets+custom), project, plan/suite/collection, framework and
    framework project, runner/runtime/environment, status/outcome,
    branch/ref/commit, trigger (manual/schedule/API), user, tags,
    release; compare two filtered sets side by side. Effort ~1 wk.
    Risk: medium — combinatorial query correctness; every filter must
    compose with project scoping.
35. **Export formats** — PDF, docx, xlsx plus CSV. Charts must appear
    in exported files (not just on screen) and look the same in all
    three; Excel includes a raw-data sheet next to the summary and
    full execution history; server-side real PDF generation, never a
    browser print dialog; optional title page, logo, date range and
    applied-filter summary on every export. Effort ~1–2 wks. Risk:
    medium-high — this is where new dependencies (pdf/xlsx/docx/chart
    rendering) will be proposed; owner approval required per item.
36. **Saved and scheduled reports** — saved definitions per user or
    shared by project; optional scheduled generation with downloadable
    result; shareable links with expiry. Effort ~1 wk. Risk: medium —
    share links are an authorization surface (expiry + audit mandatory).
37. **Quality and safety** — role-based access and project scoping on
    every query (a user must never see data outside their projects);
    escape all report text and discovered content; background
    generation for large reports with size/time limits, progress, clear
    failure message; audit exports and shared links; no N+1 queries in
    large tables; charts need a data-table alternative and labels for
    accessibility. Effort embedded in 32–36. Risk: high if skipped —
    these are acceptance gates.
38. **Data-layer reuse check** — verify the existing analytics page's
    data layer covers these queries; reuse, don't duplicate; produce
    the dependency proposal (charts, PDF, docx, xlsx) for owner
    approval before any implementation. Effort ~2–3 d. Risk: low.
39. **Testing plan** — seed data across projects, plans, frameworks,
    time ranges; verify each filter, that export files open correctly
    in Word/Excel/PDF readers, that exported numbers match on-screen
    numbers, and that role scoping holds. Effort ~1 wk. Risk: low.


### Epic: Admin > Database — SQLite-to-PostgreSQL migration wizard (owner-specified)

Principles: SQLite stays the built-in default (nothing changes for
users who don't opt in); PostgreSQL is never bundled or installed by
the product — the admin runs it themselves, we only connect and
migrate; admin-only, role-gated, audited; modern accessible UI; the
app database and the Buildbot master state move together in one flow;
rollback within a time window only — no reverse migration in v1
(recorded as deferred).

40. **Admin > Database page** — current engine, version, location,
    size, health, last backup, migration state for both databases;
    "Switch to PostgreSQL" CTA; post-switch rollback window with
    countdown and "Roll back to SQLite"/"Finalize" actions.
    Effort ~3 d. Risk: low.
41. **Wizard flow** — steps: (1) before-you-start with checklist,
    downtime estimate, maintenance-mode notice; (2) connect (host,
    port, database, user, password with show/hide, SSL mode; password
    from env var or secret store); (3) test connectivity/version
    range/UTF-8/privileges/empty targets/latency with specific fixes;
    (4) pre-flight sizes, row counts, duration estimate, free disk,
    idle-system requirement or drain step; (5) mandatory verified
    backups with SHA256; (6) migrate in maintenance mode — Alembic
    schema on PG, table-by-table batched copy in dependency order with
    live progress and resumable state, sequence resets, explicit type
    conversion, then Buildbot state per the audit; (7) verify row
    counts, per-table checksums, smoke queries, Buildbot health + smoke
    build — block on any mismatch; (8) atomic settings write, ordered
    service restart, worker reconnect, health checks, exit maintenance;
    (9) rollback within window only — SQLite files never modified,
    one-step settings restore, typed confirmation after showing counts
    of runs/changes that would be lost; window close or Finalize
    archives. Effort ~4–6 wks total. Risk: high — data-critical path;
    the two-database cutover must never leave a split state.
42. **Security and operations** — admin role gate, CSRF-safe flow,
    audit events for test/start/switch/rollback/finalize; password
    never logged, never returned to the browser, masked in audit; TLS
    verification modes with a warning when SSL is off; single-host
    scope — refuse if other instances are detected; downloadable
    migration report; idempotent resumable process. Effort included
    in 41. Risk: high if skipped — acceptance gates.
43. **UX and accessibility** — stepper layout, inline validation,
    progress screen with cancel before the point of no return,
    keyboard access, screen-reader friendly with aria-live progress,
    all displayed content escaped. Effort ~2–3 d. Risk: low.
44. **Audit-first: application database** — run all Alembic migrations
    on PostgreSQL; check types, constraint names, raw SQL; replace
    SQLite-specific code; define supported PG version range and driver;
    decide dependency packaging for Linux and Windows installers.
    Effort ~1 wk audit. Risk: medium — installer dependency decisions
    need owner approval like any new dependency.
45. **Audit-first: Buildbot state** — audit how Buildbot stores state
    and what must be kept; decide whether history needs copying or a
    fresh state plus the app's own run history suffices; define
    behavior for in-flight builds and queued schedules; cover
    Buildbot's upgrade/migration steps on PG, restart order, worker
    reconnection; record driver/version requirements Buildbot's PG
    support adds. Effort ~1 wk audit. Risk: medium-high — least-known
    surface in the epic.
46. **Testing** — PostgreSQL job in the test suite and CI matrix
    covering app+Buildbot together; installed-package live cell for
    the full switch and rollback, synthetic credentials only.
    Effort ~1 wk. Risk: low.
47. **Related work** — retention and rollup tables for reports;
    document connection pooling and performance settings.
    Effort ~2–3 d. Risk: low.
    **Out of scope**: bundling PostgreSQL, clustering/HA, multi-host,
    reverse migration, DuckDB and Turso (watch list only).


2.7.0 ships the read-only side only: tree view over existing inventory,
stale badges, last-result column, and the schedule-form target picker.
