"""Runtime-profile registry for the guided Add Runtime wizard (M16).

Maps each supported NON-KRE framework to the toolchain fields the
wizard shows, contextual examples, and engine choices. KRE is
deliberately absent — the existing Add KRE flow is untouched.

A runtime profile = an approved toolchain + execution settings bound
to one execution target (Runner). It holds reusable settings only;
repository-specific settings stay on the framework project.
"""

# Field kinds rendered by the wizard:
#   path   — absolute path on the TARGET host
#   text   — free text
#   select — fixed choices
#   kv     — approved environment overrides (KEY=VALUE lines)

RUNTIME_PROFILES = {
    "pytest": {
        "label": "pytest",
        "desc": "Python test framework — runs inside a project "
                "checkout on the target via the configured "
                "interpreter.",
        "fields": [
            ("python_env", "path", "Python executable or virtualenv",
             "Example: /opt/test-env/bin/python — required packages "
             "must already be installed in this environment."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines applied to collection and "
             "execution."),
        ],
    },
    "pytest-bdd": {
        "label": "pytest-bdd",
        "desc": "BDD via pytest — collection and execution run "
                "through pytest in the configured environment.",
        "fields": [
            ("python_env", "path", "Python executable or virtualenv",
             "Example: /opt/test-env/bin/python — pytest and "
             "pytest-bdd must be installed there."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "behave": {
        "label": "Behave",
        "desc": "BDD framework — feature files resolved by the "
                "project; the interpreter carries behave + step "
                "dependencies.",
        "fields": [
            ("python_env", "path", "Python executable or virtualenv",
             "Example: /opt/test-env/bin/python — behave must be "
             "installed there."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "robot": {
        "label": "Robot Framework",
        "desc": "Keyword-driven framework — runs via the configured "
                "Python interpreter (-m robot).",
        "fields": [
            ("python_env", "path", "Python executable or virtualenv",
             "Example: /opt/robot-venv/bin/python — robotframework "
             "must be installed there."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "jest": {
        "label": "Jest",
        "desc": "Node.js test runner — resolved project-locally; "
                "dependencies must already be installed in the "
                "checkout.",
        "fields": [
            ("node_bin", "path", "Node.js executable (optional)",
             "Example: /usr/bin/node — used to resolve the "
             "project-local jest binary; leave empty to use PATH."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "playwright": {
        "label": "Playwright Test — JavaScript/TypeScript",
        "desc": "Node.js Playwright Test — resolved project-locally; "
                "matching browsers must be installed on the target.",
        "fields": [
            ("node_bin", "path", "Node.js executable (optional)",
             "Example: /usr/bin/node — leave empty to use PATH."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "playwright-pytest": {
        "label": "Playwright — Python/pytest",
        "desc": "Playwright through the pytest plugin — runs in the "
                "configured Python environment with "
                "pytest-playwright installed; browsers on target.",
        "fields": [
            ("python_env", "path", "Python executable or virtualenv",
             "Choose the environment containing the approved pytest "
             "and Playwright integration."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "cypress": {
        "label": "Cypress",
        "desc": "Node.js Cypress — package + binary resolved from "
                "the project; browser availability checked on the "
                "target.",
        "fields": [
            ("node_bin", "path", "Node.js executable (optional)",
             "Example: /usr/bin/node — leave empty to use PATH."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "gtest": {
        "label": "GoogleTest",
        "desc": "C/C++ test binaries — prebuilt executable or an "
                "approved build-and-run mode configured per "
                "project.",
        "fields": [
            ("exec_path", "path", "Prebuilt test executable (optional)",
             "Example: build/tests/unit_tests — repository-relative "
             "path on the target; blank = project supplies it."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines. GTEST_* settings that affect "
             "execution are scrubbed unless explicitly approved."),
        ],
    },
    "postman": {
        "label": "Postman",
        "desc": "Postman collections — the engine choice determines "
                "supported formats: Newman runs v2.1 JSON "
                "collections only; Postman CLI runs native-git v3 "
                "YAML.",
        "engine_field": (
            "engine", "Engine",
            [("newman", "Newman — v2.1 JSON collections"),
             ("postman-cli", "Postman CLI — v3 native-git YAML "
              "collections")]),
        "fields": [
            ("exec_path", "path", "Engine executable (optional)",
             "Absolute path on the target, e.g. "
             "/usr/local/bin/newman — blank resolves via "
             "npx --no-install (never downloads)."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
    "bruno": {
        "label": "Bruno",
        "desc": "Bruno collections — the bru CLI runs from the "
                "collection root; safe sandbox is the default.",
        "fields": [
            ("exec_path", "path", "bru CLI executable (optional)",
             "Example: /usr/local/bin/bru — blank resolves via "
             "PATH/npx --no-install."),
            ("sandbox", "select", "Sandbox policy",
             "safe is the default. developer_mode is configuration, "
             "not authorization — recorded and shown on every run."),
            ("env", "kv", "Approved environment overrides",
             "Optional KEY=VALUE lines."),
        ],
    },
}

# runtime_kind on RuntimeConnection rows comes from
# dispatch.FRAMEWORK_RUNTIME (framework → shared runtime kind) —
# several frameworks share one toolchain kind (pytest-bdd and
# playwright-pytest both run on a "pytest" profile).

# Structured readiness states (M16 §5).
READINESS_STATES = (
    "not-checked", "checking", "ready-discovery",
    "ready-execution", "project-validation-required",
    "missing-dependency", "unsupported-version",
    "target-unavailable", "evidence-stale",
)


def profile(framework: str) -> dict:
    return RUNTIME_PROFILES.get(framework)


def sandbox_choices():
    return [("safe", "safe (default — scripts cannot run)"),
            ("developer_mode", "developer_mode (explicit opt-in — "
             "recorded, never automatic)")]
