"""Git persistence (§10–§11).

Two directions, both through the git_backend facade (no custom Git
transport, no GitPython):

1. Source bindings — clone/fetch Katalon repositories into per-binding
   worktrees for read-only indexing. The worktree keeps its .git so
   updates stay incremental; project code is never executed during
   indexing and submodules are not auto-initialized (LFS/submodule
   policies remain explicit).

2. Destination export — versioned definitions and permitted actual
   reports/evidence under `TestOrchestrator/` in a configured repository.
   Local DB stays authoritative; export state is per-execution
   (saved/pending/pushed/conflict/failed). Secrets, users, sessions,
   private keys, licences, and the live DB are NEVER exported — the writer
   whitelists artifact kinds rather than filtering after the fact.
"""

import json
import shutil
from pathlib import Path

from . import git_backend
from . import settings as settings_mod
from .execution import Execution, GitBinding, utcnow
from .extensions import db

EXPORT_ROOT = "TestOrchestrator"


class NotConfigured(RuntimeError):
    pass


class SyncError(RuntimeError):
    pass


# ---------- credentials (§12) -----------------------------------------

def _binding_auth(binding: GitBinding):
    """Resolve the binding's SecretRef to an https (user, pass) pair.

    Secret format: 'user:password' splits at the first colon; a bare
    token maps to (token, '') — the PAT-as-username convention. SSH URLs
    rely on the host ssh/agent (dulwich subprocess ssh, or system ssh via
    the cli backend) — no password is ever placed on the URL."""
    if not binding.credential_ref:
        return None
    url = (binding.url or "").lower()
    if not url.startswith("http://") and not url.startswith("https://"):
        return None
    try:
        from flask import current_app
        from .secrets_store import SecretError, read_secret
        secret = read_secret(current_app._get_current_object(),
                             binding.credential_ref)
    except SecretError as exc:
        raise SyncError(f"credential {binding.credential_ref!r}: {exc}")
    if ":" in secret:
        return tuple(secret.split(":", 1))
    return (secret, "")


# ---------- source binding indexing ----------

def binding_worktree(binding_id: str) -> Path:
    from flask import current_app
    return Path(current_app.instance_path) / "bindings" / binding_id


def sync_binding(binding_id: str) -> dict:
    """Clone or fetch a source binding and record the resolved SHA.

    Indexing is read-only: file listing + .prj discovery only. No build
    steps, hooks, or project code are executed (§11)."""
    binding = db.session.get(GitBinding, binding_id)
    if binding is None:
        raise SyncError(f"unknown binding {binding_id}")
    worktree = binding_worktree(binding_id)
    try:
        auth = _binding_auth(binding)
        if worktree.exists() and (worktree / ".git").exists():
            # Selected backend update — failure surfaces honestly, never
            # a silent fallback to the other backend (§8).
            git_backend.run("update", worktree, binding.ref or "",
                            auth=auth)
        else:
            worktree.parent.mkdir(parents=True, exist_ok=True)
            git_backend.run("clone", binding.url, worktree,
                            branch=binding.ref or None, depth=1,
                            auth=auth)
        sha = git_backend.run("resolve", worktree, "HEAD")
        binding.worktree_path = str(worktree)
        binding.last_synced_sha = sha
        binding.status = "synced"
        binding.last_error = ""
        db.session.commit()
        discover_project(binding)          # non-fatal to sync status
        return {"sha": sha, "worktree": str(worktree)}
    except Exception as exc:
        binding.status = "failed"
        binding.last_error = str(exc)[:2000]
        db.session.commit()
        raise SyncError(f"git sync failed: {exc}") from exc


def list_test_cases(binding: GitBinding) -> list:
    """Repo-relative case paths under the bound project — used by the suite
    builder/import. Read-only listing, never content execution."""
    if not binding.worktree_path:
        return []
    base = Path(binding.worktree_path)
    if binding.subdirectory:
        base = base / binding.subdirectory
    cases_dir = base / "Test Cases"
    root = cases_dir if cases_dir.exists() else base
    return sorted(
        str(p.relative_to(base)) for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    )


def list_test_suites(binding: GitBinding) -> list:
    if not binding.worktree_path:
        return []
    base = Path(binding.worktree_path)
    if binding.subdirectory:
        base = base / binding.subdirectory
    suites_dir = base / "Test Suites"
    if not suites_dir.exists():
        return []
    return sorted(
        str(p.relative_to(base)) for p in suites_dir.rglob("*.ts")
        if p.is_file()
    )


# ---------- destination export (§11 layout) ----------

def _export_repo() -> Path:
    """The export repository path — created on first use, .git always
    preserved (commits/merges/pushes need real history). Repo-local
    identity is configured for product commits (never global config)."""
    path = settings_mod.get("git_export_repo") or ""
    if not path:
        raise NotConfigured("git_export_repo is not configured")
    repo_path = Path(path)
    git_backend.run("init", repo_path)
    git_backend.run("identity", repo_path,
                    git_backend.IDENTITY_NAME, git_backend.IDENTITY_EMAIL)
    return repo_path


def _commit(repo_path: Path, message: str) -> str:
    return git_backend.run("commit_all", repo_path, message)


# Whitelist: only these artifact kinds are exportable (§11 evidence policy).
EXPORTABLE_KINDS = {"junit", "log", "screenshot", "html"}


def _serializable(value):
    import enum
    if isinstance(value, enum.Enum):
        return value.value
    return value


def export_execution(execution: Execution) -> dict:
    """Write snapshot/summary/results/reporting + permitted evidence under
    TestOrchestrator/projects/<project-id>/executions/<execution-id>/."""
    repo_path = _export_repo()
    base = (repo_path / EXPORT_ROOT / "projects"
            / execution.project_id / "executions" / execution.id)
    base.mkdir(parents=True, exist_ok=True)

    (base / "snapshot.json").write_text(
        json.dumps(execution.snapshot(), indent=2), encoding="utf-8")
    (base / "summary.json").write_text(json.dumps({
        "execution_id": execution.id,
        "suite_id": execution.suite_id,
        "state": execution.state.value,
        "outcome": execution.outcome.value,
        "source_sha": execution.source_sha,
        "created_by": execution.created_by,
        "created_at": execution.created_at.isoformat()
        if execution.created_at else "",
        "started_at": execution.started_at.isoformat()
        if execution.started_at else "",
        "finished_at": execution.finished_at.isoformat()
        if execution.finished_at else "",
        "exit_status": execution.exit_status,
        "schema": 1,
    }, indent=2), encoding="utf-8")
    (base / "results.json").write_text(json.dumps([
        {
            "case_ref": r.case_ref, "case_name": r.case_name,
            "classname": r.classname, "status": r.status.value,
            "duration_s": r.duration_s, "iteration": r.iteration,
            "attempt": r.attempt, "unresolved": r.unresolved,
            # Failure text is evidence; secrets are never stored in results.
            "message": r.message[:2000],
        } for r in execution.results
    ], indent=2), encoding="utf-8")
    (base / "reporting.json").write_text(json.dumps({
        "artifacts": [
            {
                "rel_path": a.rel_path, "kind": a.kind,
                "sha256": a.sha256, "size": a.size,
            } for a in execution.artifacts
        ],
        "schema": 1,
    }, indent=2), encoding="utf-8")

    report_root = Path(execution.report_dir) if execution.report_dir else None
    for artifact in execution.artifacts:
        if artifact.kind not in EXPORTABLE_KINDS:
            continue  # HAR/video/debug capture stays local (safety policy)
        if not report_root:
            continue
        src = report_root / artifact.rel_path
        if not src.is_file():
            continue
        dest_dir = base / "evidence" / artifact.kind
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(artifact.rel_path).name
        shutil.copy2(src, dest)
        # Verify integrity on copy — evidence must match its checksum.
        from .results import sha256_file
        if sha256_file(dest) != artifact.sha256:
            dest.unlink(missing_ok=True)
            raise SyncError(
                f"checksum mismatch exporting {artifact.rel_path}"
            )

    sha = _commit(repo_path, f"execution {execution.id} evidence")
    return {"commit": sha, "path": str(base)}


def export_definitions(project) -> dict:
    """Versioned suite/plan/release definitions under the project dir."""
    repo_path = _export_repo()
    base = repo_path / EXPORT_ROOT / "projects" / project.id
    for name, rows in (
        ("suites", project.suites),
        ("plans", project.plans),
        ("releases", project.releases),
    ):
        out = base / name
        out.mkdir(parents=True, exist_ok=True)
        for row in rows:
            data = {
                c.name: _serializable(getattr(row, c.name))
                for c in row.__table__.columns
            }
            (out / f"{row.id}.json").write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8")
    sha = _commit(repo_path, f"project {project.id} definitions")
    return {"commit": sha, "path": str(base)}


# ---------- push, conflict handling, restore ----------

def push_export(credential_ref: str = "") -> str:
    """Push the export repo to its configured remote (§11). Reconciles
    external edits via fetch+merge — NEVER force-push. Returns a status
    string; conflicts surface honestly rather than being overwritten."""
    repo_path = _export_repo()
    if not git_backend.run("has_remote", repo_path):
        raise NotConfigured("export repo has no remote 'origin'")
    auth = _remote_auth(credential_ref)
    branch = git_backend.run("branch", repo_path)
    refspec = f"HEAD:refs/heads/{branch}"
    git_backend.run("fetch", repo_path, auth=auth)
    if git_backend.run("remote_ref", repo_path, branch):
        # Fast-forward/merge only — conflicts surface, never force-push.
        try:
            git_backend.run("merge", repo_path, branch)
        except git_backend.MergeConflictError as exc:
            raise SyncError(
                "remote has conflicting edits — reconcile manually in "
                f"{repo_path}; automatic force-push is forbidden "
                f"({exc})") from exc
        git_backend.run("push", repo_path, refspec, auth=auth)
    else:
        # First push: establish the upstream branch.
        git_backend.run("push", repo_path, refspec, auth=auth,
                        set_upstream=True)
    return "pushed"


def _remote_auth(credential_ref: str = ""):
    """Export-remote credential: the git_export_credential setting holds a
    SecretRef name; https remotes get (user, pass), ssh relies on the
    host ssh/agent — never embedded in URLs or logs."""
    name = credential_ref or settings_mod.get("git_export_credential", "")
    if not name:
        return None
    try:
        from flask import current_app
        from .secrets_store import SecretError, read_secret
        secret = read_secret(current_app._get_current_object(), name)
    except SecretError as exc:
        raise SyncError(f"credential {name!r}: {exc}")
    if ":" in secret:
        return tuple(secret.split(":", 1))
    return (secret, "")


def restore_definitions(project_id: str) -> dict:
    """Restore suite/plan/release definitions from the export clone (A08).
    Reads exported JSON back into the DB — the inverse of
    export_definitions. Only definition objects are restored; users,
    secrets, sessions, keys and audit data are never in the export."""
    repo_path = _export_repo()
    base = repo_path / EXPORT_ROOT / "projects" / project_id
    if not base.exists():
        raise NotConfigured(f"no exported definitions for {project_id}")

    from .execution import Plan, Release, Suite
    counts = {"suites": 0, "plans": 0, "releases": 0}
    for name, model, counter in (
        ("suites", Suite, "suites"),
        ("plans", Plan, "plans"),
        ("releases", Release, "releases"),
    ):
        src = base / name
        if not src.exists():
            continue
        for path in src.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            row = db.session.get(model, data["id"])
            if row is None:
                row = model(id=data["id"], project_id=project_id)
                db.session.add(row)
            from sqlalchemy import DateTime
            coltypes = {c.name: c.type for c in row.__table__.columns}
            for key, value in data.items():
                if key in ("id", "project_id"):
                    continue
                if hasattr(row, key):
                    try:
                        if isinstance(value, str) and isinstance(
                                coltypes.get(key), DateTime):
                            from datetime import datetime
                            value = datetime.fromisoformat(value)
                        setattr(row, key, value)
                    except (AttributeError, TypeError, ValueError):
                        pass
            counts[counter] += 1
    db.session.commit()
    return counts


# ---------- Katalon project discovery (read-only) ----------

_SKIP_DIRS = {".git", ".cache", "Keywords", "Scripts", "Libs", "bin",
              "build", "Reports", "__pycache__"}
_MAX_FILE = 512 * 1024                       # bound definition sizes


def _xml_root(path):
    """Parse just the root tag — bounded, no external entities."""
    import xml.etree.ElementTree as ET
    try:
        if path.stat().st_size > _MAX_FILE:
            return None, "oversized"
        for _ev, el in ET.iterparse(str(path), events=("start",)):
            return el.tag.split("}")[-1], None
    except Exception as exc:
        return None, f"malformed: {type(exc).__name__}"
    return None, "malformed: empty"


def discover_project(binding, sha: str = "") -> dict:
    """Typed inventory discovery under the selected Katalon project
    root — .prj root detection, .tc cases, suites vs collections by
    XML root tag, profile names. Read-only; never executes repo code.
    Replaces the current inventory ATOMICALLY per SHA; a failure keeps
    the last good set (stale, not destroyed)."""
    from .execution import DiscoveredItem
    import xml.etree.ElementTree as ET
    out = {"cases": 0, "suites": 0, "collections": 0, "profiles": 0,
           "warnings": []}
    sha = sha or binding.last_synced_sha or ""
    try:
        base = Path(binding.worktree_path or "")
        if binding.subdirectory:
            base = base / binding.subdirectory
        if not base.is_dir():
            raise SyncError("bound worktree/subdirectory missing")
        # .prj detection within the bound scope — bounded walk, no
        # symlink escapes outside the checkout.
        prjs = [p for p in base.rglob("*.prj")
                if not any(part.startswith(".") or
                           part in _SKIP_DIRS for part in p.parts)]
        prjs = [p for p in prjs if p.resolve().is_relative_to(
            base.resolve())]                      # containment
        if not prjs:
            raise SyncError("no Katalon .prj file found under the "
                            "bound path — not a Katalon project root")
        if len(prjs) > 1:
            names = [str(p.relative_to(base)) for p in prjs]
            raise SyncError("multiple .prj files — select one "
                            "explicitly: " + ", ".join(names[:5]))
        root = prjs[0].parent
        items = []
        # Cases: .tc under Test Cases/ only (never groovy/scripts)
        tc_dir = root / "Test Cases"
        base_r = base.resolve()
        for p in sorted(tc_dir.rglob("*.tc")) if tc_dir.exists() else []:
            if not p.resolve().is_relative_to(base_r):
                out["warnings"].append(
                    f"{p.relative_to(base)}: symlink escape skipped")
                continue
            rel = str(p.relative_to(root))
            items.append(DiscoveredItem(
                binding_id=binding.id, project_id=binding.project_id,
                sha=sha, kind="case", path=rel,
                name=p.stem, parent=str(p.parent.relative_to(root))))
        # Suites vs collections: content root tag, not filename.
        ts_dir = root / "Test Suites"
        ts_files = (sorted(ts_dir.rglob("*.ts")) +
                    sorted(ts_dir.rglob("*.tsc"))) \
            if ts_dir.exists() else []
        for p in ts_files:
            if not p.resolve().is_relative_to(base_r):
                out["warnings"].append(
                    f"{p.relative_to(base)}: symlink escape skipped")
                continue
            rel = str(p.relative_to(root))
            tag, warn = _xml_root(p)
            if warn:
                out["warnings"].append(f"{rel}: {warn}")
            kind = ("collection" if tag == "TestSuiteCollectionEntity"
                    else "suite")
            dynamic = False
            members = []
            if tag:
                try:
                    r = ET.parse(str(p)).getroot()
                    if kind == "suite":
                        members = [t.text.strip() for t in
                                   r.findall(".//testCaseLink/testCaseId")
                                   if t.text]
                        # Explicit metadata first (authoritative);
                        # name-match is an uncertain heuristic label.
                        explicit = bool(r.findall(".//testCaseRunType"))
                        name_hint = "dynamic" in (
                            r.findtext("name") or "").lower()
                        dynamic = explicit
                        if name_hint and not explicit:
                            warn = (warn or "") + \
                                " name suggests dynamic (unverified)"
                    else:
                        members = [t.text.strip() for t in
                                   r.findall(".//TestSuiteRunConfiguration"
                                             "/testSuiteEntity") if t.text]
                except Exception:
                    warn = (warn or "") + " members unparseable"
            items.append(DiscoveredItem(
                binding_id=binding.id, project_id=binding.project_id,
                sha=sha, kind=kind, path=rel, name=p.stem,
                parent=str(p.parent.relative_to(root)),
                dynamic=dynamic,
                members_json=json.dumps(members),
                warnings=(warn or "")))
            out["suites" if kind == "suite" else "collections"] += 1
        # Profiles: names only — never parse/render values.
        prof_dir = root / "Profiles"
        for p in sorted(prof_dir.rglob("*.glbl")) if prof_dir.exists() else []:
            if not p.resolve().is_relative_to(base_r):
                out["warnings"].append(
                    f"{p.relative_to(base)}: symlink escape skipped")
                continue
            items.append(DiscoveredItem(
                binding_id=binding.id, project_id=binding.project_id,
                sha=sha, kind="profile",
                path=str(p.relative_to(root)), name=p.stem))
            out["profiles"] += 1
        out["cases"] = sum(1 for i in items if i.kind == "case")
        # Atomic replace — but NEVER overwrite a NEWER committed
        # inventory: if a later discovery already persisted a different
        # SHA (and the binding's last fetched sha moved past ours),
        # this late result is stale — keep the newer set.
        if (binding.discovered_sha
                and binding.discovered_sha != sha
                and binding.last_synced_sha != sha):
            binding.discovery_status = "ok"      # newer already fine
            db.session.commit()
            out["stale_skip"] = True
            return out
        DiscoveredItem.query.filter_by(binding_id=binding.id).delete()
        db.session.add_all(items)
        binding.discovered_sha = sha
        binding.discovery_status = ("ok" if items else "none")
        binding.discovery_error = ""
        binding.discovery_at = utcnow()
        binding.project_root = str(root.relative_to(base)) or "."
        db.session.commit()
        return out
    except Exception as exc:
        # Failed discovery: keep prior inventory, mark stale — never
        # erase the last good set.
        binding.discovery_status = "failed"
        binding.discovery_error = str(exc)[:512]
        db.session.commit()
        out["error"] = str(exc)[:512]
        return out


def sync_framework_project(fp, binding, sha: str = "") -> dict:
    """Run the framework adapter for one FrameworkProject and
    persist its inventory atomically. Item rows are keyed on
    (framework_project_id, kind, path, name, granularity) — unchanged
    rows KEEP their id so saved selections/references survive a
    refresh; removed rows are deleted and reported so stale
    selections can be flagged. A failed run keeps the last good
    inventory and marks the project 'failed' (stale, not destroyed).
    Static inspection only — repository code never executes."""
    from .execution import DiscoveredItem
    from .discovery import discover, fingerprint
    out = {"items": 0, "warnings": [], "added": 0, "removed": 0,
           "kept": 0}
    sha = sha or binding.last_synced_sha or ""
    try:
        res = discover(fp, binding)
        out["warnings"] = list(res.warnings)
        fp.discovery_fingerprint = fingerprint(fp)
        if res.warnings and not res.items:
            fp.discovery_status = "failed"
            fp.discovery_error = "; ".join(res.warnings)[:512]
            fp.discovery_warnings_json = json.dumps(
                res.warnings)[:4096]
            db.session.commit()
            out["error"] = fp.discovery_error
            return out

        existing = {(_i.kind, _i.path, _i.name,
                     _i.granularity): _i for _i in
                    DiscoveredItem.query.filter_by(
                        framework_project_id=fp.id)}
        seen = set()
        rows = []
        for it in res.items:
            key = (it.kind, it.path, it.name, it.granularity)
            seen.add(key)
            row = existing.get(key)
            if row is None:
                row = DiscoveredItem(
                    binding_id=binding.id, project_id=fp.project_id,
                    framework_project_id=fp.id, sha=sha,
                    kind=it.kind)
                db.session.add(row)
                out["added"] += 1
            else:
                out["kept"] += 1
            row.path, row.name = it.path, it.name
            row.parent = it.parent
            row.node_id = it.node_id
            row.granularity = it.granularity
            row.selectable = it.selectable
            row.dynamic = it.dynamic
            row.warnings = it.warnings[:512]
            row.tags = it.tags
            row.members_json = json.dumps(it.members)
            row.framework = fp.framework
            row.fingerprint = fp.discovery_fingerprint
            row.sha = sha
            rows.append(row)
        removed = [r for k, r in existing.items() if k not in seen]
        for r in removed:
            db.session.delete(r)
        out["removed"] = len(removed)
        if removed:
            out["warnings"].append(
                f"{len(removed)} previously discovered item(s) no "
                "longer exist — saved selections referencing them "
                "are stale")
        fp.discovery_status = "ok" if rows else "none"
        fp.discovery_error = ""
        fp.discovery_warnings_json = json.dumps(res.warnings)[:4096]
        fp.discovery_at = utcnow()
        fp.discovered_sha = sha
        db.session.commit()
        out["items"] = len(rows)
        out["method"] = res.method
        out["needs_native"] = res.needs_native
        out["effective"] = res.effective
        return out
    except Exception as exc:
        fp.discovery_status = "failed"
        fp.discovery_error = str(exc)[:512]
        fp.discovery_warnings_json = json.dumps([str(exc)])[:4096]
        db.session.commit()
        out["error"] = str(exc)[:512]
        return out


def request_native_collection(fp, binding, runtime,
                              username: str = "") -> object:
    """Queue an isolated native-collection run: the framework's own
    collector executes on the chosen worker/SSH target inside the
    staged checkout and returns Reports/collect.json. This is the
    approved path where repository code may execute — bounded by
    the same timeout/retry/collect pipeline as real runs. Returns
    the Execution (state queued)."""
    from .dispatch import create_execution, FRAMEWORK_RUNTIME
    want = FRAMEWORK_RUNTIME.get(fp.framework, "")
    got = getattr(runtime, "runtime_kind", "") if runtime else ""
    if want and got != want:
        raise ValueError(
            f"{fp.framework} collection requires a {want!r} "
            f"runtime (selected {got or 'unknown'!r})")
    roots = (fp.test_roots() or fp.feature_roots() or ["."])
    # Framework execution settings travel with the collect run the same
    # way they do for item dispatches (_fp_item_gate) — gtest needs
    # executables/build_dir to resolve the binaries to list.
    rc = {"native_collect": True, "fp_id": fp.id,
          "collect_roots": roots,
          "runtime_id": runtime.id if runtime else "",
          "timeout_seconds": 900}
    if fp.framework not in rc:
        rc[fp.framework] = dict(fp.settings() or {})
    ex = create_execution(
        username or "system", binding=binding,
        source_sha=binding.last_synced_sha or "",
        run_config=rc)
    return ex


def apply_native_inventory(ex, collect_path) -> dict:
    """Reconcile Reports/collect.json into the framework project's
    inventory: native items get exact selectable node_ids; static
    candidates confirmed by collection are upgraded; rows not seen
    natively stay (static preview may cover things collection
    can't run). Records discovery provenance (sha + fingerprint +
    adapter + method=native)."""
    from .execution import DiscoveredItem, FrameworkProject
    from .discovery import fingerprint
    rc = (ex.snapshot().get("run_config") or {})
    fp = db.session.get(FrameworkProject, rc.get("fp_id") or "")
    if fp is None:
        return {"error": "framework project gone"}
    try:
        doc = json.loads(collect_path.read_text() or "{}")
    except Exception as exc:
        return {"error": f"collect.json unreadable: {exc}"}
    items = doc.get("items") or []
    warnings = doc.get("warnings") or []
    if doc.get("noop"):
        # By-design no-op collector (cypress has no native list
        # command): informational only — never touches inventory or
        # discovery status, so a collect run cannot poison the
        # dispatch gate. The warning is still surfaced on the run.
        fp.discovery_warnings_json = json.dumps(warnings)[:4096]
        db.session.commit()
        return {"items": 0, "added": 0, "upgraded": 0,
                "warnings": warnings, "noop": True}
    sha = ex.source_sha or ""
    fp.discovery_fingerprint = fingerprint(fp)
    existing = {(i.kind, i.path, i.name): i for i in
                DiscoveredItem.query.filter_by(
                    framework_project_id=fp.id)}
    added = upgraded = 0
    for it in items:
        key = (it.get("kind", ""), it.get("path", ""),
               it.get("name", ""))
        row = existing.get(key)
        if row is None:
            row = DiscoveredItem(
                binding_id=fp.binding_id, project_id=fp.project_id,
                framework_project_id=fp.id, sha=sha,
                kind=it.get("kind", "test"))
            db.session.add(row)
            added += 1
        else:
            upgraded += int(not row.selectable)
        row.path = it.get("path", "")
        row.name = it.get("name", "")
        row.parent = it.get("parent", "") or ""
        row.node_id = it.get("node_id", "") or ""
        row.granularity = it.get("granularity", "test")
        row.selectable = bool(it.get("node_id"))
        row.tags = ",".join(it.get("tags") or [])
        row.warnings = (it.get("warnings") or "")[:512]
        row.framework = fp.framework
        row.fingerprint = fp.discovery_fingerprint
        row.sha = sha
        row.item_type = "native"
    fp.discovery_status = "ok" if items else "failed"
    fp.discovery_error = "" if items else "; ".join(
        warnings)[:512] or "collection produced no items"
    fp.discovery_warnings_json = json.dumps(warnings)[:4096]
    fp.discovery_at = utcnow()
    fp.discovered_sha = sha
    db.session.commit()
    return {"items": len(items), "added": added,
            "upgraded": upgraded, "warnings": warnings}


# ---------- report publication + synchronized deletion ----------

REPORT_ROOT = "TestOrchestrator/Reports"


import contextlib

@contextlib.contextmanager
def _pub_lock(binding_id: str):
    """Single-worker model: report publish/delete ops serialize on a
    cross-process file lock per binding — a second worker blocks, it
    cannot race a publisher or deleter."""
    import fcntl
    from flask import current_app
    lf = (Path(current_app.instance_path) / "reports-pub" /
          binding_id)
    lf.mkdir(parents=True, exist_ok=True)
    fh = open(lf / ".pub.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _pub_worktree(binding_id: str, op_id: str = "") -> Path:
    """Separate publication checkout — never the fetch or authoring
    worktree. Per-operation subdir isolates concurrent publishers."""
    from flask import current_app
    base = Path(current_app.instance_path) / "reports-pub" / binding_id
    return base / (op_id or "shared")


def _report_dir(ex) -> str:
    return f"{REPORT_ROOT}/{ex.id}"


def _build_manifest(ex) -> dict:
    snap = ex.snapshot()
    return {
        "version": 1, "execution_id": ex.id,
        "project_id": ex.project_id,
        "binding_id": ex.binding_id or "",
        "source_sha": ex.source_sha,
        "suite_path": snap.get("run_config", {}).get("suite_path", ""),
        "collection": snap.get("run_config", {}).get("collection",
                                                     False),
        "created_at": str(ex.created_at),
        "finished_at": str(ex.finished_at),
        "outcome": ex.outcome.value if ex.outcome else "",
        "state": ex.state.value if ex.state else "",
        "report_format": "junit+assets",
        "incomplete": ex.state and ex.state.value != "completed",
    }


def publish_report(execution_id: str) -> dict:
    return _publish_report_locked(execution_id)


def _publish_report_locked(execution_id: str) -> dict:
    """Publish the finalized report tree to
    TestOrchestrator/Reports/<id>/ on the binding's writable branch —
    idempotent by digest: unchanged content skips the push."""
    from .execution import Execution
    ex = db.session.get(Execution, execution_id)
    if ex is None:
        return {"error": "unknown execution"}
    if ex.deletion_status != "none":
        return {"error": "deletion requested — publication blocked"}
    binding = (db.session.get(GitBinding, ex.binding_id)
               if ex.binding_id else None)
    if binding is None:
        ex.report_pub_status = "failed"
        ex.report_pub_error = "no source binding"
        db.session.commit()
        return {"error": "no source binding"}
    with _pub_lock(binding.id):
        return _publish_report_inner(ex, binding)


def _publish_report_inner(ex, binding) -> dict:
    # Writable-destination validation — read access is not publish
    # permission; an explicit admin opt-in + a named branch are
    # required. Refusing here shows an actionable unconfigured state.
    if not binding.report_writable:
        ex.report_pub_status = "failed"
        ex.report_pub_error = ("binding not enabled for report "
                               "write-back — admin must opt in")
        db.session.commit()
        return {"error": "unconfigured"}
    branch = binding.ref or ""
    if not branch or branch.startswith("refs/tags/") or             branch.startswith("detached"):
        ex.report_pub_status = "failed"
        ex.report_pub_error = "destination must be a named branch"
        db.session.commit()
        return {"error": "invalid branch"}
    wt = _pub_worktree(binding.id, ex.id)
    try:
        if not (wt / ".git").exists():
            wt.parent.mkdir(parents=True, exist_ok=True)
            git_backend.run("clone", binding.url, wt,
                            branch=branch,
                            auth=_binding_auth(binding))
        else:
            git_backend.run("update", wt, branch,
                            auth=_binding_auth(binding))
        dest = wt / _report_dir(ex)
        dest.mkdir(parents=True, exist_ok=True)
        import json as _j
        (dest / "manifest.json").write_text(
            _j.dumps(_build_manifest(ex), indent=2))
        # copy finalized report assets when present
        if ex.report_dir:
            import shutil
            src = Path(ex.report_dir)
            if src.exists():
                for f in src.rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(src)
                        (dest / "report" / rel).parent.mkdir(
                            parents=True, exist_ok=True)
                        shutil.copy2(f, dest / "report" / rel)
        # content digest — distinguishes unchanged vs updated content
        import hashlib
        h = hashlib.sha256()
        for f in sorted(dest.rglob("*")):
            if f.is_file():
                h.update(f.read_bytes())
        digest = h.hexdigest()
        if (ex.report_pub_status == "published"
                and ex.report_pub_digest == digest):
            return {"published": True, "skipped": True}
        sha = git_backend.run("commit_all", wt,
                              f"report: {ex.id[:8]}")
        try:
            git_backend.run("push", wt, branch,
                            auth=_binding_auth(binding))
        except Exception as exc:
            ex.report_pub_status = "failed"
            ex.report_pub_error = f"push failed: {str(exc)[:400]}"
            db.session.commit()
            return {"error": str(exc)[:200]}
        ex.report_pub_status = "published"
        ex.report_pub_repo = binding.url
        ex.report_pub_branch = branch
        ex.report_pub_dir = _report_dir(ex)
        ex.report_pub_sha = sha
        ex.report_pub_digest = digest
        ex.report_pub_error = ""
        db.session.commit()
        return {"published": True, "sha": sha}
    except Exception as exc:
        ex.report_pub_status = "failed"
        ex.report_pub_error = str(exc)[:400]
        db.session.commit()
        return {"error": str(exc)[:200]}


def delete_report(execution_id: str) -> dict:
    """Synchronized deletion: commit-remove the recorded report dir on
    the recorded branch — never history rewrite, never force-push.
    Finalizes only after remote success or confirmed absence."""
    from .execution import Execution
    ex = db.session.get(Execution, execution_id)
    if ex is None:
        return {"error": "unknown execution"}
    if not ex.report_pub_dir:
        # never published — nothing to remove remotely; finalize.
        ex.deletion_status = "none"
        rd, wp = ex.report_dir or "", ex.workspace_path or ""
        db.session.delete(ex)
        db.session.commit()
        from . import evidence
        evidence.remove_owned(execution_id, rd, wp)
        return {"removed": True, "absent": True}
    binding = (db.session.get(GitBinding, ex.binding_id)
               if ex.binding_id else None)
    if binding is None:
        ex.deletion_status = "failed"
        ex.deletion_error = "no source binding"
        db.session.commit()
        return {"error": "no source binding"}
    branch = ex.report_pub_branch or binding.ref or "main"
    # validate the recorded dir is the allowed root + this execution —
    # a stored path is not unrestricted deletion authority.
    expected = _report_dir(ex)
    if ex.report_pub_dir != expected:
        ex.deletion_status = "failed"
        ex.deletion_error = ("recorded dir does not match "
                             "TestOrchestrator/Reports/<id>")
        db.session.commit()
        return {"error": "dir mismatch"}
    wt = _pub_worktree(binding.id, ex.id)
    try:
        if not (wt / ".git").exists():
            wt.parent.mkdir(parents=True, exist_ok=True)
            git_backend.run("clone", binding.url, wt,
                            branch=branch,
                            auth=_binding_auth(binding))
        else:
            git_backend.run("update", wt, branch,
                            auth=_binding_auth(binding))
        target = wt / ex.report_pub_dir
        if target.exists():
            import shutil
            shutil.rmtree(target)
        sha = git_backend.run("commit_all", wt,
                              f"delete report: {ex.id[:8]}")
        if sha:                        # only push if there was a change
            git_backend.run("push", wt, branch,
                            auth=_binding_auth(binding))
        ex.deletion_status = "none"
        ex.deletion_error = ""
        ex.report_pub_dir = ""
        ex.report_pub_status = "none"
        rd, wp = ex.report_dir or "", ex.workspace_path or ""
        db.session.delete(ex)            # app deletion after remote ok
        db.session.commit()
        from . import evidence
        evidence.remove_owned(execution_id, rd, wp)
        return {"removed": True}
    except Exception as exc:
        ex.deletion_status = "failed"
        ex.deletion_error = str(exc)[:400]
        db.session.commit()
        return {"error": str(exc)[:200]}


def parse_collection_detail(ts_file):
    """Read-only collection definition from a .tsc XML — ordered member
    entries + collection execution settings. Returns None on unparseable.
    Per-member keys map the TestSuiteRunConfiguration fields; missing
    values come back None (rendered —, never invented)."""
    import xml.etree.ElementTree as ET
    from pathlib import Path
    try:
        r = ET.parse(str(Path(ts_file))).getroot()
    except Exception:
        return None
    if r.tag != "TestSuiteCollectionEntity":
        return None
    members = []
    for cfg in r.findall(".//TestSuiteRunConfiguration"):
        def t(tag):
            el = cfg.find(tag)
            return el.text.strip() if el is not None and el.text else None
        ref = t("testSuiteEntity")
        if ref:
            members.append({"ref": ref, "runEnabled": t("runEnabled"),
                            "profileName": t("profileName"),
                            "runConfigurationId": t("runConfigurationId"),
                            "runWith": t("runWith")})
    def top(tag):
        el = r.find(tag)
        return el.text.strip() if el is not None and el.text else None
    return {"executionMode": top("executionMode"),
            "delayBetweenInstances": top("delayBetweenInstances"),
            "maxConcurrentInstances": top("maxConcurrentInstances"),
            "members": members}
