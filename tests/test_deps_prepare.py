"""deps_prepare (npm ci) semantics: default-on with explicit opt-out,
lockfile early refusal, probe awareness, NEVER during discovery or
preview/native collection."""
import json

from testorchestrator import runner_readiness
from testorchestrator.adapters import nodefw


def test_probe_verdict_accepts_missing_jest_when_npm_present():
    # probe ran before install — jest missing but npm present must not
    # be fatal (npm ci installs at run time)
    probe = {"node": "v24.0.0", "npx": "11.0.0", "npm": "11.0.0",
             "jest": "missing (npx --no-install jest --version failed)"}
    out = runner_readiness._summarize(probe, "jest")
    assert "ready" in out.split("—")[0]
    assert "not resolvable — install" not in out


def test_probe_verdict_still_fatal_without_npm():
    probe = {"node": "missing", "npx": "missing", "npm": "missing",
             "jest": "missing"}
    out = runner_readiness._summarize(probe, "jest")
    assert "not ready" in out


def test_native_collect_never_preps():
    """deps_argv must be empty for native collection — discovery and
    preview never run npm ci."""
    # the dispatch code path keys off rc['native_collect'] — pin the
    # contract at the source level: deps_argv construction excludes
    # native_collect unconditionally.
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch._submit_buildbot)
    assert "native_collect" in src
    # the deps argv is gated on NOT native_collect
    assert 'rc.get("native_collect")' in src
    # and the only deps argv is npm ci behind deps_on
    assert 'deps_argv = ([npm, "ci", "--no-audit", "--no-fund"]' in src
    # the discovery path is the native_collect caller — pin the linkage
    import inspect as _i
    from testorchestrator import gitsync
    nsrc = _i.getsource(gitsync.request_native_collection)
    assert '"native_collect": True' in nsrc


def test_lockfile_refusal_message_present():
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch._submit_buildbot)
    assert "package-lock.json" in src
    assert "deps_prepare=false" in src


def test_prepare_default_on_explicit_off():
    """Contract: deps_prepare defaults on; explicit false disables."""
    import inspect
    from testorchestrator import dispatch
    src = inspect.getsource(dispatch._submit_buildbot)
    assert 'rc.get("deps_prepare", True)' in src
