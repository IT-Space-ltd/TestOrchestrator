"""Durable artifact storage (M9).

Produce → stage (workspace Reports/) → store durably → verify →
expose → cleanup-when-eligible. The workspace file is a STAGING
copy; `Artifact.storage_state` records the lifecycle:

    staged → uploading → stored | failed          (store confirmed)
    stored → expired                              (staging removed)

Backends:
- ``local``   — filesystem root inside the administrator-approved
  roots list (service-accessible storage, NOT the browser's
  machine, NOT worker temp).
- ``mounted`` — same mechanics, but the root must sit under a
  separately approved mounted-share list (administrator-mounted
  SMB/NFS; direct share management is out of scope).
- ``s3``      — boto3-gated: reports unavailable until the
  dependency is approved+installed (separately gated — §2).

Every write is idempotent: the key is
``<project_id>/<execution_id>/<attempt>/<rel_path>`` — re-storing
the same execution overwrites identical content, never duplicates.
Verification = size + sha256 after write; failure → ``failed``
state, staging preserved, retry is a re-run of the same transfer.
"""
import hashlib
import os
import secrets
from pathlib import Path

from flask import current_app


class StoreError(Exception):
    pass


def _approved_roots(key: str):
    """Administrator-approved filesystem roots — config list, not a
    user-supplied arbitrary path."""
    raw = current_app.config.get(key) or []
    if isinstance(raw, str):
        raw = [r for r in raw.split(os.pathsep) if r]
    return [Path(r).resolve() for r in raw]


def approved_local_roots():
    roots = _approved_roots("TO_ARTIFACT_ROOTS")
    if not roots:
        from flask import current_app as _app
        roots = [Path(_app.instance_path).resolve() / "artifacts"]
    return roots


def approved_mount_roots():
    return _approved_roots("TO_MOUNTED_ROOTS")


def _under(path: Path, roots) -> bool:
    rp = path.resolve()
    return any(rp == r or r in rp.parents for r in roots)


class _FSStore:
    """Shared mechanics for local/mounted backends: writes go
    tmp-file → fsync → atomic rename inside the approved root;
    verification re-hashes the durable copy."""

    def __init__(self, root: Path, subdir: str = ""):
        self.root = root / (subdir or "")

    def _dst(self, key: str) -> Path:
        dst = (self.root / key).resolve()
        if not _under(dst, [self.root]):
            raise StoreError("key escapes store root")
        return dst

    def put(self, src: Path, key: str) -> str:
        dst = self._dst(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.parent / (".to-" + secrets.token_hex(6))
        h = hashlib.sha256()
        with open(src, "rb") as f, open(tmp, "wb") as o:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                o.write(chunk)
            o.flush()
            os.fsync(o.fileno())
        os.replace(tmp, dst)
        # Re-resolve AFTER the rename: a swapped parent (symlink
        # substitution between the key check and the rename) lands
        # outside the root — detect and refuse rather than trusting
        # the check-to-use window.
        if not _under(dst, [self.root]):
            try:
                dst.unlink()
            except OSError:
                pass
            raise StoreError("post-rename containment check failed")
        from .results import sha256_file
        if sha256_file(dst) != h.hexdigest() or \
                dst.stat().st_size != src.stat().st_size:
            raise StoreError("post-write verification failed")
        return str(dst.relative_to(self.root))

    def path(self, ref: str) -> Path:
        return self._dst(ref)

    def delete(self, ref: str) -> bool:
        p = self._dst(ref)
        if p.is_file():
            p.unlink()
            return True
        return False

    def probe_steps(self):
        """Granular destination checks — reachable → temp write →
        read-back/checksum → temp delete. Returns a list of
        (label, ok, detail) rows; stops at the first hard failure
        since later steps depend on earlier ones."""
        steps = []
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            steps.append(("destination reachable", True,
                          str(self.root)))
        except OSError as exc:
            steps.append(("destination reachable", False, str(exc)))
            return steps
        probe = self.root / f".to-probe-{secrets.token_hex(4)}"
        try:
            probe.write_text("probe")
            steps.append(("temporary write", True, ""))
        except OSError as exc:
            steps.append(("temporary write", False, str(exc)))
            return steps
        try:
            ok = probe.read_text() == "probe"
            steps.append(("read-back + checksum", ok,
                          "" if ok else "content mismatch"))
            if not ok:
                return steps
        except OSError as exc:
            steps.append(("read-back + checksum", False, str(exc)))
            return steps
        try:
            probe.unlink()
            steps.append(("temporary delete", True, ""))
        except OSError as exc:
            steps.append(("temporary delete", False,
                          f"{exc} — leftover {probe.name}"))
        return steps

    def probe(self) -> tuple:
        steps = self.probe_steps()
        bad = next((s for s in steps if not s[1]), None)
        if bad is None:
            return True, "write/read/delete verified"
        return False, f"{bad[0]}: {bad[2]}"


class _S3Store:
    """boto3-backed S3/S3-compatible store — capability-gated: the
    dependency is separately approved, so absence is an honest
    readiness failure, not a silent fallback."""

    def __init__(self, cfg: dict, credential_ref: str = ""):
        self.cfg = cfg
        # TLS is the default — a non-TLS endpoint is only accepted
        # behind an explicit test-only config flag (§2); it must
        # never become a production default. Checked before the
        # dependency gate so the policy holds regardless of boto3.
        ep = (cfg.get("endpoint_url") or "")
        if ep.startswith("http://") and not current_app.config.get(
                "TO_S3_ALLOW_INSECURE_ENDPOINTS"):
            raise StoreError(
                "non-TLS S3 endpoint refused — set TLS or mark the "
                "endpoint test-only in config")
        try:
            import boto3                               # gated dep
        except ImportError as exc:
            raise StoreError(
                "S3 storage requires boto3 — pending dependency "
                "approval; local/mounted stores work now") from exc
        # The ref is a SecretRef NAME — resolve through the secrets
        # store; credentials are never stored in config, URLs, or
        # logs. Expected format 'access_key:secret_key'.
        credential = ""
        if credential_ref:
            from .secrets_store import SecretError, read_secret
            try:
                credential = read_secret(
                    current_app._get_current_object(), credential_ref)
            except SecretError as exc:
                raise StoreError(
                    f"credential {credential_ref!r}: {exc}") from exc
        from botocore.config import Config
        self._client = boto3.client(
            "s3",
            region_name=cfg.get("region") or None,
            endpoint_url=cfg.get("endpoint_url") or None,
            aws_access_key_id=credential.split(":", 1)[0] if credential
            else None,
            aws_secret_access_key=(credential.split(":", 1)[1]
                                   if ":" in credential else None),
            config=Config(s3={"addressing_style": "path"}
                          if cfg.get("path_style") else {}))
        self.bucket = cfg["bucket"]
        self.prefix = (cfg.get("prefix") or "").strip("/")

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, src: Path, key: str) -> str:
        k = self._key(key)
        self._client.upload_file(str(src), self.bucket, k)
        head = self._client.head_object(Bucket=self.bucket, Key=k)
        if head.get("ContentLength") != src.stat().st_size:
            raise StoreError("s3 size verification failed")
        return k

    def open(self, ref: str):
        body = self._client.get_object(Bucket=self.bucket,
                                       Key=ref)["Body"]
        return body

    def delete(self, ref: str) -> bool:
        self._client.delete_object(Bucket=self.bucket, Key=ref)
        return True

    def probe_steps(self):
        steps = [("destination reachable", True,
                  f"bucket {self.bucket}"), ]
        k = self._key(f".to-probe-{secrets.token_hex(4)}")
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            steps[0] = ("destination reachable", False, str(exc))
            return steps
        steps.append(("authentication", True, ""))
        try:
            self._client.put_object(Bucket=self.bucket, Key=k,
                                    Body=b"probe")
            steps.append(("temporary write", True, ""))
        except Exception as exc:
            steps.append(("temporary write", False, str(exc)))
            return steps
        try:
            got = self._client.get_object(
                Bucket=self.bucket, Key=k)["Body"].read()
            ok = got == b"probe"
            steps.append(("read-back + checksum", ok,
                          "" if ok else "content mismatch"))
            if not ok:
                return steps
        except Exception as exc:
            steps.append(("read-back + checksum", False, str(exc)))
            return steps
        try:
            self._client.delete_object(Bucket=self.bucket, Key=k)
            steps.append(("temporary delete", True, ""))
        except Exception as exc:
            steps.append(("temporary delete", False,
                          f"{exc} — leftover key {k}"))
        return steps

    def probe(self) -> tuple:
        steps = self.probe_steps()
        bad = next((s for s in steps if not s[1]), None)
        if bad is None:
            return True, "write/read/delete verified"
        return False, f"{bad[0]}: {bad[2]}"


def backend_for(store) -> object:
    """Materialize the backend for an ArtifactStore row. Roots are
    checked against the administrator-approved lists on EVERY use —
    a saved config cannot wander outside policy."""
    cfg = store.config()
    if store.kind in ("local", "mounted"):
        root = Path(cfg.get("root") or "")
        roots = (approved_local_roots() if store.kind == "local"
                 else approved_mount_roots())
        if not roots:
            raise StoreError(
                f"no approved {store.kind} roots configured — "
                "administrator must set the root list first")
        if not _under(root, roots):
            raise StoreError(
                f"root {root} is outside the approved "
                f"{store.kind} roots")
        # Share-absence guard (§storage-4): a mounted destination
        # whose mount is gone must NOT silently write into the
        # underlying mount-point directory and report network
        # storage. The configured root must be the mount point
        # itself — additional layout lives in `subdir`.
        if store.kind == "mounted" and not os.path.ismount(root):
            raise StoreError(
                f"mounted store root {root} is not a mount point — "
                "the configured share appears absent; refusing to "
                "write to the underlying directory")
        return _FSStore(root, cfg.get("subdir") or "")
    if store.kind == "s3":
        if not cfg.get("bucket"):
            raise StoreError("s3 store requires a bucket")
        return _S3Store(cfg, store.credential_ref)
    raise StoreError(f"unknown store kind {store.kind!r}")


def artifact_key(project_id: str, exec_id: str, attempt: int,
                 rel_path: str) -> str:
    """Execution/attempt-scoped durable key — idempotent (same
    execution → same key → overwrite, never duplicate)."""
    safe = rel_path.replace("\\", "/").lstrip("/")
    return f"{project_id}/{exec_id}/{int(attempt or 1)}/{safe}"


def store_execution_artifacts(ex, report_dir) -> dict:
    """Transfer registered artifacts to the project's ACTIVE store.
    Executions without a configured store stay `staged` — local
    workspace is the default historical behavior and stays valid.
    Returns {"stored": n, "failed": n, "skipped": n}."""
    from .extensions import db
    from .execution import Artifact, ArtifactStore
    store = ArtifactStore.query.filter_by(
        project_id=ex.project_id, active=True).first()
    counts = {"stored": 0, "failed": 0, "skipped": 0}
    if store is None:
        return counts
    try:
        backend = backend_for(store)
    except StoreError as exc:
        store.last_error = str(exc)
        db.session.commit()
        return counts
    snap = ex.snapshot()
    attempt = len(snap.get("bb_attempts") or []) or 1
    rows = Artifact.query.filter_by(execution_id=ex.id).all()
    root = Path(report_dir).resolve()
    for a in rows:
        src = (root / a.rel_path).resolve()
        # Source containment: a rel_path must never reach outside the
        # report dir — a registered artifact is evidence, not an
        # arbitrary-read primitive.
        if src != root and root not in src.parents:
            a.storage_state = "failed"
            store.last_error = f"containment: {a.rel_path}"[:512]
            counts["failed"] += 1
            continue
        if not src.is_file():
            # Actionable state (§storage-6): the staged source is
            # gone — retry cannot recover it, only a re-run can.
            a.storage_state = "missing"
            counts["skipped"] += 1
            continue
        a.storage_state = "uploading"
        try:
            ref = backend.put(
                src, artifact_key(ex.project_id, ex.id,
                                  attempt, a.rel_path))
            a.store_id = store.id
            a.storage_ref = ref
            a.storage_state = "stored"
            a.attempt = attempt
            from .execution import utcnow
            a.stored_at = utcnow()
            counts["stored"] += 1
        except Exception as exc:                    # noqa: BLE001
            a.storage_state = "failed"
            store.last_error = str(exc)[:512]
            counts["failed"] += 1
    db.session.commit()
    return counts
