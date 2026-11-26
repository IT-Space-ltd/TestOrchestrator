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
