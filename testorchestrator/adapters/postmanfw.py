"""Postman execution adapter — Newman and Postman CLI engines.

Run model (§3): the engine binary (installed/pinned target tooling,
never auto-installed — newman resolves via ``npx --no-install`` when
no explicit path is configured) runs the selected collection inside
the staged checkout. All reports land under Reports/ for the shared
collect path: junit via the engine's own reporter, json for the
structured outcome, plus the step log.

Engine differences are explicit, not assumed identical:
- newman: ``newman run <collection>`` — folder selection
  (``--folder``, name-based), ``-e/-g/-d`` assets, ``-n``
  iterations, ``--delay-request``, ``--timeout-request``.
- postman-cli: ``postman collection run <collection>`` — flags
  verified per installed version by the readiness probe; not every
  collection format produces identical reporters.

TLS verification stays ON unless the project explicitly configures
``insecure``. ``--export-environment``/``--export-globals`` are
never emitted — resolved secrets must not land in artifacts (§4).
Raw request/response bodies require the explicit ``capture_bodies``
setting; ``--reporter-json-no-body``… is the default direction
(off).
"""

KIND = "postman"
ENGINES = ("newman", "postman-cli")


def build_invocation(engine: str, configured_path: str = "",
                     win: bool = False) -> tuple:
    """(executable, argv_prefix): explicit executable_path wins —
    the runtime's configured binary; otherwise npx resolves the
    pinned repo/newman install without downloading it."""
    if engine == "postman-cli":
        return ((configured_path or "postman"), [])
    if configured_path:
        return configured_path, []
    return ("npx.cmd" if win else "npx"), ["--no-install", "newman"]


def build_args(engine: str, collection: str, folder: str = "",
               paths=(), collection_format: str = "v2.1",
               environment: str = "", globals_file: str = "",
               data: str = "", iterations: int = 0,
               delay_ms: int = 0, timeout_ms: int = 0,
               insecure: bool = False,
               capture_bodies: bool = False) -> list:
    """argv after the engine binary. ``collection`` is the
    checkout-relative file (v2.1) or root directory (v3) the
    inventory recorded — never a cloud UID: signed-in cloud runs
    upload results, so local paths are the default and only mode.

    Format-aware reporting (docs §1): Postman CLI restricts
    --reporters to v2.1 collections; v3 uses --output (raw streamed
    YAML) — the two cannot combine. Newman supports --reporters for
    v2.1 only and cannot execute v3 at all."""
    if engine == "postman-cli":
        args = ["collection", "run", collection]
        for p in paths:
            args += [str(p)]          # v3 request/folder path args
        if folder:
            args += ["--folder", folder]
        if environment:
            args += ["--environment", environment]
        if data:
            args += ["--iteration-data", data]
        if iterations:
            args += ["--iteration-count", str(int(iterations))]
        if delay_ms:
            args += ["--delay-request", str(int(delay_ms))]
        if timeout_ms:
            args += ["--timeout-request", str(int(timeout_ms))]
        if collection_format == "v3":
            # raw streamed YAML — cannot combine with --reporters
            args += ["--output", "Reports/postman.raw.yaml"]
        else:
            args += ["--reporters", "cli,junit",
                     "--reporter-junit-export",
                     "Reports/junit/postman.xml"]
        return args
    args = ["run", collection,
            "--reporters", "cli,junit,json",
            "--reporter-junit-export", "Reports/junit/newman.xml",
            "--reporter-json-export", "Reports/postman.json",
            "--color", "off", "-k" if insecure else ""]
    args = [a for a in args if a]
    if folder:
        args += ["--folder", folder]
    if environment:
        args += ["-e", environment]
    if globals_file:
        args += ["-g", globals_file]
    if data:
        args += ["-d", data]
    if iterations:
        args += ["-n", str(int(iterations))]
    if delay_ms:
        args += ["--delay-request", str(int(delay_ms))]
    if timeout_ms:
        args += ["--timeout-request", str(int(timeout_ms))]
    if not capture_bodies:
        # newman's JSON reporter keeps bodies out with this flag —
        # request/response data can carry tokens/PII (§4).
        args += ["--reporter-json-no-body"]
    return args


def classify_exit(rc: int) -> tuple:
    labels = {
        0: ("ok", "collection run passed"),
        1: ("tests", "assertion/request failures"),
        2: ("config", "collection/assets/configuration error"),
        124: ("interrupted", "timeout"),
        126: ("infrastructure", "engine not executable"),
        127: ("infrastructure", "engine not found"),
    }
    if rc in labels:
        return labels[rc]
    return "internal", f"unexpected exit status {rc}"


PROBE_SH = """#!/bin/sh
# TestOrchestrator postman readiness probe (POSIX).
set +e
R=Reports
mkdir -p "$R"
L="$R/probe.txt"; : > "$L"
p() { echo "TO-PROBE $1"; echo "TO-PROBE $1" >> "$L"; }
p "connectivity=ok"
node --version >/dev/null 2>&1 \\
  && p "node=$(node --version)" || p "node=missing"
npx --version >/dev/null 2>&1 \\
  && p "npx=$(npx --version)" || p "npx=missing"
command -v newman >/dev/null 2>&1 \\
  && p "newman=$(newman --version 2>/dev/null | head -1)" \\
  || (npx --no-install newman --version >/dev/null 2>&1 \\
      && p "newman=$(npx --no-install newman --version | head -1) via npx" \\
      || p "newman=missing (no binary, npx --no-install failed) — the Newman CLI is required — install with: npm install -g newman")
command -v postman >/dev/null 2>&1 \\
  && p "postman_cli=$(postman --version 2>/dev/null | head -1)" \\
  || p "postman_cli=missing"
(command -v newman >/dev/null 2>&1 || command -v postman >/dev/null 2>&1) \\
  && p "postman=engine-present" \\
  || p "postman=missing (no newman/postman CLI on PATH)"
postman collection run --help 2>/dev/null | grep -q junit \\
  && p "postman_junit=supported" \\
  || p "postman_junit=unverified (check installed version docs)"
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
rem TestOrchestrator postman readiness probe (Windows cmd).
if not exist Reports mkdir Reports
set L=Reports\probe.txt
type nul > "%L%"
rem cmd.exe constraints: 'call :label' is illegal inside if/for parens;
rem .cmd shims (newman/postman/npx) invoked bare transfer control and
rem never return — 'call' is mandatory; 'X && (...) || (...)' can emit
rem BOTH sides, so every conditional is a two-line '<test>' +
rem 'if errorlevel 1 (...) else (...)' pair.
call :p connectivity=ok
where node >nul 2>&1
if errorlevel 1 (echo TO-PROBE node=missing & >>"%L%" echo TO-PROBE node=missing) else (for /f "delims=" %%v in ('node --version 2^>nul') do (echo TO-PROBE node=%%v & >>"%L%" echo TO-PROBE node=%%v))
where npx >nul 2>&1
if errorlevel 1 (echo TO-PROBE npx=missing & >>"%L%" echo TO-PROBE npx=missing) else (for /f "delims=" %%v in ('call npx --version 2^>nul') do (echo TO-PROBE npx=%%v & >>"%L%" echo TO-PROBE npx=%%v))
where newman >nul 2>&1
if errorlevel 1 goto nn_npx
for /f "delims=" %%v in ('call newman --version 2^>nul') do (echo TO-PROBE newman=%%v & >>"%L%" echo TO-PROBE newman=%%v)
goto nn_done
:nn_npx
call npx --no-install newman --version >nul 2>&1
if errorlevel 1 (echo TO-PROBE newman=missing ^(no binary, npx --no-install failed^) & >>"%L%" echo TO-PROBE newman=missing ^(no binary, npx --no-install failed^)) else (for /f "delims=" %%v in ('call npx --no-install newman --version 2^>nul') do (echo TO-PROBE newman=%%v via npx & >>"%L%" echo TO-PROBE newman=%%v via npx))
:nn_done
where postman >nul 2>&1
if errorlevel 1 (echo TO-PROBE postman_cli=missing & >>"%L%" echo TO-PROBE postman_cli=missing) else (for /f "delims=" %%v in ('call postman --version 2^>nul') do (echo TO-PROBE postman_cli=%%v & >>"%L%" echo TO-PROBE postman_cli=%%v))
where newman >nul 2>&1
if not errorlevel 1 goto eng_yes
where postman >nul 2>&1
if not errorlevel 1 goto eng_yes
call :p postman=missing ^(no newman/postman CLI on PATH^)
goto eng_done
:eng_yes
call :p postman=engine-present
:eng_done
call postman collection run --help 2>nul | findstr /c:"junit" >nul
if errorlevel 1 (echo TO-PROBE postman_junit=unverified ^(check installed version docs^) & >>"%L%" echo TO-PROBE postman_junit=unverified ^(check installed version docs^)) else (echo TO-PROBE postman_junit=supported & >>"%L%" echo TO-PROBE postman_junit=supported)
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


def probe_scripts(app_url: str = "") -> dict:
    return {
        "probe.sh": PROBE_SH.replace("%APP_URL%", app_url or ""),
        "probe.cmd": PROBE_CMD.replace("%APP_URL%", app_url or "")
                              .replace("\n", "\r\n"),
    }


def probe_argv(os_arch: str) -> list:
    """argv for the probe on the worker — batch file on Windows (no
    Bash dependency), POSIX sh elsewhere."""
    win = (os_arch or "").lower().startswith("win")
    return ["cmd", "/c", "probe.cmd"] if win else ["sh", "probe.sh"]
