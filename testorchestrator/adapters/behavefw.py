"""Behave Framework execution adapter.

``build_args`` shapes the argv launched under the configured
interpreter on a worker or SSH target:

    python -m behave --junit --junit-directory Reports/junit
        <feature-or-path:line>...

Selectors: feature file paths run the whole file; ``path:LINE``
runs a single scenario/outline (behave's native selector — exact).
Outputs land under Reports/ so the shared collect path finds junit
untouched. ``classify_exit`` maps behave exit codes so a usage
error or unmatched steps surface as config/test failure — never a
passing zero-test run.
"""

KIND = "behave"


def build_args(targets=(), tags=(), dry_run: bool = False) -> list:
    """argv after the interpreter. ``targets`` are feature paths or
    ``path:LINE`` scenario selectors; ``tags`` map to
    ``--tags=expr``; ``dry_run`` performs collection without running
    steps (native-collection mode — worker-side only)."""
    args = ["-m", "behave",
            "--junit", "--junit-directory", "Reports/junit"]
    if dry_run:
        args += ["--dry-run", "--no-skipped", "-f", "plain"]
    for t in tags:
        args += ["--tags", t]
    for t in targets:
        args.append(t)
    return args


def collect_args(targets=()) -> list:
    """Native-collection argv — lists scenarios without executing
    steps. Output is parsed worker-side and returned as inventory."""
    return ["-m", "behave", "--dry-run", "--no-skipped",
            "-f", "steps.catalog", "--no-summary"] + list(targets)


def classify_exit(rc: int) -> tuple:
    """(severity, label) for a behave process exit status.

    behave exits 0 on all-passed, 1 on test failures, 2 on usage
    errors, 100 on pending/undefined steps, 101 on user interrupt.
    """
    labels = {
        0: ("ok", "all scenarios passed"),
        1: ("tests", "scenarios failed"),
        2: ("config", "usage error"),
        100: ("tests", "undefined or pending steps"),
        101: ("interrupted", "execution interrupted"),
    }
    if rc in labels:
        return labels[rc]
    return "internal", f"unexpected exit status {rc}"


def probe_scripts(app_url: str = "") -> dict:
    """Readiness probe — same python-family contract as pytest
    ($PYBIN interpreter, REQUIRED_LIBS import checks) with the
    `behave` module as the kind check."""
    from . import pytestfw
    return {name: text.replace("pytest", "behave")
            for name, text in
            pytestfw.probe_scripts(app_url).items()}


def probe_argv(os_arch: str) -> list:
    from . import pytestfw
    return pytestfw.probe_argv(os_arch)
