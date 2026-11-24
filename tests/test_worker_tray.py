"""Display-free tests for the Windows worker tray status dot.

`pystray` is a Windows-only runtime dependency; it is stubbed in
sys.modules so the pure-PIL drawing logic is exercised headlessly.
"""
import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

sys.modules.setdefault("pystray", types.ModuleType("pystray"))

_spec = importlib.util.spec_from_file_location(
    "worker_tray", Path(__file__).resolve().parent.parent
    / "packaging" / "windows" / "bb-worker-payload-src" / "worker-tray.py")
tray = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tray)

_BASE = Image.new("RGBA", (64, 64), (30, 90, 160, 255))


def _dot_center(size):
    d = max(4, size // 4)
    return (size - 1 - d // 2, size - 1 - d // 2)


@pytest.mark.parametrize("size", [16, 20, 24, 32, 48])
def test_dot_green_bottom_right(size):
    base = _BASE.resize((size, size))
    img = tray._dot_icon(base, running=True)
    # interior of the dot: bottom-right corner region
    px = img.getpixel(_dot_center(size))
    assert px[:3] == tray._GREEN[:3]


@pytest.mark.parametrize("size", [16, 20, 24, 32, 48])
def test_dot_red_bottom_right(size):
    base = _BASE.resize((size, size))
    img = tray._dot_icon(base, running=False)
    px = img.getpixel(_dot_center(size))
    assert px[:3] == tray._RED[:3]


@pytest.mark.parametrize("size", [16, 20, 24, 32, 48])
def test_dot_small_and_corner_untouched(size):
    base = _BASE.resize((size, size))
    img = tray._dot_icon(base, running=True)
    # opposite corner unchanged
    assert img.getpixel((0, 0)) == base.getpixel((0, 0))
    # top edge of the dot area left untouched by fill (outline may ring)
    assert img.getpixel((size - 1, 0)) == base.getpixel((size - 1, 0))


def test_dot_size_bounded_by_quarter():
    size = 48
    img = tray._dot_icon(_BASE.resize((size, size)), running=True)
    # scan a horizontal line through the dot's centre — fill width <= ~1/4+outline
    mid = size - size // 8
    colored = [x for x in range(size)
               if img.getpixel((x, mid))[:3] == tray._GREEN[:3]]
    assert colored and max(colored) - min(colored) + 1 <= size // 4 + 2


def test_dot_has_outline():
    size = 48
    img = tray._dot_icon(_BASE.resize((size, size)), running=True)
    # just outside the green fill on the left edge -> outline pixel
    d = max(4, size // 4)
    ring = max(1, size // 48)
    x, y = size - d - ring, _dot_center(size)[1]
    px = img.getpixel((x, y))
    assert px[:3] == tray._OUTLINE[:3]


def test_transitions():
    img_running = tray._dot_icon(_BASE, running=True)
    img_stopped = tray._dot_icon(_BASE, running=False)
    img_again = tray._dot_icon(_BASE, running=True)
    r, s, a = (img.getpixel(_dot_center(64))[:3]
               for img in (img_running, img_stopped, img_again))
    assert r == tray._GREEN[:3] and s == tray._RED[:3] and a == tray._GREEN[:3]


def test_state_unknown_on_schtasks_error():
    with mock.patch.object(tray, "_schtasks",
                           side_effect=OSError("schtasks missing")):
        assert tray._state() == "unknown"
    fake = types.SimpleNamespace(returncode=1, stdout="")
    with mock.patch.object(tray, "_schtasks", return_value=fake):
        assert tray._state() == "unknown"
    fake = types.SimpleNamespace(returncode=0, stdout="Status:  Running")
    with mock.patch.object(tray, "_schtasks", return_value=fake):
        assert tray._state() == "running"
    fake = types.SimpleNamespace(returncode=0, stdout="Status:  Ready")
    with mock.patch.object(tray, "_schtasks", return_value=fake):
        assert tray._state() == "stopped"


def test_status_text_and_unknown_is_red():
    for st, want_dot, want_text in [
        ("running", tray._GREEN, "Worker: Running"),
        ("stopped", tray._RED, "Worker: Not running"),
        ("unknown", tray._RED, "status check failed"),
    ]:
        tray._STATE["current"] = st
        text = tray._status_text()
        assert want_text in text
        img = tray._dot_icon(_BASE, tray._STATE["current"] == "running")
        assert img.getpixel(_dot_center(64))[:3] == want_dot[:3]


def test_tooltip_text_per_state():
    assert "Running" in tray._title_for("running")
    assert "Not running" in tray._title_for("stopped")
    assert "status check failed" in tray._title_for("unknown")
    assert "connected" not in tray._title_for("running").lower()
