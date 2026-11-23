#!/usr/bin/env pythonw
"""TestOrchestrator Buildbot worker — system-tray controller.

Launched at user logon via a Startup-folder shortcut (the worker task
itself runs as SYSTEM at boot — a tray icon can only live in an
interactive session). Right-click menu: Start / Stop / Quit, plus a
live status line. Control goes through schtasks — the same interface
the installer uses, no extra service or listener.
"""
from pathlib import Path
import subprocess
import threading
import time

import pystray
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
TASK = "TestOrchestratorBuildbotWorker"
TITLE = "TestOrchestrator Buildbot Worker"
POLL_SECONDS = 2

_GREEN = (34, 139, 34, 255)
_RED = (178, 34, 34, 255)
_OUTLINE = (255, 255, 255, 255)


def _schtasks(*args):
    return subprocess.run(
        ["schtasks", *args], capture_output=True, text=True,
        timeout=30, creationflags=getattr(
            subprocess, "CREATE_NO_WINDOW", 0))


def is_running() -> bool:
    try:
        r = _schtasks("/Query", "/TN", TASK, "/FO", "LIST")
        return " Running" in r.stdout
    except Exception:
        return False


def _state() -> str:
    """'running' | 'stopped' | 'unknown' — unknown means the status
    check itself failed (mapped to red + a saying tooltip, never a
    crash and never green)."""
    try:
        r = _schtasks("/Query", "/TN", TASK, "/FO", "LIST")
        if r.returncode != 0:
            return "unknown"
        return "running" if " Running" in r.stdout else "stopped"
    except Exception:
        return "unknown"


def _dot_icon(base: Image.Image, running: bool) -> Image.Image:
    """Base icon + a small status dot at the bottom-right corner —
    roughly a quarter of the icon width, thin white outline so it
    stays visible on light and dark taskbars."""
    img = base.convert("RGBA").copy()
    w, h = img.size
    d = max(4, w // 4)
    x0, y0, x1, y1 = w - d, h - d, w - 1, h - 1
    draw = ImageDraw.Draw(img)
    ring = max(1, w // 48)
    draw.ellipse([x0 - ring, y0 - ring, x1 + ring, y1 + ring],
                 fill=_OUTLINE)
    draw.ellipse([x0, y0, x1, y1], fill=(_GREEN if running else _RED))
    return img


def _start(icon=None, item=None):
    _schtasks("/Run", "/TN", TASK)
    icon.update_menu() if icon else None


def _stop(icon=None, item=None):
    _schtasks("/End", "/TN", TASK)
    icon.update_menu() if icon else None


_STATE = {"current": "unknown"}


def _status_text(icon=None, item=None):
    s = _STATE["current"]
    if s == "running":
        return "Worker: Running"
    if s == "stopped":
        return "Worker: Not running"
    return "Worker: Not running — status check failed"


def _configure(icon=None, item=None):
    # console window running the interactive reconfigure prompts —
    # os.startfile, not cmd/start: a windowless pythonw + CREATE_NO_
    # WINDOW cannot allocate the console ('Not enough memory
    # resources are available to process this command')
    import os
    os.startfile(str(HERE / "reconfigure-worker.cmd"))


def _noop(*_):
    pass


def _quit(icon, item=None):
    icon.stop()


def _refresh_loop(icon, base: Image.Image) -> None:
    """Cheap background poll — schtasks query every POLL_SECONDS on a
    daemon thread, icon/title/menu update only on a state change, so
    the tray event loop never blocks. On success and on failure the
    dot and text follow _state() (unknown -> red + saying tooltip)."""
    while icon.visible:
        st = _state()
        if st != _STATE["current"]:
            _STATE["current"] = st
            icon.icon = _dot_icon(base, st == "running")
            icon.title = (TITLE if st == "running"
                          else (f"{TITLE} — Not running"
                                if st == "stopped"
                                else f"{TITLE} — Not running "
                                     "(status check failed)"))
            try:
                icon.update_menu()
            except Exception:
                pass
        time.sleep(POLL_SECONDS)


def _start_watcher(icon, base: Image.Image) -> None:
    threading.Thread(target=_refresh_loop, args=(icon, base),
                     daemon=True, name="tray-status").start()


def main() -> None:
    try:
        image = Image.open(HERE / "it.ico")
    except Exception:
        image = Image.new("RGB", (64, 64), (30, 90, 160))
    menu = pystray.Menu(
        pystray.MenuItem(_status_text, _noop),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start", _start),
        pystray.MenuItem("Stop", _stop),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Configure…", _configure),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit),
    )
    _STATE["current"] = _state()
    image = _dot_icon(image, _STATE["current"] == "running")
    icon = pystray.Icon("to-bb-worker", image, TITLE, menu)
    icon.title = TITLE
    _start_watcher(icon, image)
    icon.run()


if __name__ == "__main__":
    main()
