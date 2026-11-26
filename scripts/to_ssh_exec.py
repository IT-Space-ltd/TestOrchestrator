#!/usr/bin/env python3
"""Agentless SSH execution dispatcher (docs/orchestration-replacement.md).

Runs inside the controller-side ``to-ssh-dispatcher`` buildbot worker —
never on the remote host. The remote needs only SSH + the test runtime.

Protocol (remote run dir = <workdir>/<execution_id>):
  run.sh        generated argv script (validated spec — no free-form
                portal shell; every path/arg is shlex-quoted)
  run.pid       pgid of the detached run (setsid → run.sh is leader)
  exit_code     written by run.sh when the runner exits
  run.out       captured stdout+stderr
  Reports/      the runner's report tree, SFTP-collected back

Disconnect semantics: the run detaches (setsid), so a dropped session
does not kill it; a reconnecting dispatcher finds run.sh/exit_code and
RESUMES polling instead of launching again. Cancellation kills the
remote process GROUP and is reported as confirmed/unconfirmed via
TO-SSH marker lines on stdout — the portal only reports CANCELED on
``cancel-confirmed``.

Usage: to_ssh_exec.py <spec-file.json>
Exit: 0 runner done/cancel-confirmed · 2 unrecoverable setup error ·
3 runner exit != 0 · 15 cancel-unconfirmed/unreachable.
"""

import json
import os
import shlex
import signal
import sys
import time
from pathlib import Path

import paramiko

POLL_S = 3.0


def _load_spec(path: str) -> dict:
    spec = json.loads(Path(path).read_text())
    for k in ("execution_id", "host", "username", "remote_workdir",
              "executable", "args", "source_tar"):
        if not spec.get(k) and spec.get(k) != 0:
            raise SystemExit(f"spec missing {k}")
    return spec


def _fingerprints(key) -> dict:
    import base64
    import hashlib
    return {
        "SHA256": "SHA256:" + base64.b64encode(
            hashlib.sha256(key.asbytes()).digest()).decode().rstrip("="),
        "MD5": ":".join(f"{b:02x}" for b in key.get_fingerprint()),
    }


class _Client:
    """Thin wrapper so the rest of the dispatcher keeps its
    SSHClient-shaped call sites (exec_command/open_sftp/close) while
    the connect path verifies the pinned key itself."""

    def __init__(self, transport):
        self._t = transport

    def exec_command(self, cmd, timeout=30):
        chan = self._t.open_session(timeout=timeout)
        chan.settimeout(timeout)
        chan.exec_command(cmd)
        return chan, chan.makefile("rb"), chan.makefile_stderr("rb")

    def open_sftp(self):
        return paramiko.SFTPClient.from_transport(self._t)

    def close(self):
        self._t.close()


def _connect(spec) -> _Client:
    """Connect + verify the host key against the ADMIN-APPROVED
    fingerprint BEFORE authenticating — an unexpected key is a hard
    failure (re-verify in the portal), never a silent accept."""
    key_file = spec.get("key_file") or None
    if not (key_file and Path(key_file).is_file()):
        raise SystemExit("spec has no usable key_file")
    pkey = None
    last_exc = None
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey,
                paramiko.ECDSAKey, paramiko.DSSKey):
        try:
            pkey = cls.from_private_key_file(key_file)
            break
        except paramiko.SSHException as exc:
            last_exc = exc
    if pkey is None:
        raise SystemExit(f"ssh key unreadable: {last_exc}")
    import socket as _sock
    transport = paramiko.Transport(_sock.create_connection(
        (spec["host"], int(spec.get("port") or 22)), timeout=20))
    try:
        transport.start_client(timeout=20)
        remote_key = transport.get_remote_server_key()
        fps = _fingerprints(remote_key)
        approved = spec.get("host_key_fingerprint") or ""
        if approved and approved not in fps.values():
            raise SystemExit(
                "HOST KEY MISMATCH: approved fingerprint "
                f"{approved!r} but host presented "
                f"{fps['SHA256']} — re-verify the target in the "
                "portal before running")
        print(f"TO-SSH: host key verified {fps['SHA256']}")
        transport.auth_publickey(spec["username"], pkey)
    except SystemExit:
        transport.close()
        raise
    except Exception:
        transport.close()
        raise
    return _Client(transport)


def _exec(client, cmd: str, timeout: float = 30) -> tuple:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    return stdout.channel.recv_exit_status(), stdout.read().decode(
        "utf-8", "replace"), stderr.read().decode("utf-8", "replace")


def _remote_state(client, spec) -> str:
    """resume | fresh — resume when the run dir already has run.sh."""
    wd = spec["remote_workdir"]
    rc, out, _ = _exec(client, f"test -f {shlex.quote(wd)}/run.sh "
                             f"&& echo yes || echo no")
    return "resume" if out.strip() == "yes" else "fresh"


def _prepare(client, spec) -> None:
    wd = spec["remote_workdir"]
    sftp = client.open_sftp()
    try:
        q = shlex.quote
        _sweep_stale_workdirs(client, spec)
        rc, out, err = _exec(
            client,
            f"mkdir -p {q(wd)} && "
            f"touch {q(wd)}/.to_write_test && "
            f"rm -f {q(wd)}/.to_write_test && "
            # The per-execution workdir is locked to the SSH user
            # BEFORE any staging — a delivered credential file must
            # never sit inside a directory other users can list/read,
            # not even between put and chmod.
            f"chmod 700 {q(wd)}")
        if rc != 0:
            detail = (err or out).strip()
            raise RuntimeError(
                f"remote workdir {wd} is not creatable/writable for "
                f"SSH user {spec.get('username')!r} (rc={rc}"
                + (f": {detail}" if detail else ")"))
        # stage the portal-built source archive
        sftp.put(spec["source_tar"], wd + "/source.tar")
        # Delivered credential (portal-side credential_ref): SFTP'd
        # per execution into the run workdir, 0600, removed at
        # collect/kill — never inside source.tar or argv.
        if spec.get("credential_stage"):
            sftp.put(spec["credential_stage"], wd + "/.to_kre_cred")
            _exec(client, f"chmod 600 {shlex.quote(wd)}/.to_kre_cred")
        # Managed offline licenses: the pack is SFTP'd into the run
        # workdir, then each to-<sha>.lic is installed into the LOGIN
        # account's ~/.katalon/license (0600) — durable machine-bound
        # state that PERSISTS across runs (unlike .to_kre_cred, which
        # is wiped at collect/kill). Only to-* names are installed,
        # so operator-owned .lic files are never overwritten or
        # removed; the .to_managed ledger records TO ownership.
        lic = spec.get("license_install") or {}
        if lic.get("stage"):
            sftp.put(lic["stage"], wd + "/.to_licpack.tar")
            _exec(
                client,
                f'LDIR="$HOME/.katalon/license" && '
                f'mkdir -p "$LDIR" && '
                f'tar -xf {shlex.quote(wd)}/.to_licpack.tar -C '
                f'{shlex.quote(wd)}')
            for ent in (lic.get("files") or []):
                name, sha = ent["name"], ent["sha256"]
                rc, out, err = _exec(
                    client,
                    f'LDIR="$HOME/.katalon/license"; '
                    f'if [ -f "$LDIR/{name}" ]; then '
                    f'  echo "to_license: {name} already installed '
                    f'(content-identical, kept)"; '
                    f'else '
                    f'  install -m 600 {shlex.quote(wd)}/{name} '
                    f'"$LDIR/{name}" && '
                    f'  echo "to_license: installed {name}"; '
                    f'fi; '
                    f'touch "$LDIR/.to_managed" && '
                    f'grep -q "^{sha}  {name}" "$LDIR/.to_managed" '
                    f'2>/dev/null || echo "{sha}  {name}  '
                    f'user=$(id -un 2>/dev/null)" '
                    f'>> "$LDIR/.to_managed"')
                if rc != 0:
                    raise RuntimeError(
                        f"to_license: license install failed for "
                        f"{name}: {(err or out).strip()[:200]}")
        remote = shlex.quote
        args = " ".join(remote(a) for a in spec["args"])
        cred = spec.get("credential_file") or ""
        exe = remote(spec["executable"])
        wrapper = ""
        if cred:
            # same contract as worker-local files: path only, wrapper
            # script on the REMOTE host resolves and execs — never a
            # secret in argv. Without an explicit remote_cred_wrapper
            # the bundled resolver is staged into the run dir — the
            # remote host needs no pre-installed copy.
            wrapper_path = spec.get("remote_cred_wrapper") or ""
            if not wrapper_path:
                wrapper_path = wd + "/kre_cred_exec.sh"
                sftp.put(str(Path(__file__).resolve().parent
                             / "kre_cred_exec.sh"), wrapper_path)
                _exec(client, f"chmod 700 {remote(wrapper_path)}")
            # Run under `sh` explicitly — the SSH path must not rely on
            # any PATH-resolved interpreter (the old shebang+python3
            # requirement); sh is the shell run.sh already executes in.
            wrapper = ("sh " + remote(wrapper_path) + " "
                       + remote(cred) + " ")
        # Node runners execute inside the untarred project root
        # (proj/src) — exec_subdir descends into it; env carries
        # runner vars like PLAYWRIGHT_JUNIT_OUTPUT_FILE.
        subdir = (spec.get("exec_subdir") or "").strip("/")
        cd_target = f"{remote(wd)}/proj/{remote(subdir)}" if subdir \
            else f"{remote(wd)}/proj"
        env_exports = "".join(
            f"export {remote(k)}={remote(v)}\n"
            for k, v in (spec.get("env") or {}).items()
            if k.replace("_", "").isalnum() and "\n" not in str(v))
        # Absolute CLI path (e.g. runtime.executable_path → npx) whose
        # directory must reach PATH — env values are literal, so the
        # prefix needs its own shell-expanded export line.
        prefix = (spec.get("path_prefix") or "").strip()
        if prefix:
            env_exports += f"export PATH={remote(prefix)}:\"$PATH\"\n"
        # Optional dependency step (node runners: npm ci — pinned
        # project deps into the isolated staged workspace).
        deps = spec.get("deps_argv") or []
        deps_line = (
            " ".join(remote(a) for a in deps)
            + f" >>{remote(wd)}/run.out 2>&1 || "
            f"{{ printf 124 > {remote(wd)}/exit_code; exit 124; }}\n"
            if deps else "")
        script = (
            "#!/bin/sh\n"
            f"mkdir -p {remote(wd)}/proj && "
            f"tar -xf {remote(wd)}/source.tar -C {remote(wd)}/proj\n"
            f"cd {cd_target} || exit 125\n"
            "mkdir -p Reports/junit\n"
            f"{env_exports}"
            f"{deps_line}"
            f"{wrapper}{exe} {args} "
            f">>{remote(wd)}/run.out 2>&1\n"
            f"printf '%s' \"$?\" > {remote(wd)}/exit_code\n")
        with sftp.open(wd + "/run.sh", "w") as fh:
            fh.write(script)
        _exec(client, f"chmod 700 {remote(wd)}/run.sh")
    finally:
        sftp.close()


def _sweep_stale_workdirs(client, spec) -> None:
    """Bounded remote-workdir retention (ISS-024): sibling per-execution
    workdirs older than the retention bound are removed — but ONLY when
    they carry TO run markers (run.sh/run.pid), never the workdir root
    or foreign content. Runs left for reconciliation after a timeout are
    reattachable inside this window; the bound prevents the unbounded
    /tmp growth that filled tmpfs and broke SFTP staging on the
    acceptance guest."""
    import posixpath
    wd = spec["remote_workdir"]
    root = posixpath.dirname(wd.rstrip("/"))
    if not root or root == "/":
        return
    retention = int(spec.get("workdir_retention_s") or 86400)
    q = shlex.quote
    # Epoch comparison — find -mmin is minute-granular, too coarse for
    # short retention windows. Only dirs carrying a TO run marker are
    # eligible; the root itself is never touched.
    script = (
        f"cutoff=$(( $(date +%s) - {retention} )); "
        f"for d in {q(root)}/*/; do "
        f"  if [ -f \"$d\"run.sh ] || [ -f \"$d\"run.pid ]; then "
        f"    m=$(stat -c %Y \"$d\" 2>/dev/null || echo 0); "
        f"    if [ \"$m\" -gt 0 ] && [ \"$m\" -lt \"$cutoff\" ]; then "
        f"      rm -rf \"$d\"; "
        f"    fi; "
        f"  fi; "
        f"done; true")
    try:
        _exec(client, script, timeout=30)
    except Exception:
        pass    # sweep is best-effort; a failure must not block the run


def _cleanup_remote_workdir(client, spec) -> None:
    """Remove the per-execution remote workdir after collection or a
    confirmed cancel kill (ISS-024). Delivered credential material is
    already wiped separately at collect/kill — this bounds everything
    else the run staged (source.tar, licpack, run.sh, Reports).
    ``keep_workdir`` in the spec is the operator debugging opt-out —
    the age-based sweep still bounds what is kept."""
    if spec.get("keep_workdir"):
        return
    wd = (spec.get("remote_workdir") or "").strip()
    if len(wd) < 8 or wd == "/":
        return
    q = shlex.quote
    try:
        _exec(client, f"rm -rf {q(wd)} 2>/dev/null; true", timeout=30)
    except Exception:
        pass


def _launch(client, spec) -> None:
    wd = spec["remote_workdir"]
    q = shlex.quote
    # setsid detaches the run — SSH disconnects cannot kill it. The
    # async job must be ONE simple command with redirected fds: a
    # backgrounded compound (`cd && rm && setsid ... &`) forks a
    # subshell that WAITS for the detached tree while holding the
    # channel's pipes — the client read then times out for the run's
    # entire lifetime. run.pid is written by the session leader
    # itself ($$ inside the setsid'd sh), so it equals the
    # process-group id used for group cancellation — never $! of an
    # intermediate subshell.
    rc, out, err = _exec(
        client,
        f"setsid sh -c 'cd {q(wd)} && rm -f exit_code run.pid && "
        f"printf %s \"$$\" > {q(wd)}/run.pid && "
        f"exec ./run.sh' </dev/null >{q(wd)}/launch.out 2>&1 & "
        f"echo launched")
    if "launched" not in out:
        raise SystemExit(f"remote launch failed: {err.strip()[:400]}")
    print(f"TO-SSH: launched pid at {wd}/run.pid")


def _remote_done(client, spec) -> int | None:
    wd = spec["remote_workdir"]
    q = shlex.quote
    rc, out, _ = _exec(
        client, f"test -f {q(wd)}/exit_code && cat {q(wd)}/exit_code"
                f" || echo RUNNING", timeout=15)
    out = out.strip()
    if out == "RUNNING" or not out.lstrip("-").isdigit():
        return None
    return int(out)


def _kill_remote(client, spec) -> bool:
    """Kill the remote process GROUP (pgid == run.pid); confirm it is
    gone. Returns True only when termination is verified."""
    wd = spec["remote_workdir"]
    q = shlex.quote
    try:
        rc, pid, _ = _exec(client, f"cat {q(wd)}/run.pid 2>/dev/null")
        pid = pid.strip()
        if not pid.isdigit():
            return False
        _exec(client, f"kill -TERM -{pid} 2>/dev/null; sleep 1; "
                      f"kill -KILL -{pid} 2>/dev/null; true")
        # A killed run must not leave delivered secret material.
        _exec(client, f"rm -f {q(wd)}/.to_kre_cred 2>/dev/null; true")
        rc, out, _ = _exec(client, f"kill -0 {pid} 2>/dev/null "
                                   f"&& echo alive || echo dead")
        return out.strip() == "dead"
    except Exception:
        return False


def _collect(client, spec, local_dir: Path) -> None:
    """SFTP-pull run.out + exit_code + the report tree."""
    wd = spec["remote_workdir"]
    local_dir.mkdir(parents=True, exist_ok=True)
    sftp = client.open_sftp()

    def _get(remote_rel: str, local_rel: str) -> bool:
        try:
            target = local_dir / local_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(f"{wd}/{remote_rel}", str(target))
            return True
        except OSError:
            return False

    def _walk(remote_dir: str, local_rel: str) -> None:
        try:
            for ent in sftp.listdir_attr(remote_dir):
                rpath = remote_dir + "/" + ent.filename
                lrel = local_rel + "/" + ent.filename
                if ent.st_mode & 0o40000:
                    _walk(rpath, lrel)
                else:
                    _get(rpath.replace(wd + "/", ""), lrel)
        except OSError:
            pass

    try:
        _get("run.out", "run.out")
        _get("exit_code", "exit_code")
        # The runner's -reportFolder is an ABSOLUTE path under the run
        # dir (dispatch passes <wd>/<report_rel>) — collect from there.
        report_rel = (spec.get("report_rel") or "Reports").strip("/")
        _walk(f"{wd}/{report_rel}", report_rel)
        # Delivered credentials live only for the execution's window —
        # remove once results are pulled (helper already consumed it).
        try:
            sftp.remove(f"{wd}/.to_kre_cred")
        except OSError:
            pass
        # The license pack + extracted copies are per-run staging —
        # the INSTALLED copies under ~/.katalon/license persist.
        for rel in (".to_licpack.tar",
                    *((e["name"]) for e in
                      (spec.get("license_install") or {})
                      .get("files") or [])):
            try:
                sftp.remove(f"{wd}/{rel}")
            except OSError:
                pass
    finally:
        sftp.close()


def _tail_remote_log(client, spec, lines: int = 200) -> None:
    wd = spec["remote_workdir"]
    try:
        rc, out, _ = _exec(client, f"tail -n {lines} "
                                 f"{shlex.quote(wd)}/run.out 2>/dev/null")
        if out.strip():
            print("TO-SSH: ---- remote run.out ----")
            print(out[:8000])
    except Exception:
        pass


_CANCELLED = {"flag": False}


def main(argv=None) -> int:
    spec_file = (argv or sys.argv[1:])[0]
    spec = _load_spec(spec_file)
    local_artifacts = Path.cwd() / "remote-artifacts"

    def _on_term(signum, frame):
        _CANCELLED["flag"] = True

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    client = None
    try:
        client = _connect(spec)
        state = _remote_state(client, spec)
        if state == "resume":
            print("TO-SSH: reattaching to existing remote run — not "
                  "launching a duplicate")
        else:
            _prepare(client, spec)
            _launch(client, spec)
        deadline = time.monotonic() + int(spec.get("timeout_s") or 3600)
        exit_code = None
        while True:
            try:
                exit_code = _remote_done(client, spec)
            except Exception as exc:
                # Session loss: the REMOTE run continues detached —
                # reconnect and resume, never relaunch.
                print(f"TO-SSH: session lost ({exc}); reconnecting")
                try:
                    client = _connect(spec)
                except Exception as exc2:
                    print(f"TO-SSH: reconnect failed ({exc2}); "
                          "retrying")
                    time.sleep(POLL_S)
                    continue
                continue
            if exit_code is not None:
                break
            if _CANCELLED["flag"]:
                print("TO-SSH: cancel signal received — terminating "
                      "remote process group")
                try:
                    ok = _kill_remote(client, spec)
                except Exception:
                    ok = False
                print("TO-SSH: cancel-confirmed" if ok
                      else "TO-SSH: cancel-unconfirmed")
                if ok:
                    _cleanup_remote_workdir(client, spec)
                return 0 if ok else 15
            if time.monotonic() > deadline:
                print("TO-SSH: timeout — remote run left for "
                      "reconciliation (not killed)")
                return 2
            time.sleep(POLL_S)
        _tail_remote_log(client, spec)
        _collect(client, spec, local_artifacts)
        _cleanup_remote_workdir(client, spec)
        print(f"TO-SSH: runner exit_code={exit_code}; artifacts "
              "collected")
        return 0 if exit_code == 0 else 3
    except SystemExit:
        raise
    except Exception as exc:
        print(f"TO-SSH: dispatcher error: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
