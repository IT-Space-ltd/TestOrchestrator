# Advanced Analytics — counting policy

Counting and windowing rules for the Advanced analytics sections on the
Main Dashboard (`/`) and the Project Dashboard
(`/projects/<id>/dashboard`). All figures are computed in
`testorchestrator/analytics.py`; Plotly figures are built in
`testorchestrator/charts.py`. Aggregation and rendering are separate.
Every chart states its counting unit on the card.

## Terms

- **Test case** — one `TestResult` row (parsed JUnit/case result).
- **Attempt** — one `Execution` row. A retry creates a NEW row linked by
  `snapshot.retry_of`; `snapshot.attempt` increments (1, 2, 3…).
- **Unit** — a `role="unit"` child execution of a partitioned
  (`role="parent"`) run; each unit is a real dispatchable shard.
- **Logical run** — a retry-chain head (`snapshot.retry_of` unset) with
  `role in ("", "parent")`, together with all of its retry attempts.
  Unit children never count as their own logical runs.
- **Final resolved attempt** — the highest-`attempt` member of the chain
  that reached a terminal state (`completed`, `failed`, `canceled`).
  A chain whose latest attempt is still in flight resolves to the last
  TERMINAL member; a chain with no terminal member is excluded from
  outcome metrics (reported as insufficient data, not guessed).
- **Terminal outcome** — the resolved attempt's `outcome`:
  `passed`, `failed`, `incomplete` (partial/canceled), or `none`
  (infra failure before any result). `none` is displayed honestly —
  never folded into passed.

## Time-window assignment

- A **logical run** belongs to the day/period in which its *final
  resolved attempt* finished — except in the first-vs-final chart,
  where the cohort is assigned to the day the *first* attempt finished
  so the before/after pair always describes the same runs.
- **Queue wait / turnaround** rows belong to the day the execution was
  enqueued (`created_at`).
- An attempt that starts in-window but finishes out-of-window is not
  counted in outcome metrics until it terminates (it is still shown as
  active in the existing metric strip — unchanged).

## Chart-by-chart policy

### Main Dashboard

**Project outcome comparison** — unit: logical run. Per visible
project, terminal logical runs grouped by the final resolved outcome.
Unit children and non-terminal chains excluded. Toggle switches counts
(absolute) / percent (share of that project's terminal logical runs).
Bounded to the 30 projects with the most in-window runs; overflow is
disclosed, never silently dropped.

**First-attempt vs final pass rate** — unit: logical run. Per day
(first-attempt finish day): `first` = share of terminal head attempts
with outcome `passed`; `final` = share of the same cohort whose final
resolved attempt passed. Hover shows passed/total and the retry count.
Run-level metric — not comparable with the case-level pass-rate chart
on the project dashboard.

**Queue wait & turnaround** — unit: dispatchable attempt
(`role in ("", "unit")`; `role="parent"` rows own no process and are
excluded). Queue wait = `started_at − created_at`, included only when
both timestamps exist. Turnaround = `finished_at − created_at`.
**Instrumentation note:** there is no dedicated "results-ready"
timestamp — collection/normalization completes inside the terminal
transition, so `finished_at` is the closest honest bound and the metric
is labelled "enqueue → finished", not "results ready". Median and p95
per enqueue day; days with <1 sample show no point.

### Project Dashboard

**Test-result history** — unit: test case × execution attempt.
**Columns are attempts**, not logical runs: the 20 most recent
terminal attempts matching the active page filters
(suite/status/source-ref/environment), each labelled
`finished day · execution-id`. A retry is its own execution row, so a
retried run appears as multiple columns — no cross-attempt merging.
The column's attempt number and full execution id are in the hover and
the data table; clicking a cell opens that exact attempt's evidence.
Rows: case identities — `case_ref` when present, else `case_name`;
when the suite filter is "all", identities are prefixed with the suite
name so cases from different suites cannot collide. Cell color AND
letter (P/F/E/S) encode the case status in that attempt — never color
alone. Hover: revision, environment, attempt number, status, duration.
**Missing results stay missing**: a case absent from a run renders an
empty cell — it is never drawn as skipped or passed.

**Suite-duration distribution** — unit: **logical-run wall-clock
elapsed time**, `finished_at − started_at` of the final resolved
attempt. For an ordinary run that is the attempt's own span; for a
partitioned run it is the *parent record's* span — the parent stamps
`started_at` when its first unit leaves the queue and `finished_at`
when all units reach terminal state. Child-unit durations are **never
summed**: units are excluded from the distribution, so a partitioned
run contributes exactly one sample (its wall clock), and parallel
children cannot inflate it. Every attempt counts once (consistent
with the existing duration chart — reruns are separate attempts).
Box plot per suite, max 12 suites by sample count (ties broken by
suite name); the data table and CSV list the same contributing
executions the boxes are drawn from.

**Environment comparison** — suite × environment heatmap.
Selectable metric:
- *case pass rate* — `passed/(passed+failed+error)` over `TestResult`
  rows in the cell; skipped cases excluded from the denominator (same
  formula as the existing case pass-rate chart),
- *run pass rate* — share of terminal logical runs whose final
  resolved attempt passed,
- *median duration* — median logical-run duration in seconds.
`environment=NULL` runs form a labeled "(unset)" column — never
silently merged. Cell hover shows the sample counts. Sequential
blue scale — distinct from the outcome palette so magnitudes are not
read as pass/fail. Bounded to 12 suite rows × 8 environment columns.

## Display bounds — deterministic selection and omitted records

Bounds are **display limits, not aggregation limits**: every cell,
row and CSV value is computed over the full in-window dataset; only
which series/rows render is capped. Chart, data table and CSV always
describe the *same* bounded scope — a subset never appears as a total.

| Bound | Selection (deterministic) | Reaching omitted records |
|---|---|---|
| 30 projects (comparison) | most in-window terminal runs, then name | narrow the period, or per-project dashboards |
| 40 case rows (history) | the 40 most recently first-seen cases | filter by suite/status/env |
| 20 run columns (history) | latest 20 terminal attempts by finish time | same — filters select the cohort |
| 12 suites (box plot) | most samples, then suite name | filter by suite |
| 12×8 env matrix | first suites/envs alphabetically | filter by suite/environment |

Truncation is disclosed on the card when active. The CSV exports the
bounded scope shown — the flags in the JSON payload
(`*_truncated`) mark when it applied.

## Drill-through mapping

- **Outcome-comparison segment** → `/executions?project_id&outcome&final=1&from_date&to_date` — `final=1` makes the list show only final resolved attempts, i.e. exactly the logical runs the segment counts.
- **Environment cell** → `/executions?project_id&suite_id&environment&final=1` — the final resolved attempts that produced the cell's run metrics; case-level metrics derive from those same runs' results.
- **History cell** → `/executions/<id>` — the exact attempt (unambiguous).
- **Queue-chart point** → `/executions?from_date&to_date&role=dispatch` — that day's enqueue cohort of dispatchable attempts; the median/p95 sample additionally requires both timestamps, which the list cannot express (documented difference, not a silent filter).
- **First-vs-final chart** — intentionally no click-through: the cohort is defined by the *first* attempt's finish day, which ordinary list filters cannot express ("final attempts whose chain head finished on day X"). A list filtered by final-attempt day would show a *different* cohort — showing that silently would be wrong.

## Missing data

Any series with zero eligible samples renders an explicit
"insufficient data"/N/A state — never a fabricated zero or a guessed
value. Bounds are disclosed on the card when truncation applies.

## Access control

Aggregation is scoped by the requesting user's role and project
membership (`User.project_allowed`), identical to the Executions list:
non-admins see only assigned projects — an empty membership yields
empty analytics, not 'all'. The same scope applies to chart JSON,
hover detail, data tables, CSV export, and every drill-through link.
Runner/worker identity stays off shared charts (admin surface).
