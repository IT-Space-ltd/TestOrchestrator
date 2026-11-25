"""GoogleTest execution adapter.

Run model: on the worker/SSH target, a single driver invocation
performs (1) optional prepare/configure/build commands — only when
the framework project explicitly configured them, never implied —
(2) per-executable `--gtest_list_tests` when native listing is
requested, (3) each selected binary with
``--gtest_filter``/``--gtest_output=xml:Reports/junit/<n>.xml``
``--gtest_color=no --gtest_brief=1``. Build provenance
(configured commands + discovered binary path) and the binary's
SHA-256 are recorded into Reports/build-manifest.json by the
driver script itself — durable evidence next to junit.

Failure taxonomy (classify_exit): 0 ok · 1 tests failed ·
2 build/prepare failure · 3 collection failure ·
4 infrastructure (missing binary).
"""

KIND = "gtest"


def build_script(runs, prepare="", configure="", build="",
                 extra_args=(), list_tests: bool = False,
                 timeout_s: int = 0, run_disabled: bool = False,
                 fail_if_no_test: bool = False) -> str:
    """POSIX driver executed as ``sh -c <script>`` — runs live under
    the staged checkout. ``runs`` = [(exe_path, filter, junit_name)].
    Every argument is single-quoted for the shell — no interpolation
    of test names into command position. GTEST_* env is scrubbed:
    inherited filters/sharding/repetition must never silently alter
    the requested execution (docs correction §3).
    ``run_disabled`` is the explicit disabled-test opt-in;
    ``fail_if_no_test`` emits --gtest_fail_if_no_test_selected where
    the binary supports it (a 0 exit with 0 tests is never PASS)."""
    def q(s):
        return "'" + str(s).replace("'", "'\\''") + "'"

    # Build manifest is appended line-by-line; JSON snippets are
    # literal (no f-strings) so braces/quotes stay unambiguous.
    lines = ["set -u",
             # scrub inherited gtest env — filters/shards/repeats/
             # output targets are set by argv below, never ambient
             "unset GTEST_FILTER GTEST_OUTPUT GTEST_SHARD_INDEX "
             "GTEST_TOTAL_SHARDS GTEST_REPEAT GTEST_SHUFFLE "
             "GTEST_ALSO_RUN_DISABLED_TESTS "
             "GTEST_FAIL_IF_NO_TEST_SELECTED 2>/dev/null || true",
             "R=Reports", "mkdir -p $R/junit",
             'MANIFEST="$R/build-manifest.json"',
             'echo "{" > "$MANIFEST"',
             'echo "  \\"steps\\": [" >> "$MANIFEST"']
    for label, cmd in (("prepare", prepare), ("configure", configure),
                       ("build", build)):
        if not cmd:
            continue
        safe = str(cmd).replace('"', "'").replace("\\", "\\\\")
        lines += [
            f'echo "    {{\\"step\\": \\"{label}\\", \\"command\\": '
            f'\\"{safe}\\", \\"rc\\": \\"" >> "$MANIFEST"',
            f"  echo RUN {label}: {q(cmd)}",
            f"  if sh -c {q(cmd)} > $R/{label}.log 2>&1; then",
            '    echo "0\\"}" >> "$MANIFEST"',
            "  else",
            '    echo "$?, \\"failed\\"}" >> "$MANIFEST"',
            f"    cat $R/{label}.log | tail -50",
            '    echo "]}" >> "$MANIFEST"; exit 2',
            "  fi",
            '    echo "," >> "$MANIFEST"',
        ]
    lines.append('echo "]" >> "$MANIFEST"')
    t = f"timeout {int(timeout_s)} " if timeout_s else ""
    for exe, filt, jname in runs:
        lines += [
            f"  if [ ! -x {q(exe)} ]; then",
            f"    echo 'MISSING BINARY {exe}' >&2",
            "    exit 4",
            "  fi",
            '  echo "  \\"binary\\": \\"'
            + str(exe).replace('"', "'") + '\\"," >> "$MANIFEST"',
            f'  echo "  \\"sha256\\": \\"$(sha256sum {q(exe)} '
            '| cut -d" " -f1)\\"" >> "$MANIFEST"']
        if list_tests:
            lines.append(
                f"  {t}{q(exe)} --gtest_list_tests"
                f" > $R/list-{jname}.txt 2>&1 || exit 3")
        args = " ".join(q(a) for a in extra_args)
        flt = f"--gtest_filter={filt}" if filt else ""
        dis = " --gtest_also_run_disabled_tests" if run_disabled else ""
        if fail_if_no_test:
            # Probe the linked gtest for the flag at run time — an
            # unrecognized --gtest_* flag makes the binary print help
            # and exit 0 having run nothing, the exact silent vacuous
            # pass this option exists to prevent. Support differs per
            # binary (each links its own gtest).
            lines.append(
                f"  if {q(exe)} --gtest_help 2>&1 | "
                "grep -q gtest_fail_if_no_test_selected; then "
                "NZFLAG=' --gtest_fail_if_no_test_selected'; "
                "else NZFLAG=''; fi")
            nz = "$NZFLAG"
        else:
            nz = ""
        lines.append(
            f"  {t}{q(exe)} --gtest_color=no --gtest_brief=1{dis}{nz}"
            f" --gtest_output=xml:$R/junit/{jname}.xml"
            f" {flt} {args} || exit 1")
        lines.append(
            f'  if [ ! -s "$R/junit/{jname}.xml" ]; then'
            f" echo 'NO RESULT XML {jname} — binary produced no "
            "report' >&2; exit 1; fi")
    lines.append('echo "}" >> "$MANIFEST"')
    return "\n".join(lines)


def list_args(executable: str) -> list:
    """Native-collection argv — lists suites/cases without running."""
    return [executable, "--gtest_list_tests"]


def classify_exit(rc: int) -> tuple:
    labels = {
        0: ("ok", "all tests passed"),
        1: ("tests", "tests failed"),
        2: ("config", "prepare/configure/build failure"),
        3: ("config", "collection failure (--gtest_list_tests)"),
        4: ("infrastructure", "test binary missing"),
        124: ("interrupted", "timeout"),
        126: ("infrastructure", "binary not executable"),
        127: ("infrastructure", "binary not found"),
    }
    if rc in labels:
        return labels[rc]
    return "internal", f"unexpected exit status {rc}"


PROBE_SH = """#!/bin/sh
# TestOrchestrator gtest readiness probe (POSIX).
set +e
R=Reports
mkdir -p "$R"
L="$R/probe.txt"; : > "$L"
p() { echo "TO-PROBE $1"; echo "TO-PROBE $1" >> "$L"; }
p "connectivity=ok"
for t in cc c++ gcc g++ clang++ cmake make ninja; do
  command -v $t >/dev/null 2>&1 && p "tool_$t=present" \\
    || p "tool_$t=absent"
done
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
rem TestOrchestrator gtest readiness probe (Windows cmd).
if not exist Reports mkdir Reports
set L=Reports\probe.txt
type nul > "%L%"
rem cmd.exe constraints: 'call :label' is illegal inside if/for parens;
rem 'X && (...) || (...)' can emit BOTH sides — every conditional is
rem a two-line '<test>' + 'if errorlevel 1 (...) else (...)' pair.
call :p connectivity=ok
for %%t in (cc c++ gcc g++ clang++ cmake make ninja cl) do call toolchk.cmd %%t
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

# Helper invoked as 'call toolchk.cmd <tool>' from inside the probe's
# for-loop — 'call :label' is illegal inside for-DO, 'call file.cmd'
# is legal everywhere. %L% is inherited from the caller's env.
TOOLCHK_CMD = r"""@echo off
where %1 >nul 2>&1
if errorlevel 1 (echo TO-PROBE tool_%1=absent & >>"%L%" echo TO-PROBE tool_%1=absent) else (echo TO-PROBE tool_%1=present & >>"%L%" echo TO-PROBE tool_%1=present)
exit /b 0
"""


def probe_scripts(app_url: str = "") -> dict:
    """Readiness — toolchain presence markers; binaries themselves
    are validated per-run (prebuilt or configured build steps)."""
    return {
        "probe.sh": PROBE_SH.replace("%APP_URL%", app_url or ""),
        "probe.cmd": PROBE_CMD.replace("%APP_URL%", app_url or "")
                              .replace("\n", "\r\n"),
        "toolchk.cmd": TOOLCHK_CMD.replace("\n", "\r\n"),
    }


def probe_argv(os_arch: str) -> list:
    """argv for the probe on the worker — batch file on Windows (no
    Bash dependency), POSIX sh elsewhere."""
    win = (os_arch or "").lower().startswith("win")
    return ["cmd", "/c", "probe.cmd"] if win else ["sh", "probe.sh"]
