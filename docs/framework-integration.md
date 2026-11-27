# Framework integration notes (contributors)

Rules that apply when adding a new test framework to TestOrchestrator.

## Native collection: decide explicitly

Every framework must be in exactly one of these two sets:

1. **Frameworks with a collector** — a script in
   `testorchestrator/collectors.py` (`COLLECT_SCRIPTS` or
   `NODE_SCRIPTS`) that runs on the target, executes or lists tests,
   and returns structured results.
2. **Collector-less frameworks** — static discovery is authoritative.
   The pinned set today is **`{"bruno", "katalon", "postman"}`**
   (enforced by `tests/test_deps_prepare.py::test_collect_refusal_covers_every_collectorless_framework`).

Adding a framework without deciding breaks that test — deliberately.
Make the decision in the test, not by accident.

## Rules for collector-less frameworks

- A native collect request must be **refused early with a clear
  message** pointing the user at static discovery.
- The refusal must **never** set the framework project's
  `discovery_status` to `failed` — a refused collect is not a
  discovery failure (ISS-016 pattern: poisoning the status blocks all
  later dispatch).

## deps_prepare

- Static discovery and import preview are parse-only: no install, no
  repo code execution, ever.
- Native jest collect runs `npm ci` **without** `--ignore-scripts`
  (install scripts execute). This is deliberate and documented in the
  Admin Manual and release notes.
- The exception: when `node_modules` is vendored in the repository,
  no install is needed and none runs.
- Without a lockfile, prepare/collect refuses.
- If deps preparation is off, collect fails with a clear message —
  never silently skips.
