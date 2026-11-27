"""A node-framework runtime misconfigured with `node` as its executable
passes the PATH probes but dies at dispatch with 'bad option:
--no-install' (found in matrix wave-3: jest runs produced no result
data). The probe must test the configured executable with the exact
npx-style invocation shape dispatch uses, and the readiness summary
must name the misconfiguration."""
import os
import stat
import subprocess
import tempfile

from testorchestrator.adapters import nodefw
from testorchestrator.runner_readiness import _summarize


def _run_check(exe, d):
    check = '''XE="%s"
[ -z "$XE" ] && XE=npx
if "$XE" --no-install --version >/dev/null 2>&1; then
  echo "exec_invocation=ok"
else
  echo "exec_invocation=incompatible"
fi''' % exe
    env = dict(os.environ, PATH=d + ":" + os.environ["PATH"])
    return subprocess.run(["sh", "-c", check], capture_output=True,
                          text=True, env=env).stdout


def test_probe_embeds_configured_executable():
    scripts = nodefw.probe_scripts("jest", "", exe="/opt/x/node")
    assert 'XE="/opt/x/node"' in scripts["probe.sh"]
    # default (no exe configured) leaves the template empty -> PATH npx
    scripts = nodefw.probe_scripts("jest", "")
    assert 'XE=""' in scripts["probe.sh"]
    # windows cmd carries the same substitution
    scripts = nodefw.probe_scripts("jest", "", exe="C:\\n\\npx.cmd")
    assert "set XE=C:\\n\\npx.cmd" in scripts["probe.cmd"]


def test_exec_invocation_shape_posix():
    d = tempfile.mkdtemp()
    node = os.path.join(d, "node")
    with open(node, "w") as fh:
        fh.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = "--no-install" ]'
                 ' && { echo "bad option" >&2; exit 9; }; done\n'
                 'echo v24.0.0\n')
    os.chmod(node, 0o755)
    npx = os.path.join(d, "npx")
    with open(npx, "w") as fh:
        fh.write('#!/bin/sh\necho 11.0.0\nexit 0\n')
    os.chmod(npx, 0o755)
    assert "incompatible" in _run_check(node, d)
    assert "exec_invocation=ok" in _run_check(npx, d)
    assert "exec_invocation=ok" in _run_check("", d)  # PATH npx fallback


def test_summarize_names_misconfigured_executable():
    msg = _summarize(
        {"exec_invocation": "incompatible - the configured executable "
                            "'/usr/local/bin/node' cannot consume "
                            "npx-style arguments",
         "node": "v24.0.0", "npx": "11.0.0"}, "jest")
    assert "npx-style" in msg
    # absent marker (older probe output) must not block readiness
    msg2 = _summarize({"node": "v24.0.0", "npx": "11.0.0"}, "jest")
    assert "npx-style" not in msg2


def test_probe_sh_still_posix_clean():
    body = nodefw.probe_scripts("jest", "", exe="/x/npx")["probe.sh"]
    res = subprocess.run(["sh", "-n"], input=body.encode(),
                         capture_output=True)
    assert res.returncode == 0, res.stderr.decode()[:200]
