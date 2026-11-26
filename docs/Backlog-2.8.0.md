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

2.7.0 ships the read-only side only: tree view over existing inventory,
stale badges, last-result column, and the schedule-form target picker.
