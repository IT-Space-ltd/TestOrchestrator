"""Installer payload completeness — regression for the 2.0.2 defect.

scripts/install.py copied the payload but omitted the vendored
``reporting_labs`` package, so systems installed through the supported
installer could not generate reportingLabs reports
(``ModuleNotFoundError: No module named 'reporting_labs'``). Running the
application from the extracted tarball masked it, because the package
sat next to ``wsgi.py`` at the tarball root. These tests pin the
installer-side behaviour, not the tarball layout.

The vendored source lives at ``3rdparty/reporting_labs`` in both the
checkout and the installed payload; the app's scoped bootstrap finder
(testorchestrator/__init__.py) resolves the ``reporting_labs`` import
name from there.
"""
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import install as inst  # noqa: E402  scripts/install.py


def test_payload_items_all_exist_and_cover_3rdparty():
    """Every declared payload item must exist at the package root —
    the installer aborts on a missing source instead of silently
    producing a half-complete payload. reporting-labs arrives via the
    wholesale 3rdparty copy."""
    assert inst.PAYLOAD_ITEMS, "payload copy list is empty"
    missing = [i for i in inst.PAYLOAD_ITEMS if not (REPO / i).exists()]
    assert not missing, f"payload sources missing: {missing}"
    assert "3rdparty" in inst.PAYLOAD_ITEMS
    assert (REPO / "3rdparty" / "reporting_labs"
            / "__init__.py").is_file()


def test_required_payload_files_cover_reporting():
    """The post-copy completeness gate must include the vendored
    report generator and its licence under 3rdparty/."""
    joined = "\n".join(inst.REQUIRED_PAYLOAD_FILES)
    assert "3rdparty/reporting_labs/__init__.py" in joined
    assert "3rdparty/reporting_labs/LICENSE" in joined


def test_root_copy_is_gone_source_lives_in_3rdparty():
    """The relocation must leave exactly one vendored copy — no stale
    root-level package that could mask a broken payload."""
    assert not (REPO / "reporting_labs").exists(), \
        "stale root-level reporting_labs copy present"


def test_copied_payload_resolves_reporting_labs(tmp_path):
    """Simulate the installed payload (app package + 3rdparty vendored
    dir) in a dir outside the checkout, then resolve reporting_labs
    through the app's own bootstrap — no PYTHONPATH, no manual copy.
    A global site-packages package cannot mask the vendored source
    because the bootstrap pins it, and __file__ proves the location."""
    payload = tmp_path / "payload"
    inst.copy_payload_tree(REPO / "3rdparty",
                           payload / "3rdparty")
    inst.copy_payload_tree(REPO / "testorchestrator",
                           payload / "testorchestrator")
    assert (payload / "3rdparty" / "reporting_labs"
            / "__init__.py").is_file()
    assert (payload / "3rdparty" / "reporting_labs"
            / "LICENSE").is_file()
    r = subprocess.run(
        [sys.executable, "-E", "-s", "-c",
         "import testorchestrator, reporting_labs, sys;"
         "assert reporting_labs.__file__.startswith(sys.argv[1]),"
         " reporting_labs.__file__;"
         "print(reporting_labs.__version__)",
         str(payload)],
        capture_output=True, text=True, cwd=payload)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0.1.14"


def test_bootstrap_resolves_vendored_source():
    """In the checkout itself the bootstrap must produce the vendored
    module — and only the reporting_labs name, nothing else from
    3rdparty becomes importable."""
    finders = [f for f in sys.meta_path
               if type(f).__name__ == "_VendoredReportingLabs"]
    assert finders, "vendored reporting-labs bootstrap not installed"
    spec = finders[0].find_spec("reporting_labs")
    assert spec is not None
    assert str(REPO / "3rdparty" / "reporting_labs") in \
        spec.submodule_search_locations
    # scoped: other 3rdparty dirs must not be handed out by the finder
    assert finders[0].find_spec("dagu") is None
    assert finders[0].find_spec("caddy") is None
    # and the import resolves for real
    import reporting_labs
    assert "3rdparty" in reporting_labs.__file__


def test_isolated_payload_without_package_fails_import(tmp_path):
    """The defect, as a negative control: a payload copy that lacks
    reporting_labs really cannot import it — neither the repo root nor
    site-packages may supply it (isolated mode + site-packages strip,
    since dev environments have carried a stale namespace copy)."""
    r = subprocess.run(
        [sys.executable, "-I", "-c",
         "import sys;"
         "sys.path = [p for p in sys.path if 'site-packages' not in p];"
         "import reporting_labs"],
        capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode != 0
    assert "No module named 'reporting_labs'" in r.stderr


def test_buildbot_venv_uses_installed_runtime_not_extraction_dir(
        tmp_path, monkeypatch):
    """.run regression: the buildbot venv must be based on the
    INSTALLED bundled runtime. sys.executable under the self-extracting
    wrapper is the /tmp/to-install-* extraction dir — a venv created
    from it has a dangling interpreter symlink after cleanup and the
    master can never restart (203/EXEC)."""
    payload = tmp_path / "opt" / "to"
    rt = (payload / "3rdparty" / "python-runtime" / "python" / "bin"
          / "python3")
    rt.parent.mkdir(parents=True)
    rt.write_text("")  # marker — bundled_python() only checks exists()
    wheels = payload / "3rdparty" / "buildbot-wheels"
    wheels.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(inst.subprocess, "check_call",
                        lambda cmd: calls.append(cmd))
    inst.create_buildbot_venv_offline(
        payload, wheels, payload / "buildbot-venv")
    # first call: <installed-runtime> -m venv <bb_venv>
    assert calls[0][0] == str(rt), \
        f"venv based on {calls[0][0]!r} — must be the installed runtime"
    assert calls[0][1:] == ["-m", "venv",
                            str(payload / "buildbot-venv")]
    # pip install runs under the NEW venv's python — offline, pinned
    pip_call = calls[1]
    assert pip_call[0].endswith("buildbot-venv/bin/python3") \
        or pip_call[0].endswith("buildbot-venv\\Scripts\\python.exe")
    assert "--no-index" in pip_call


def test_bundled_python_resolves_payload_path(tmp_path):
    """bundled_python returns the payload-local interpreter only —
    never the running installer's own (extraction-dir) python."""
    assert inst.bundled_python(tmp_path) is None
    rt = (tmp_path / "3rdparty" / "python-runtime" / "python" / "bin"
          / "python3")
    rt.parent.mkdir(parents=True)
    rt.write_text("")
    assert inst.bundled_python(tmp_path) == rt


def test_buildbot_venv_ok_only_when_interpreter_inside_payload(
        tmp_path):
    """Upgrade gate: a venv whose python3 resolves outside the payload
    (dangling .run extraction path, tarball dir, system python) must be
    rebuilt — carrying it forward leaves the master restart-dead."""
    payload = (tmp_path / "opt" / "to").resolve()
    bb_py = payload / "buildbot-venv" / "bin" / "python3"
    bb_py.parent.mkdir(parents=True)

    # missing entirely -> rebuild
    assert inst._buildbot_venv_ok(payload, str(bb_py)) is False

    # dangling symlink to a deleted extraction dir -> rebuild
    bb_py.symlink_to("/tmp/to-install-gone/python/bin/python3")
    assert inst._buildbot_venv_ok(payload, str(bb_py)) is False

    # live target OUTSIDE payload -> rebuild (e.g. old tarball path)
    outside = tmp_path / "elsewhere" / "python3"
    outside.parent.mkdir(parents=True)
    outside.write_text("")
    bb_py.unlink()
    bb_py.symlink_to(str(outside))
    assert inst._buildbot_venv_ok(payload, str(bb_py)) is False

    # live target inside payload -> keep
    inside = (payload / "3rdparty" / "python-runtime" / "python" / "bin"
              / "python3")
    inside.parent.mkdir(parents=True)
    inside.write_text("")
    bb_py.unlink()
    bb_py.symlink_to(str(inside))
    assert inst._buildbot_venv_ok(payload, str(bb_py)) is True


def test_remove_buildbot_venv_unlinks_symlink_never_follows(tmp_path):
    """venv dir itself a symlink -> unlink the link ONLY; the outside
    target (and everything in it) must survive untouched."""
    payload = (tmp_path / "opt" / "to").resolve()
    payload.mkdir(parents=True)
    outside = tmp_path / "elsewhere" / "venv-target"
    outside.mkdir(parents=True)
    marker = outside / "keep-me.txt"
    marker.write_text("important")
    bb_venv = payload / "buildbot-venv"
    bb_venv.symlink_to(str(outside), target_is_directory=True)

    inst._remove_buildbot_venv(payload, bb_venv)

    assert not bb_venv.exists() and not bb_venv.is_symlink()
    assert marker.read_text() == "important"          # target untouched
    assert outside.is_dir()


def test_remove_buildbot_venv_unlinks_dangling_symlink(tmp_path):
    """Dangling symlink (exists() False, is_symlink() True) must still
    be removed — venv creation would otherwise hit FileExistsError."""
    payload = (tmp_path / "opt" / "to").resolve()
    payload.mkdir(parents=True)
    bb_venv = payload / "buildbot-venv"
    bb_venv.symlink_to(str(tmp_path / "gone"), target_is_directory=True)

    inst._remove_buildbot_venv(payload, bb_venv)

    assert not bb_venv.is_symlink()
    assert not (tmp_path / "gone").exists()


def test_remove_buildbot_venv_removes_real_dir_inside_payload(
        tmp_path):
    payload = (tmp_path / "opt" / "to").resolve()
    bb_venv = payload / "buildbot-venv"
    (bb_venv / "bin").mkdir(parents=True)
    (bb_venv / "bin" / "python3").write_text("x")

    inst._remove_buildbot_venv(payload, bb_venv)

    assert not bb_venv.exists()


def test_remove_buildbot_venv_refuses_outside_payload(tmp_path):
    """A path resolving outside the payload is refused, not removed."""
    payload = (tmp_path / "opt" / "to").resolve()
    payload.mkdir(parents=True)
    outside = tmp_path / "somewhere" / "buildbot-venv"
    outside.mkdir(parents=True)
    (outside / "keep").write_text("x")

    import pytest
    with pytest.raises(SystemExit):
        inst._remove_buildbot_venv(payload, outside)
    assert outside.is_dir()
