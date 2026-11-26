"""Bruno execution adapter — `bru` CLI (v4 documented; probed).

Run model: ``bru run`` executes FROM the collection root — request
and folder arguments are paths relative to that root, supplied in
order (selection order is preserved end-to-end). Folder recursion
is explicit (``-r``). Sequential is the default; no parallel flag
is emitted — dependency warnings live on the item/config.

Engineering boundaries:
- The CLI is installed target tooling — never auto-installed; the
  readiness probe records ``bru --version`` and probes flag support
  (documented ≠ available in every version).
- Sandbox is explicit: ``--sandbox safe`` default; developer mode
  only when the project config opts in (wider capabilities —
  external modules, filesystem). Module caching is never on by
  default.
- TLS verification ON unless ``insecure`` — requires the explicit
  insecure setting. Client certs/custom CA are paths the project
  configures; credential files must not be collected as artifacts.
- Reporters: dedicated flags (``--reporter-json/--reporter-junit/
  --reporter-html``), not deprecated generic output options. Body/
  header exclusion defaults on — script console output is a
  separate leak channel handled by shared log redaction (§9).
"""

KIND = "bruno"


def build_args(collection_root: str, paths=(), recurse: bool = False,
               environment: str = "", environment_file: str = "",
               global_environment: str = "",
               workspace_path: str = "",
               env_vars=(), global_env_vars=(),
               include_tags=(), exclude_tags=(), tests_only=False,
               bail=False, delay_ms=0, iterations=0,
               data_file="", insecure=False,
               developer_mode=False, module_cache=False,
               cacert="", client_cert="", proxy="",
               no_proxy=False) -> list:
    """argv after ``bru`` — run from ``collection_root`` (the spec
    workdir), paths relative to it, order preserved."""
    args = ["run"] + [str(p) for p in paths if str(p)] if paths \
        else ["run"]
    if recurse:
        args += ["-r"]
    if environment:
        args += ["--env", environment]
    if environment_file:
        args += ["--env-file", environment_file]
    if workspace_path:
        args += ["--workspace-path", workspace_path]
    if global_environment:
        args += ["--global-env", global_environment]
    for kv in env_vars:
        args += ["--env-var", kv]          # secrets → argv exposure
    for kv in global_env_vars:             # requires --global-env
        args += ["--global-env-var", kv]
    if include_tags:
        args += ["--tags-include", ",".join(include_tags)]
    if exclude_tags:
        args += ["--tags-exclude", ",".join(exclude_tags)]
    if tests_only:
        args += ["--tests-only"]
    if bail:
        args += ["--bail"]
    if delay_ms:
        args += ["--delay", str(int(delay_ms))]
    if iterations:
        args += ["--iteration-count", str(int(iterations))]
    if data_file:
        args += ["--iteration-data", data_file]
    if developer_mode:
        args += ["--sandbox", "developer"]
    else:
        args += ["--sandbox", "safe"]
    if module_cache:                       # explicit opt-in only
        args += ["--enable-module-cache"]
    if cacert:
        args += ["--cacert", cacert]
    if client_cert:
        args += ["--client-cert-config", client_cert]
    if proxy:
        args += ["--proxy", proxy]
    if no_proxy:
        args += ["--noproxy"]
    if insecure:                           # explicit acknowledgment
        args += ["--insecure"]
    # Dedicated reporter flags land durable artifacts under Reports/
    args += ["--reporter-json", "Reports/bruno.json",
             "--reporter-junit", "Reports/junit/bruno.xml",
             "--reporter-html", "Reports/bruno.html"]
    return args


def classify_exit(rc: int) -> tuple:
    labels = {
        0: ("ok", "collection run passed"),
        1: ("tests", "request/assertion failures"),
        2: ("config", "collection/flag/configuration error"),
        124: ("interrupted", "timeout"),
        126: ("infrastructure", "bru not executable"),
        127: ("infrastructure", "bru not installed"),
    }
    if rc in labels:
        return labels[rc]
    return "internal", f"unexpected exit status {rc}"


PROBE_SH = """#!/bin/sh
# TestOrchestrator bruno readiness probe (POSIX).
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
command -v bru >/dev/null 2>&1 \\
  && p "bruno=$(bru --version 2>/dev/null | head -1)" \\
  || p "bruno=missing — the Bruno CLI (@usebruno/cli) is required, never auto-installed — install with: npm install -g @usebruno/cli")
bru run --help 2>/dev/null | grep -q -- '--sandbox' \\
  && p "sandbox_flag=supported" || p "sandbox_flag=unverified"
bru run --help 2>/dev/null | grep -q -- '--global-env' \\
  && p "global_env=supported" || p "global_env=unverified"
bru run --help 2>/dev/null | grep -q -- '--reporter-junit' \\
  && p "junit_reporter=supported" || p "junit_reporter=unverified"
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
rem TestOrchestrator bruno readiness probe (Windows cmd).
if not exist Reports mkdir Reports
set L=Reports\probe.txt
type nul > "%L%"
rem cmd.exe constraints: 'call :label' is illegal inside if/for parens;
rem .cmd shims (bru/npx) invoked bare transfer control and never
rem return — 'call' is mandatory; 'X && (...) || (...)' can emit BOTH
rem sides, so every conditional is a two-line '<test>' +
rem 'if errorlevel 1 (...) else (...)' pair.
call :p connectivity=ok
where node >nul 2>&1
if errorlevel 1 (echo TO-PROBE node=missing & >>"%L%" echo TO-PROBE node=missing) else (for /f "delims=" %%v in ('node --version 2^>nul') do (echo TO-PROBE node=%%v & >>"%L%" echo TO-PROBE node=%%v))
where npx >nul 2>&1
if errorlevel 1 (echo TO-PROBE npx=missing & >>"%L%" echo TO-PROBE npx=missing) else (for /f "delims=" %%v in ('call npx --version 2^>nul') do (echo TO-PROBE npx=%%v & >>"%L%" echo TO-PROBE npx=%%v))
where bru >nul 2>&1
if errorlevel 1 (echo TO-PROBE bruno=missing ^(installed/pinned CLI required - never auto-installed^) & >>"%L%" echo TO-PROBE bruno=missing ^(installed/pinned CLI required - never auto-installed^)) else (for /f "delims=" %%v in ('call bru --version 2^>nul') do (echo TO-PROBE bruno=%%v & >>"%L%" echo TO-PROBE bruno=%%v))
call bru run --help 2>nul | findstr /c:"--sandbox" >nul
if errorlevel 1 (echo TO-PROBE sandbox_flag=unverified & >>"%L%" echo TO-PROBE sandbox_flag=unverified) else (echo TO-PROBE sandbox_flag=supported & >>"%L%" echo TO-PROBE sandbox_flag=supported)
call bru run --help 2>nul | findstr /c:"--global-env" >nul
if errorlevel 1 (echo TO-PROBE global_env=unverified & >>"%L%" echo TO-PROBE global_env=unverified) else (echo TO-PROBE global_env=supported & >>"%L%" echo TO-PROBE global_env=supported)
call bru run --help 2>nul | findstr /c:"--reporter-junit" >nul
if errorlevel 1 (echo TO-PROBE junit_reporter=unverified & >>"%L%" echo TO-PROBE junit_reporter=unverified) else (echo TO-PROBE junit_reporter=supported & >>"%L%" echo TO-PROBE junit_reporter=supported)
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
