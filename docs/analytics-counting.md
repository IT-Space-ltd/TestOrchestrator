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
Columns: the 20 most recent terminal attempts matching the active page
filters (suite/status/source-ref/environment). Rows: case identities —
`case_ref` when present, else `case_name`; when the suite filter is
"all", identities are prefixed with the suite name so cases from
different suites cannot collide. Cell color AND letter (P/F/E/S)
encode the case status in that attempt — never color alone. Hover:
revision, environment, attempt number, outcome, duration. Missing cell
= the case was not present in that run (empty, distinct from skipped).
Bounded: 40 case rows × 20 run columns; overflow is disclosed.

**Suite-duration distribution** — unit: logical run duration
(`finished_at − started_at`), `role="unit"` children excluded so a
partitioned run's wall clock is counted once, at its parent. Every
attempt counts once (consistent with the existing duration chart —
reruns are separate attempts). Box plot per suite, max 12 suites by
sample count; contributing executions available via the data table.

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
