# 2.8.0 Reports menu — analytics data-layer reuse audit

Backlog item: **38. Data-layer reuse check**. This audit is the required
prerequisite before implementing the Reports main menu. No product code or
dependency is changed here; export/chart dependency choices remain pending
owner approval.

## Existing implementation inventory

### Aggregation modules

- `testorchestrator/project_dashboard.py`
  - `summary(project_id, days, suite, state, source_ref, environment, tz)`
  - produces the current project dashboard rows: outcome trend, case-level
    pass rate, duration points, top failing cases, recent executions.
  - filters: project, period, suite, state, source ref, environment.
- `testorchestrator/analytics.py`
  - `main_analytics(user, days, tz)` for cross-project main-dashboard
    analytics.
  - `project_analytics(project_id, days, suite, state, source_ref,
    environment, tz)` for advanced project analytics.
  - shared logical-run machinery: `resolve_logical_runs`, `head_id`,
    first-attempt/final-outcome cohort handling, terminal-state policy,
    timezone-aware local-day bucketing, explicit truncation bounds.
  - advanced outputs: result-history matrix, suite-duration distribution,
    environment comparison, first-vs-final pass rate, duration regression,
    evidence freshness, queue wait/turnaround, execution activity.
- `docs/analytics-counting.md`
  - authoritative counting semantics for logical runs, retries, units,
    terminal outcomes, local-day bucketing and truncation disclosure.
- `testorchestrator/charts.py`
  - presentation-only Plotly figure builders fed by the rows above.
  - aggregation and rendering are already separated; this separation should
    be preserved.

### Routes and exports

- `/projects/<id>/dashboard` renders the project dashboard and Analytics tab.
- `/projects/<id>/analytics` returns JSON and per-chart CSV for the advanced
  analytics payload.
- CSV is currently chart-specific and project-scoped; it is not a general
  report export pipeline.
- There is no existing PDF, docx or xlsx export pipeline.

### Authorization and scoping

- Cross-project analytics use `_visible_executions(user, days)`, which first
  restricts executions to projects where `user.project_allowed(project_id)`
  is true. This is the correct pattern: scope in the query/source set, never
  post-filter after aggregation.
- Project dashboard routes resolve through `_project_or_404`, so unauthorized
  project access is indistinguishable from a missing project.
- Filter option sets are also restricted to the authorized project id.
- The future report builder must reuse these entry points or a stricter
  query-scope helper. It must never accept a project id list from the client
  without intersecting it with `current_user.project_allowed`.

## Reuse assessment

### Directly reusable without semantic changes

- Retry-chain resolution and logical-run counting:
  `resolve_logical_runs`, `head_id`, terminal-state constants.
- Local-day timezone bucketing and UTC-instant storage conventions.
- Counting policy from `docs/analytics-counting.md`.
- Existing trend rows for outcome, pass rate, duration and failure frequency.
- Advanced analytics rows for flakiness/history, duration regression,
  environment comparison and evidence freshness.
- Existing project/state/suite/source-ref/environment filter semantics.
- Existing Plotly browser rendering path.

### Reusable after refactoring, not by copying

- The current aggregations load SQLAlchemy result lists and aggregate in
  Python. That is acceptable for the dashboard bounds, but report filters
  will be combinatorial and potentially cover long time ranges. The report
  data layer should introduce a small shared query/row pipeline rather than
  copying these loops per report type.
- `_project_executions*` and `_visible_executions` should become the basis
  for a scoped execution query builder. Today they are private dashboard
  helpers and not a general reporting API.
- Chart-specific CSV shape logic in the route should not become the export
  implementation. Reports need dataset-oriented export models with stable
  column contracts and raw-data sheets/files.

### Not currently covered

- Collections and collection results — do not exist yet; depends on backlog
  item 1.
- Framework/framework-project filtering as first-class report dimensions —
  framework inventory exists, but suite generalization is backlog item 2.
- Plan, schedule, trigger, release, user and tag filters in one composable
  filter model. Some fields exist on the schema, but the dashboard only
  exposes a subset.
- Runner/runtime utilization and failure-kind classification need new
  explicit definitions before implementation.
- Flaky-test detection needs a documented heuristic. The existing history
  matrix exposes evidence but does not define a flaky score or threshold.
- Cross-project report builder UI, saved definitions, shared links,
  scheduled generation, background export jobs and export audit events.
- Raw execution-history export at scale, size/time limits, progress and
  cancellation.

## Data correctness rules for the Reports menu

1. **Use logical-run semantics by default.** Retry attempts must not inflate
   pass-rate, duration or trend numbers unless a report intentionally says
   “attempt-level”.
2. **Never conflate infra/no-result with test failure.** Preserve the
   existing `none`/`incomplete` distinctions until backlog item 8 adds the
   timeout terminal classification.
3. **Disclose truncation.** Existing `MAX_*` bounds are product behavior;
   report outputs must carry the same or stricter disclosure.
4. **Timezone is part of the dataset contract.** Exports must record the
   viewer/report timezone and use the same local-day bucketing as the
   on-screen preview.
5. **Preview and export must use the same immutable query snapshot inputs.**
   If data changes during a long export, the generated file must still be
   internally consistent and labeled with generated-at/filter state.
6. **Project scoping happens before aggregation.** This is an acceptance
   gate, not an optimization.

## Recommended implementation shape

Create a dedicated reporting service module rather than expanding routes:

```text
testorchestrator/reporting/
  queries.py       scoped execution/result query builders
  definitions.py   report/filter schema validation
  aggregates.py    reusable metric frames built on analytics semantics
  exports/         csv/xlsx/docx/pdf implementations after approval
  jobs.py          background generation, limits, progress, audit
```

Migration path:

1. Move/adapter the existing dashboard query semantics behind `queries.py`
   without changing dashboard output.
2. Reuse `analytics.py` row contracts where possible; do not duplicate
   retry-chain logic.
3. Add report-definition validation and a preview endpoint.
4. Add export implementations only after owner approval of dependencies.
5. Keep the existing dashboard routes working as regression coverage for
   the shared data layer.

## Dependency proposal for owner decision

No dependency has been added. Current state:

- **Already present:** `plotly==7.1.0` for browser-side charts and vendored
  Plotly JS. This covers on-screen chart rendering but not server-side chart
  image generation.
- **Already present:** vendored `reporting_labs` for execution reports, not
  a general report-builder export engine.
- **Missing:** server-side chart rasterization, PDF, docx and xlsx writers.

Proposed packages, requiring explicit owner approval before use:

| Need | Candidate | Notes / risk |
|---|---|---|
| xlsx | `openpyxl` | Pure-Python, widely used; can write raw-data and summary sheets. Preferred xlsx candidate. |
| docx | `python-docx` | Pure-Python; adequate for tables/images. Requires chart images to embed. |
| PDF | `reportlab` | Programmatic server-side PDF generation with wheel availability; more layout work, but no browser print dialog. |
| PDF alternative | `weasyprint` | HTML/CSS-to-PDF, attractive layout reuse, but native/system-library packaging risk on Windows and Linux is higher. Needs explicit packaging spike before approval. |
| chart rasterization | `kaleido` | Plotly-static-image path, but ships/depends on browser-native components; packaging and security review required, especially for offline Windows installer. |
| chart fallback | server-side SVG generation from report data | Avoids Kaleido/browser dependency but duplicates chart rendering semantics and may not look identical to browser Plotly charts. |

Recommendation: approve/x spike in this order:

1. `openpyxl` for xlsx raw-data export.
2. `python-docx` for docx.
3. `reportlab` for deterministic server-side PDF.
4. evaluate `kaleido` separately; if packaging risk is unacceptable, use a
   documented simplified server-rendered chart style rather than shipping a
   browser runtime.

## Suggested first implementation slice

After owner approval of the data-layer shape (and before export formats):

1. Extract a scoped reporting query builder with tests proving role/project
   scoping.
2. Implement one report type end-to-end: **execution summary**.
3. Support preview + CSV only, using no new dependency.
4. Add report-definition validation, escaping, audit events and large-query
   limits.
5. Use that slice as the template for trend/flaky/utilization reports.

This keeps the first product-code increment small while establishing the
security and counting foundations required by backlog items 32–37.

## Status update — implementation slices

Implemented on `feature/2.8.0-backlog`: the top-level Reports menu now exposes
the execution-summary report preview and CSV export using the scoped query
layer proposed above, plus a pass-rate/duration trend report with browser
Plotly charts, an accessible data table and daily-row CSV. The trend slice
uses logical-run semantics: terminal logical-role attempts in the rolling
window are grouped through the shared retry-chain resolver before metadata
filters are applied. Because the window ends at the report generation instant,
an older out-of-window chain head cannot change which in-window terminal
attempt is final; this keeps the source query bounded without weakening the
final-attempt semantics. Runs are assigned to the final resolved attempt's
finish day in the viewer's timezone, and partitioned unit-child results
contribute once to the parent logical run. Result statuses are aggregated in
one batched query after the bounded logical-run set is selected, so the rollup
does not N+1. CSV rows carry the generated-at instant, timezone, filter
snapshot and truncation metadata. A top-failing/flaky-test report is also
implemented on the same logical-run
selection layer. It collapses each case to one severity-ordered status per
logical run, ranks failures by failed/error logical-run count, and uses a
disclosed flaky heuristic: at least three executed runs, at least one pass and
one failure/error, ranked by 2*min(pass, fail)/executed. Case rankings are
capped and truncation is disclosed. Failure analysis by error kind is also
implemented: explicit `error_kind` wins, failed runs with failed/error parsed
case evidence classify as test failures, and other non-passed runs remain
honestly uncategorized rather than being folded into test failure. Schedule
reliability is also implemented on the same logical-run selection layer: rows
count final resolved outcomes per schedule and join audited
`schedule.misfire_skipped`, `schedule.overlap_skipped`,
`schedule.target_unavailable` and `schedule.fire_failed` events in the same
rolling window. Audit lookup is constrained to visible schedule IDs rather
than loading unrelated system audit rows, and zero-run schedules remain
visible so silent schedules are not hidden. Runner/runtime utilization is
also implemented as a deliberately attempt-level exception to logical-run
counting: retries and partition units consume real capacity, so terminal
attempts are counted individually. Busy time is clipped to the overlap with
the rolling report window. Runner capacity uses the dispatch ceiling
min(max_slots, license_slots) with unset licences unconstrained; runtime
capacity is capped by both its configured concurrency and the host runner
ceiling. Utilization percentages are not clipped at 100%, because over-100%
values are evidence of overlapping historical assignments or later capacity
reconfiguration. Zero-use runners/runtimes remain visible only when their
current project scopes intersect the viewer's visible projects; historical
visible executions still surface their assigned infrastructure even if the
current scope was later narrowed. Plan/suite/collection results are also
implemented on logical-run semantics. Target identity comes from immutable
execution snapshots: app suite IDs, plan IDs, or repository
binding+kind+path source-target triples, so inventory replacement does not
split repository-target history. Plan rows intentionally aggregate member
suite logical runs and are labeled as such; they are not whole-plan-run
rollups yet. Direct test/case executions are outside that target grain and
are omitted with a disclosed count rather than being folded into a suite row.
Saved definitions, scheduled generation, share links, whole-plan-run rollups,
PDF/docx/xlsx and the remaining report types remain open backlog work.
