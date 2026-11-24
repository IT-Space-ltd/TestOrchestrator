"""Artifact capture policy (§storage-5).

Three distinct stages — the UI and enforcement must never conflate
them:

- **Generation** — the framework creates the file on the worker.
  Collection toggles do NOT prevent generation; where a framework
  supports generation-time suppression it is wired through the
  adapter's own flags and documented there.
- **Collection** — TestOrchestrator registers, stores, and exposes
  the file. This is what the capture policy controls.
- **Retention/publication** — handled by store retention and the
  (separate, optional) Git publication path.

The policy is snapshotted into every execution's ``run_config`` at
dispatch time — server-side enforcement reads ONLY the snapshot, so
editing the project policy never rewrites a past run's permissions.
``reports`` is a required category: machine-readable results are the
ingestion contract and are never toggleable.
"""

# (key, label, required, privacy_note)
CAPTURE_CATEGORIES = [
    ("reports", "Structured test reports (JUnit, framework JSON)", True,
     "required — machine-readable results are the ingestion contract"),
    ("logs", "Execution logs", False,
     "logs may contain credentials or personal data"),
    ("screenshots", "Screenshots", False,
     "may capture credentials or personal data on screen"),
    ("videos", "Videos", False,
     "may capture credentials or personal data on screen"),
    ("traces", "Traces (HAR / network captures)", False,
     "traces can contain raw API traffic incl. headers and secrets"),
    ("html", "HTML reports", False, ""),
    ("coverage", "Coverage data", False, ""),
    ("extra", "Explicitly permitted additional files", False,
     "broad checkout uploads remain prohibited"),
]

CATEGORY_KEYS = [c[0] for c in CAPTURE_CATEGORIES]

# artifact kind → capture category (kinds assigned by
# results.classify_artifact; "manifest" is internal and always kept).
_KIND_CATEGORY = {
    "junit": "reports",
    "log": "logs",
    "screenshot": "screenshots",
    "video": "videos",
    "har": "traces",
    "html": "html",
    "other": "extra",
}

_COVERAGE_SUFFIXES = (".lcov", ".cov", ".coverage")


def category_for(rel_path: str, kind: str):
    """Resolve an artifact to its capture category. Path-based
    coverage detection wins over extension classification
    (coverage.xml would otherwise look like a structured report).
    ``manifest`` is internal bookkeeping — not a category."""
    if kind == "manifest":
        return None
    rl = rel_path.replace("\\", "/").lower()
    if (rl.startswith("coverage/") or "/coverage/" in rl
            or rl.endswith(_COVERAGE_SUFFIXES)):
        return "coverage"
    return _KIND_CATEGORY.get(kind, "extra")


def default_policy() -> dict:
    """All categories enabled — matches the historical
    collect-everything behavior for upgraded installs."""
    return {k: True for k in CATEGORY_KEYS}


def normalize_policy(raw) -> dict:
    """Merge a stored/POSTed policy over defaults. ``reports`` is
    required and cannot be disabled — ingestion must not break."""
    policy = default_policy()
    if isinstance(raw, dict):
        for k in CATEGORY_KEYS:
            if k in raw:
                policy[k] = bool(raw[k])
    policy["reports"] = True
    return policy


def policy_allows(policy: dict, rel_path: str, kind: str) -> tuple:
    """(allowed, category) — internal kinds are always allowed."""
    cat = category_for(rel_path, kind)
    if cat is None:
        return True, None
    return bool(policy.get(cat, True)), cat
