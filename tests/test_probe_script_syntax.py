"""Probe scripts must be valid POSIX sh — a syntax error kills the probe
mid-run and the runtime is falsely marked target-unavailable (found in
matrix batch: bruno/postman probes had stray parens)."""
import subprocess

import pytest

from testorchestrator.adapters import (behavefw, brunofw, gtestfw,
                                       nodefw, postmanfw, pytestfw,
                                       robotfw)

PROBES = []
for mod in (nodefw, brunofw, postmanfw, pytestfw, behavefw, robotfw,
            gtestfw):
    for attr in ("PROBE_SH",):
        body = getattr(mod, attr, None)
        if body:
            PROBES.append((mod.__name__, body))


@pytest.mark.parametrize("name,body", PROBES,
                         ids=[p[0] for p in PROBES])
def test_probe_sh_posix_syntax(name, body):
    # substitute the template placeholders the way production does
    body = body.replace("%KIND%", "jest").replace("%APP_URL%", "")
    res = subprocess.run(["sh", "-n"], input=body.encode(),
                         capture_output=True)
    assert res.returncode == 0, \
        f"{name} probe.sh has a syntax error: {res.stderr.decode()[:200]}"
