"""Execution-level runtime readiness (M16 §5): the second gate above
toolchain availability.

`runner_readiness` proves a TOOLCHAIN exists on the target (interpreter
importable, npx resolvable, workspace writable). That alone is NOT
execution readiness — a version answer does not mean this runtime can
run THIS project's suites and ingest their results. This module
validates the pair (runtime, project) and stamps durable per-pair
evidence inside `runtime.config_json["_exec_ready"]`; dispatch requires
it for non-KRE runtimes.

Checks (all server-side, no repo code loaded onto the target):
  toolchain   positive probe evidence exists and is current
  association project is inside the runtime's allowed_projects scope
  framework   a FrameworkProject exists whose required runtime kind
              equals this runtime's kind (engine/format contract)
  discovery   that framework project's config was validated by
              discovery (discovery_status == ok — the revision check
              itself stays at item dispatch)
  engine      postman: a supported engine is configured
  permissions probe recorded the workspace as writable for the
              run account
  plugin      cypress: binary available to the worker account
  ingestion   the project's capture policy retains the machine-
              readable report contract (junit/structured reports)
"""
import json
from datetime import datetime, timezone

from .dispatch import FRAMEWORK_RUNTIME
from .extensions import db
from .execution import FrameworkProject, utcnow

_EVIDENCE_KEY = "_exec_ready"

_ENGINE_KINDS = {"postman": ("newman", "postman-cli")}


def pair_evidence(rt, project_id: str) -> dict:
    cfg = rt.config()
    ev = cfg.get(_EVIDENCE_KEY) or {}
    return ev.get(project_id) or {}


def execution_ready(rt, project_id: str) -> bool:
    """True when the runtime holds current per-project validation
    evidence. KRE runtimes are not gated here (existing flow)."""
    if (rt.runtime_kind or "kre") == "kre":
        return True
    return rt.readiness_state == "ready-execution" and \
        bool(pair_evidence(rt, project_id))


def _probe(rt) -> dict:
    try:
        return json.loads(rt.probe_json or "{}")
    except (ValueError, TypeError):
        return {}


def checks_for(rt, project) -> list:
    """Evaluate the pair checks. Returns [(name, ok, detail)]."""
    kind = rt.runtime_kind or "kre"
    out = []

    # project-validation-required can only be reached AFTER a
    # positive probe — it counts as toolchain-verified evidence so a
    # fixed project can re-validate without re-probing the target.
    ready_states = ("ready-discovery", "ready-execution",
                    "project-validation-required")
    out.append(("toolchain", rt.readiness_state in ready_states,
                f"state={rt.readiness_state} — a positive toolchain "
                "probe is required first"))

    try:
        allowed = json.loads(rt.allowed_projects or "[]")
    except (ValueError, TypeError):
        allowed = []
    assoc = not allowed or project.id in allowed
    out.append(("association", assoc,
                "project must be associated with the runtime"))

    fps = FrameworkProject.query.filter_by(
        project_id=project.id).all()
    matching = [fp for fp in fps
                if FRAMEWORK_RUNTIME.get(fp.framework) == kind]
    out.append(("framework", bool(matching),
                f"no validated {kind} framework project exists — "
                "the engine/format contract requires one"))

    validated = [fp for fp in matching if fp.discovery_status == "ok"]
    out.append(("discovery", not matching or bool(validated),
                "framework project configuration has not been "
                "validated by discovery"))

    engine_ok = True
    engine_detail = ""
    if kind in _ENGINE_KINDS:
        engines = _ENGINE_KINDS[kind]
        for fp in matching:
            engine = (fp.settings() or {}).get("engine") or \
                rt.config().get("engine") or ""
            if engine not in engines:
                engine_ok = False
                engine_detail = (f"{fp.name}: engine "
                                 f"{engine or 'unset'!r} — supported: "
                                 f"{', '.join(engines)}")
                break
    if not engine_ok:
        out.append(("engine", False, engine_detail))

    probe = _probe(rt)
    ws = probe.get("workspace_write")
    out.append(("permissions", ws in (None, "ok"),
                "workspace not writable for the run account "
                "(probe evidence)"))

    if kind == "cypress":
        out.append(("plugin",
                    probe.get("cypress_binary", "ok") == "ok",
                    "Cypress binary not available to the worker "
                    "account"))

    out.append(("ingestion",
                (project.capture_policy() or {}).get("reports", True),
                "machine-readable report capture is disabled — "
                "results could not be ingested"))

    return out


def validate_project(rt, project, actor: str = "system") -> list:
    """Run the pair checks; on success stamp per-pair evidence and
    lift the runtime to ready-execution. Returns the failed check
    details ([] = ready)."""
    if (rt.runtime_kind or "kre") == "kre":
        return []
    checks = checks_for(rt, project)
    failed = [f"{name}: {detail}" for name, ok, detail in checks
              if not ok]
    cfg = dict(rt.config())
    ev = dict(cfg.get(_EVIDENCE_KEY) or {})
    if failed:
        ev.pop(project.id, None)
        cfg[_EVIDENCE_KEY] = ev
        rt.config_json = json.dumps(cfg)
        remaining = [e for pid, e in ev.items() if e]
        if remaining:
            rt.readiness_state = "ready-execution"
        elif rt.readiness_state in ("ready-discovery",
                                    "ready-execution",
                                    "project-validation-required"):
            # Pair-level failure on an otherwise verified toolchain.
            # Negative toolchain states keep their own verdict —
            # masking "missing-dependency" would be misleading.
            rt.readiness_state = "project-validation-required"
        rt.last_diagnostic = (
            f"{rt.runtime_kind} execution readiness: not ready — "
            + "; ".join(failed))[:2000]
    else:
        _stamp(rt, project.id,
               [name for name, ok, _ in checks])
        rt.last_diagnostic = (
            f"{rt.runtime_kind} execution readiness: ready for "
            f"{project.name!r} — toolchain + project checks passed")
    rt.last_check_at = utcnow()
    db.session.commit()
    from .models import record_audit
    record_audit(actor, "runtime.exec_validate",
                 f"{rt.id} x {project.id}: "
                 f"{'ready' if not failed else 'FAILED ' + '; '.join(failed)}"
                 [:500])
    return failed


def _stamp(rt, project_id: str, checks: list) -> None:
    """Write the per-pair evidence record — the single writer used by
    validate_project. Tests seed validated preconditions through this
    seam rather than hand-editing config_json."""
    cfg = dict(rt.config())
    ev = dict(cfg.get(_EVIDENCE_KEY) or {})
    ev[project_id] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
    cfg[_EVIDENCE_KEY] = ev
    rt.config_json = json.dumps(cfg)
    rt.readiness_state = "ready-execution"


def clear_evidence(rt) -> None:
    """Probe re-runs, profile edits, and association changes revoke
    pair evidence — toolchains and scopes are no longer the ones the
    validation was recorded against."""
    cfg = dict(rt.config())
    if cfg.pop(_EVIDENCE_KEY, None) is not None:
        rt.config_json = json.dumps(cfg)


def prune_projects(rt) -> None:
    """Association edit: drop validation for projects that left the
    runtime's scope; demote the display state if none remain."""
    cfg = dict(rt.config())
    ev = dict(cfg.get(_EVIDENCE_KEY) or {})
    if not ev:
        return
    try:
        allowed = json.loads(rt.allowed_projects or "[]")
    except (ValueError, TypeError):
        allowed = []
    keep = {pid: e for pid, e in ev.items()
            if not allowed or pid in allowed}
    cfg[_EVIDENCE_KEY] = keep
    rt.config_json = json.dumps(cfg)
    if not keep and rt.readiness_state == "ready-execution":
        rt.readiness_state = "ready-discovery"
