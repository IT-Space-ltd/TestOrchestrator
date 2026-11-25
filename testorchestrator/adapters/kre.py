"""KRE (Katalon Runtime Engine) adapter — connect-only (handoff §5).

KRE is installed, licensed, updated, and removed externally by the operator.
This adapter registers existing installations and invokes them; it NEVER
installs, downloads, imports, upgrades, or licenses KRE. Executable
existence alone is not a claim of licence readiness.

All invocations use subprocess argument arrays over allowlisted inputs —
never concatenated shell text. Workspaces are isolated per attempt at the
recorded source SHA with a dedicated report directory. Cancellation targets
the actual process tree.

NOTE: argument spelling is version-aware (verified KRE CLI schema pending
operator-supplied executable; see docs/integration-contracts.md). The
fixture executable used in tests proves the pipeline mechanics — it does
not prove KRE CLI compatibility (A14).
"""

import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class KreError(RuntimeError):
    """Actionable external-prerequisite failure (missing/incompatible KRE)."""


@dataclass
class InvocationResult:
    started_at: str = ""
    finished_at: str = ""
    exit_status: int | None = None
    timed_out: bool = False
    canceled: bool = False
    stdout_path: str = ""
    stderr_path: str = ""
    pid: int = 0
    error_kind: str = ""   # license|config|infrastructure|execution
    error_text: str = ""


# Browser choices the adapter emits to -browserType=. Values are KRE's
# documented names — the browser itself must be installed on the RUNNER
# host (not this portal). Edge is Windows-only, Safari macOS-only.
SUPPORTED_BROWSERS = {
    "chrome":          {"label": "Chrome",           "platforms": None},
    "chrome_headless": {"label": "Chrome (headless)", "platforms": None},
    "firefox":         {"label": "Firefox",           "platforms": None},
    "firefox_headless": {"label": "Firefox (headless)", "platforms": None},
    # Edge Chromium (Chromium-based) ships Linux drivers per Katalon 8.x
    # notes — NOT the discontinued legacy Edge, which was Windows-only.
    # "edge_legacy" stays Windows-only; plain "edge" means Chromium.
    "edge":            {"label": "Edge",              "platforms": None},
    "edge_legacy":     {"label": "Edge (legacy)",     "platforms": ("windows",)},
    "safari":          {"label": "Safari",            "platforms": ("darwin", "macos")},
}

# Remote WebDriver: an explicit opt-in that overrides local browser use.
# url/driver-type/capabilities are passed verbatim to KRE — the adapter
# validates shape, not reachability.


def normalize_browser(value: str, os_arch: str = "") -> str:
    """Map a stored/requested value to a supported browser id, or "".
    Accepts the ids above and the legacy display strings (e.g. the old
    free-text 'Chrome (headless)')."""
    v = (value or "").strip().lower()
    if not v:
        return ""
    for bid, meta in SUPPORTED_BROWSERS.items():
        if v in (bid, meta["label"].lower()):
            if meta["platforms"]:
                arch = (os_arch or "").lower()
                if arch and not any(p in arch for p in meta["platforms"]):
                    return ""   # platform-incompatible choice — do not guess
            return meta["label"]
    return ""


def validate_browser(value: str, os_arch: str = "") -> tuple[bool, str]:
    """(ok, normalized|error) — empty is allowed (falls back to the
    documented default); anything non-empty must normalize."""
    v = (value or "").strip()
    if not v:
        return True, ""
    norm = normalize_browser(v, os_arch)
    if not norm:
        return False, (f"unsupported browser {value!r} for this target "
                       f"({os_arch or 'unknown platform'}) — supported: "
                       + ", ".join(sorted(SUPPORTED_BROWSERS)))
    return True, norm


# Well-known KRE console flag set (Katalon-documented form). Kept version-
# aware: flags may be overridden per detected version once the operator's
# installed version is probed — never assumed universal (§5).
def build_args(
    executable: str,
    project_path: str,
    suite_path: str,
    report_dir: str,
    profile: str = "default",
    browser: str = "Chrome (headless)",
    remote_webdriver_url: str = "",
    remote_webdriver_type: str = "",
    extra: list | None = None,
    collection: bool = False,
) -> list:
    # KRE console selectors want the project-relative path WITHOUT the
    # file extension — the discovered inventory path keeps it, so it is
    # stripped at the adapter boundary. Katalon saves BOTH suites and
    # suite collections as .ts (the entity tag, not the filename, is
    # what discovery classifies on); .tsc spellings are tolerated too.
    selector = suite_path
    for ext in (".ts", ".tsc") if collection else (".ts",):
        if suite_path.lower().endswith(ext):
            selector = suite_path[:-len(ext)]
            break
    args = [
        executable,
        "-noSplash",
        "-runMode=console",
        f"-projectPath={project_path}",
        (f"-testSuiteCollectionPath={selector}"
         if collection else f"-testSuitePath={selector}"),
        f"-executionProfile={profile}",
    ]
    if remote_webdriver_url:
        # Katalon-documented remote form: -browserType=Remote is still
        # REQUIRED — the browser runs on the WebDriver service (e.g.
        # Selenium Grid node), not the KRE host. remoteWebDriverType
        # names the remote driver type (commonly Selenium); the actual
        # browser choice on the grid comes from desired capabilities in
        # the KRE project config — the URL/type alone does NOT select
        # Chrome vs Firefox on the node.
        args += ["-browserType=Remote",
                 f"-remoteWebDriverUrl={remote_webdriver_url}"]
        if remote_webdriver_type:
            args += [f"-remoteWebDriverType={remote_webdriver_type}"]
    else:
        args += [f"-browserType={browser}"]
    args += [f"-reportFolder={report_dir}", *(extra or [])]
    return args


# Version-gated console options (§5): each flag declares the minimum KRE
# major version it is supported on. Thresholds are the adapter's declared
# contract — operators verify them against the INSTALLED build; an
# unknown or lower detected version drops the option with an evidence
# note rather than emitting a guessed flag.
OPTION_GATES = {
    "retry": ("-retry", 8, "immediate retry of failed cases"),
    "retryStrategy": ("-retryStrategy", 9, "retry strategy policy"),
    "maxFailedTests": ("-maxFailedTests", 9, "abort after N failures"),
}


def version_major(version: str) -> int | None:
    match = re.match(r"\s*(\d+)", version or "")
    return int(match.group(1)) if match else None


def gated_flags(version: str, requested: dict) -> tuple:
    """(flags, dropped): apply the option gate to requested kre_options.
    Keys outside OPTION_GATES and options below the detected version are
    dropped (reported), so only verified-supported flags reach argv."""
    flags, dropped = [], []
    major = version_major(version)
    for key, value in (requested or {}).items():
        spec = OPTION_GATES.get(str(key))
        if spec is None:
            dropped.append(f"{key} (not an allowlisted option)")
        elif major is None:
            dropped.append(f"{key} (KRE version unknown — requires "
                           f">= {spec[1]}.x)")
        elif major < spec[1]:
            dropped.append(f"{key} (requires KRE >= {spec[1]}.x, "
                           f"detected {version})")
        else:
            flags.append(f"{spec[0]}={value}")
    return flags, dropped


def probe_version(executable: str, timeout: int = 30) -> str:
    """Probe an existing installation's version. Raises KreError when the
    executable is missing or unprobeable — actionable prerequisite error."""

    path = Path(executable)
    if not path.is_absolute():
        raise KreError(f"executable path must be absolute: {executable}")
    if not path.exists():
        raise KreError(f"KRE executable not found: {executable}")
    if not os.access(path, os.X_OK):
        raise KreError(f"KRE path is not executable: {executable}")
    try:
        proc = subprocess.run(
            [str(path), "-version"], capture_output=True, text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KreError(f"version probe failed for {executable}: {exc}")
    text = (proc.stdout + proc.stderr).strip()
    # The engine-version marker is explicit: katalon.versionNumber=.
    # A bare first-number match is NOT acceptable — boot output carries
    # timestamps, hashes, and framework versions that are not the engine
    # version (a wrong parse is worse than an honest unknown).
    match = re.search(r"katalon\.versionNumber=(\d+\.\d+(?:\.\d+)*)",
                      text)
    if match:
        return match.group(1)
    raise KreError(
        "version probe produced no katalon.versionNumber marker — "
        "installation version inconclusive")


def prepare_workspace(source_dir: Path, dest: Path, sha: str) -> Path:
    """Isolated checkout at the recorded source SHA (§5). For a local runner
    the worktree copy is made under the runner workspace; source contents
    are copied verbatim — project code is never executed during indexing."""

    workspace = dest / "project"
    if source_dir.exists():
        shutil.copytree(source_dir, workspace)
    else:
        workspace.mkdir(parents=True)
    (dest / "snapshot.sha").write_text(sha, encoding="utf-8")
    return workspace


def _scrub(text: str, redact: list) -> str:
    """Replace every occurrence of a sensitive value before it can land
    in evidence. Empty strings are ignored."""
    for value in redact or []:
        if value:
            text = text.replace(str(value), "***REDACTED***")
    return text


def run_invocation(
    args: list,
    log_dir: Path,
    timeout_s: int = 3600,
    cancel_event=None,
    env_extra: dict | None = None,
    redact: list | None = None,
) -> InvocationResult:
    """Execute an invocation and capture evidence (§5).

    - argv array only; no shell
    - own process group so cancel kills the tree
    - stdout/stderr captured to files (never logged to app logs verbatim
      if they could carry secrets — artifact collection handles policy)
    - ``redact`` values are scrubbed from the recorded argv AND from the
      captured stdout/stderr files before they become artifacts
    - cancel stays pending-aware: process termination is awaited
    """

    log_dir.mkdir(parents=True, exist_ok=True)
    result = InvocationResult()
    # Record the exact argv used — sanitized (paths/flags only, no
    # secrets) so reviewers can inspect the actual KRE invocation.
    (log_dir / "kre-invocation.log").write_text(
        f"argv={_scrub(shlex.join(str(a) for a in args), redact or [])}\n",
        encoding="utf-8")
    stdout_f = open(log_dir / "kre-stdout.log", "wb")
    stderr_f = open(log_dir / "kre-stderr.log", "wb")
    result.stdout_path = str(stdout_f.name)
    result.stderr_path = str(stderr_f.name)
    result.started_at = datetime.now(timezone.utc).isoformat()

    env = dict(os.environ)
    env.update(env_extra or {})

    try:
        proc = subprocess.Popen(
            args, stdout=stdout_f, stderr=stderr_f, env=env,
            start_new_session=True,  # own process group for tree cancel
        )
    except OSError as exc:
        stdout_f.close(); stderr_f.close()
        raise KreError(f"failed to launch {args[0]}: {exc}")

    result.pid = proc.pid
    deadline = time.monotonic() + timeout_s
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            _kill_tree(proc)
            result.canceled = True
            break
        if time.monotonic() > deadline:
            _kill_tree(proc)
            result.timed_out = True
            break
        time.sleep(0.25)

    try:
        result.exit_status = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        _kill_tree(proc, force=True)
        result.exit_status = proc.wait()

    result.finished_at = datetime.now(timezone.utc).isoformat()
    stdout_f.close(); stderr_f.close()
    _scrub_file(Path(result.stdout_path), redact)
    _scrub_file(Path(result.stderr_path), redact)
    return result


def _scrub_file(path: Path, redact: list, max_bytes: int = 64 << 20) -> None:
    """Rewrite a captured output file with sensitive values removed —
    the child process may echo its own argv (KRE logs the command line)."""
    if not redact or not path.exists() or path.stat().st_size > max_bytes:
        return
    raw = path.read_bytes()
    out = raw
    for value in redact:
        if value:
            out = out.replace(str(value).encode("utf-8", "replace"),
                              b"***REDACTED***")
    if out != raw:
        path.write_bytes(out)


def _kill_tree(proc, force: bool = False) -> None:
    """Terminate the real process tree (process group), escalating TERM->KILL."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def classify_error(result: InvocationResult, stdout_tail: str = "") -> str:
    """Distinguish licence/configuration/infrastructure errors from test
    failures (§5). Missing results never masquerade as a passed run."""
    if result.canceled:
        return ""
    if result.timed_out:
        return "infrastructure"
    text = stdout_tail.lower()
    # The step runner's own kill marker — a timed-out run is
    # infrastructure even when the coordinator only reports a bare
    # failure code (results=2 hides the timeout cause).
    if "command timed out" in text:
        return "infrastructure"
    # The credential resolver failed before KRE launched — never a
    # KRE license verdict (the license was never reached). Split by
    # layer: a missing/unreadable credential FILE, permission or
    # confinement failure, missing executable/interpreter, or a
    # failed launch is a target infrastructure problem; only a bad
    # credential VALUE (empty/malformed token, conflicting source,
    # usage errors) is a config error.
    if "kre_cred_exec:" in text:
        if any(s in text for s in (
                "credential file not found", "credential file unreadable",
                "credential file must not be a link",
                "cannot stat credential", "cannot read credential",
                "not owned by the invoking", "group/other permission",
                "outside permitted directory", "cannot create private run dir",
                "cannot create output fifo", "executable not found",
                "failed to start")):
            return "infrastructure"
        return "config"
    # Fatal license failures — specific markers only. KRE logs a
    # benign "Failed to activate with TestCloud license" fallback in
    # every run before acquiring the KRE license; matching on the bare
    # word "license" misclassifies unrelated failures that follow it.
    if any(s in text for s in (
            "failed to activate with katalon runtime engine",
            "license quota exceeded", "cannot find a license",
            "license has expired", "trial license has expired",
            "cannot execute the activation request",
            "invalid api key", "incorrect api key",
            "no license available", "insufficient license")):
        return "license"
    # Bad project/config markers — but never the argv echo: the
    # logged invocation always carries "-projectPath=<dir>", which is
    # data, not an error. Real KRE complaints phrase the path problem
    # out, so the bare "projectpath" substring is only meaningful when
    # it is not the "-projectPath=" option itself. These markers only
    # appear AFTER activation succeeds, so they outrank the generic
    # license text below — a truncated tail can lose the
    # "Activated successfully" line while keeping stray
    # "Failed to activate with TestCloud" noise.
    if any(s in text for s in ("no such file", "cannot find project",
                               "project not found", "invalid project")) \
            or ("projectpath" in text and "projectpath=" not in text) \
            or re.search(
                r"test suite(?: collection)? '[^']*' not found",
                text) is not None:
        return "config"
    # Generic license text only counts when the KRE license was never
    # acquired — a successful activation proves licensing was not the
    # failure.
    if ("activated successfully with katalon runtime engine license"
            not in text and any(
                s in text for s in ("license", "licence",
                                    "activation"))):
        return "license"
    if result.exit_status not in (0, 1):
        return "infrastructure"
    return ""


def discover_reports(report_dir: Path) -> list:
    """Report discovery: JUnit XML outputs produced by the invocation."""
    if not report_dir.exists():
        return []
    return sorted(
        p for p in report_dir.rglob("*.xml")
        if p.is_file() and not p.name.startswith(".")
    )


# ---------------------------------------------------------------- readiness
# Same TO-PROBE marker contract as the other runners: the staged source
# runs on the target under the target's own account, emits markers,
# installs nothing. What a remote KRE run actually needs, checked on
# the target itself — the configured katalonc executable, a Python
# interpreter the staged credential resolver runs under, that resolver
# really executing (its usage-error exit proves parse + launch), a
# writable workspace, and application-URL reachability.

PROBE_SH = """#!/bin/sh
# TestOrchestrator KRE readiness probe (POSIX).
set +e
R=Reports
mkdir -p "$R"
L="$R/probe.txt"; : > "$L"
p() { echo "TO-PROBE $1"; echo "TO-PROBE $1" >> "$L"; }
p "connectivity=ok"
K="${KREBIN:-}"
if [ -z "$K" ]; then
  p "kre=missing (no executable_path configured)"
elif [ ! -f "$K" ]; then
  p "kre=missing ($K not found)"
elif [ ! -x "$K" ]; then
  p "kre=missing ($K not executable)"
else
  p "kre=present"
  if command -v timeout >/dev/null 2>&1; then T="timeout 120"; else T=""; fi
  v=$($T "$K" -version 2>&1 \\
      | grep -o 'katalon\\.versionNumber=[0-9.]*' | head -1)
  if [ -n "$v" ]; then
    p "krever=${v#katalon.versionNumber=}"
  else
    p "krever=unprobeable (-version produced no versionNumber marker)"
  fi
fi
sh .to_kre_cred_exec.sh 2>&1 | grep -q "usage: kre_cred_exec" \\
  && { p "helper_launcher=sh"; p "helper_exec=ok"; } \\
  || p "helper_exec=FAILED"
mkdir -p Reports/.wtest && rmdir Reports/.wtest \\
  && p "workspace_write=ok" || p "workspace_write=denied"
if [ -n "%APP_URL%" ]; then
  curl -sf -m 10 -o /dev/null "%APP_URL%" \\
    && p "app_url=reachable" || p "app_url=UNREACHABLE from this target"
else
  p "app_url=not-configured (no application URL to check)"
fi
p "done=1"
"""


PROBE_CMD = r"""@echo off
rem TestOrchestrator KRE readiness probe (Windows cmd, argv-only).
setlocal enabledelayedexpansion
if not exist Reports mkdir Reports
set L=Reports\probe.txt
type nul > "%L%"
call :p connectivity=ok
if "%KREBIN%"=="" goto nokrebin
if not exist "%KREBIN%" goto kremissing
call :p kre=present
for /f "delims=" %%v in ('"%KREBIN%" -version 2^>^&1 ^| findstr /c:"katalon.versionNumber="') do (echo TO-PROBE krever=%%v & >>"%L%" echo TO-PROBE krever=%%v)
goto kredone
:kremissing
call :p kre=missing ^(%KREBIN% not found^)
goto kredone
:nokrebin
call :p kre=missing ^(no executable_path configured^)
:kredone
powershell -NoProfile -ExecutionPolicy Bypass -File ".to_kre_cred_exec.ps1" 2>&1 | findstr /c:"usage: kre_cred_exec" >nul
if errorlevel 1 (echo TO-PROBE helper_exec=FAILED & >>"%L%" echo TO-PROBE helper_exec=FAILED) else (echo TO-PROBE helper_launcher=powershell & echo TO-PROBE helper_exec=ok & >>"%L%" echo TO-PROBE helper_launcher=powershell & >>"%L%" echo TO-PROBE helper_exec=ok)
rmdir Reports\.wtest 2>nul & mkdir Reports\.wtest 2>nul & rmdir Reports\.wtest 2>nul
if errorlevel 1 (echo TO-PROBE workspace_write=denied & >>"%L%" echo TO-PROBE workspace_write=denied) else (echo TO-PROBE workspace_write=ok & >>"%L%" echo TO-PROBE workspace_write=ok)
if "%APP_URL%"=="" goto noappurl
curl -sf -m 10 -o nul "%APP_URL%" >nul 2>&1
if errorlevel 1 (echo TO-PROBE app_url=UNREACHABLE from this target & >>"%L%" echo TO-PROBE app_url=UNREACHABLE from this target) else (echo TO-PROBE app_url=reachable & >>"%L%" echo TO-PROBE app_url=reachable)
goto appdone
:noappurl
call :p app_url=not-configured
:appdone
call :p done=1
exit /b 0
:p
>>"%L%" echo TO-PROBE %*
echo TO-PROBE %*
exit /b 0
"""


def probe_scripts(app_url: str = "", helper_dir=None) -> dict:
    """Filename -> content for the staged readiness source. The
    credential launchers travel with the probe so the helper_exec
    marker proves the target-native shell + script on the real
    target — a missing payload copy is reported, not hidden."""
    scripts = {
        "probe.sh": PROBE_SH.replace("%APP_URL%", app_url or ""),
        "probe.cmd": PROBE_CMD.replace("%APP_URL%", app_url or "")
                              .replace("\n", "\r\n"),
    }
    for name in ("kre_cred_exec.sh", "kre_cred_exec.ps1"):
        try:
            scripts[".to_" + name] = (Path(helper_dir) / name) \
                .read_text(encoding="utf-8")
        except (OSError, TypeError):
            pass
    return scripts


def probe_argv(os_arch: str) -> list:
    """Entry argv for the probe on the worker — batch on Windows,
    POSIX sh everywhere else."""
    win = (os_arch or "").lower().startswith("win")
    return ["cmd", "/c", "probe.cmd"] if win else ["sh", "probe.sh"]


def helper_launch_for(os_arch: str) -> list:
    """Target-native shell argv prefix that runs the staged credential
    launcher — ``sh`` on POSIX, ``powershell -NoProfile
    -ExecutionPolicy Bypass -File`` on Windows. Both are guaranteed
    by the supported target baseline (SSH needs a shell; the Windows
    cleanup steps already require powershell); no PATH-resolved
    Python is needed for KRE. Dispatch and the readiness probe must
    agree on this choice."""
    return (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File"]
            if (os_arch or "").lower().startswith("win")
            else ["sh"])
