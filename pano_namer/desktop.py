from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from pano_namer import __version__
from pano_namer.main import create_app

_DESKTOP_STATE_FILE = Path.home() / ".pano_namer_desktop_state.json"
_DESKTOP_LOG_FILE = Path.home() / ".pano_namer_desktop.log"


def enable_crash_logging(log_path: Path = _DESKTOP_LOG_FILE) -> Path | None:
    """Capture crashes to a log file so silent exits become diagnosable.

    The launcher console only shows "exited, error should be shown above"
    with nothing above it when the process dies from a native fault or an
    exception on a background thread. faulthandler catches hard crashes
    (segfaults, aborts, OOM kills) with a Python traceback for every
    thread, and the exception hooks catch the rest.
    """
    import atexit
    import faulthandler
    import traceback
    from datetime import datetime

    try:
        handle = log_path.open("a", encoding="utf-8", errors="replace")
        handle.write(
            f"\n=== PANO PRO v{__version__} started {datetime.now().isoformat(timespec='seconds')} pid={os.getpid()} ===\n"
        )
        handle.flush()
    except OSError:
        return None

    faulthandler.enable(file=handle, all_threads=True)

    def log_exception(exc_type, exc, tb) -> None:
        try:
            handle.write(f"--- unhandled exception {datetime.now().isoformat(timespec='seconds')} ---\n")
            traceback.print_exception(exc_type, exc, tb, file=handle)
            handle.flush()
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    def log_thread_exception(args) -> None:
        log_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = log_exception
    threading.excepthook = log_thread_exception
    atexit.register(handle.flush)
    _append_recent_windows_faults(handle)
    return log_path


def _append_recent_windows_faults(handle) -> None:
    """Record the faulting module of recent native crashes into the log.

    A native access violation (e.g. inside Qt6WebEngineCore.dll) is caught by
    faulthandler as a thread dump, but the dump can't name the guilty DLL —
    only Windows' Application event log records "Faulting module name". On
    startup we pull the last day's Application Error entries for our Python
    process and append them, so the crash log is self-contained and no one
    has to open Event Viewer. Runs in a background thread so it never delays
    launch.
    """
    if sys.platform != "win32":
        return

    def worker() -> None:
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "Get-WinEvent -FilterHashtable @{LogName='Application';"
            "ProviderName='Application Error';Level=2;"
            "StartTime=(Get-Date).AddHours(-24)} |"
            " Where-Object { $_.Message -match 'python' } |"
            " Select-Object -First 5 | ForEach-Object {"
            " $line = ($_.Message -split \"`r?`n\" |"
            " Select-String 'Faulting (module name|application name)') -join ' ';"
            " $_.TimeCreated.ToString('s') + '  ' + $line }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return
        output = (result.stdout or "").strip()
        if not output:
            return
        try:
            handle.write("--- recent Windows faulting modules (Application event log) ---\n")
            handle.write(output + "\n")
            handle.flush()
        except OSError:
            pass

    threading.Thread(target=worker, name="fault-log-scan", daemon=True).start()


_RENDER_STATE_FILE = Path.home() / ".pano_namer_render_state.json"


# Step down a render tier once this many crashes are seen within the window.
_CRASH_FALLBACK_THRESHOLD = 3
_CRASH_WINDOW_DAYS = 30

# Render tiers, most to least hardware-accelerated:
#   gpu       - full hardware acceleration incl. GPU compositing. Crashes the
#               field machines, so it is now opt-in via PANOPRO_FORCE_GPU only.
#   gpu_safe  - DEFAULT. GPU + WebGL still hardware-accelerated, but GPU
#               compositing is disabled so the browser presents the final frame
#               on the CPU. This removes the "Scanout" shared-image path that
#               faults inside Qt6WebEngineCore (issues #21/#26/#39/#42/#53) while
#               keeping the 360 viewer. Reproduced and then prevented on real
#               hardware: --disable-gpu-compositing stops the SharedImage crash
#               and WebGL stays on the GPU. --disable-direct-composition alone
#               (the first attempt) was insufficient on FH-UAV-II.
#   software  - GPU off entirely; stable on broken drivers, no WebGL viewer.
_RENDER_TIERS = ("gpu", "gpu_safe", "software")

# Tiers the auto crash-fallback is allowed to pick. Full "gpu" is opt-in only.
_AUTO_RENDER_TIERS = ("gpu_safe", "software")


def _next_render_tier(tier: str) -> str:
    try:
        index = _RENDER_TIERS.index(tier)
    except ValueError:
        return "gpu_safe"
    return _RENDER_TIERS[min(index + 1, len(_RENDER_TIERS) - 1)]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _recent_crashes(timestamps: list, now_iso: str) -> list:
    """Keep only crash timestamps within the rolling window (unparseable kept)."""
    from datetime import datetime, timedelta

    def parse(value):
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    now = parse(now_iso)
    if now is None:
        return list(timestamps)
    cutoff = now - timedelta(days=_CRASH_WINDOW_DAYS)
    kept = []
    for value in timestamps:
        parsed = parse(value)
        if parsed is None or parsed >= cutoff:
            kept.append(value)
    return kept


def resolve_render_mode(
    state_file: Path = _RENDER_STATE_FILE, now_iso: str | None = None
) -> str:
    """Decide the render tier ('gpu' / 'gpu_safe' / 'software'), self-healing.

    The default is ``gpu_safe``: GPU + WebGL stay hardware-accelerated but GPU
    compositing is disabled, so Chromium never allocates the "Scanout"
    shared-image that faults inside Qt6WebEngineCore.dll on the field machines
    (issues #21/#26/#39/#42/#53). This was reproduced and then prevented on real
    hardware, and confirmed stable on FH-UAV-II under load, so every machine
    gets it from launch #1 — no one has to crash first. Full ``gpu`` (with GPU
    compositing) is opt-in via PANOPRO_FORCE_GPU for anyone who wants it.

    If ``gpu_safe`` itself keeps crashing, the auto-fallback drops to
    ``software`` (GPU off, no WebGL viewer, but rock-solid). Each launch writes a
    "running" sentinel (its start time) that a clean exit removes; a later launch
    that still finds the sentinel records a crash timestamp. Once there are
    ``_CRASH_FALLBACK_THRESHOLD`` crashes within ``_CRASH_WINDOW_DAYS`` days, we
    drop to software and reset the window. The crash history is *rolling*, not
    consecutive — a clean session between crashes no longer resets the count
    (the old "two consecutive" rule never fired in the field, re-reported
    2026-07-15).

    Overrides: PANOPRO_FORCE_GPU=1 pins full GPU (and clears any past fallback
    and crash history); PANOPRO_DISABLE_GPU=1 pins software;
    PANOPRO_RENDER_MODE=gpu|gpu_safe|software pins a specific tier.
    """
    now_iso = now_iso or _now_iso()
    if os.environ.get("PANOPRO_FORCE_GPU") == "1":
        _write_render_state(state_file, {"tier": "gpu", "running": now_iso, "crashes": []})
        return "gpu"
    if os.environ.get("PANOPRO_DISABLE_GPU") == "1":
        return "software"
    pinned = os.environ.get("PANOPRO_RENDER_MODE")
    if pinned in _RENDER_TIERS:
        if pinned != "software":
            _write_render_state(state_file, {"tier": pinned, "running": now_iso, "crashes": []})
        return pinned

    state = _read_render_state(state_file)
    # Legacy hard software pin written by 2.8.x before tiers existed.
    if state.get("mode") == "software":
        return "software"

    # Only gpu_safe/software are auto tiers now. A stored full "gpu" (the old
    # default from <=2.8.1, or a stale value) migrates to the gpu_safe default.
    tier = state.get("tier")
    if tier not in _AUTO_RENDER_TIERS:
        tier = "gpu_safe"
    if tier == "software":
        return "software"

    raw = state.get("crashes")
    crashes = list(raw) if isinstance(raw, list) else []
    running = state.get("running")
    if running:
        # Previous launch never cleared its sentinel -> it crashed. Record when
        # (the crashed run's start time; fall back to now for legacy booleans).
        crashes.append(running if isinstance(running, str) else now_iso)
    crashes = _recent_crashes(crashes, now_iso)

    if len(crashes) >= _CRASH_FALLBACK_THRESHOLD:
        tier = _next_render_tier(tier)
        crashes = []  # fresh window for the new tier
        if tier == "software":
            _write_render_state(state_file, {"tier": "software", "crashes": []})
            return "software"
    _write_render_state(state_file, {"tier": tier, "running": now_iso, "crashes": crashes})
    return tier


def mark_render_clean_exit(state_file: Path = _RENDER_STATE_FILE) -> None:
    """On a clean shutdown, clear only the running sentinel.

    Crucially this preserves the crash history — clearing it here (as an earlier
    version did) is exactly what stopped the auto-fallback from ever firing.
    """
    state = _read_render_state(state_file)
    if state.get("mode") == "software" or state.get("tier") == "software":
        return
    state.pop("running", None)
    _write_render_state(state_file, state)


def _read_render_state(state_file: Path) -> dict:
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_render_state(state_file: Path, data: dict) -> None:
    try:
        state_file.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def configure_webengine(mode: str) -> str:
    """Apply Chromium flags for the chosen render mode before QtWebEngine init.

    'gpu' keeps full hardware acceleration incl. GPU compositing (opt-in). The
    default 'gpu_safe' keeps the GPU and WebGL hardware-accelerated but adds
    --disable-gpu-compositing (browser presents on the CPU) plus
    --disable-direct-composition, which together remove the "Scanout"
    shared-image path that faults inside Qt6WebEngineCore (issues #39/#53) — the
    360 viewer still works. 'software' disables the GPU entirely — verified
    stable on a broken driver; the viewer's WebGL is unavailable in this mode,
    but the app no longer crashes. PANOPRO_CHROMIUM_FLAGS overrides the string
    entirely.

    Chromium reads QTWEBENGINE_CHROMIUM_FLAGS during QtWebEngine init, so this
    must run before QApplication is constructed. Returns the applied flags.
    """
    if mode == "software":
        default_flags = "--disable-gpu-sandbox --no-sandbox --disable-gpu --disable-gpu-compositing"
    elif mode == "gpu_safe":
        default_flags = "--disable-gpu-sandbox --no-sandbox --disable-gpu-compositing --disable-direct-composition"
    else:
        default_flags = "--disable-gpu-sandbox --no-sandbox"
    flags = os.environ.get("PANOPRO_CHROMIUM_FLAGS", default_flags)
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    applied = f"{existing} {flags}".strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = applied
    return applied


def ensure_std_streams() -> None:
    """Guarantee sys.stdout/sys.stderr are real writable streams.

    In windowed / pythonw processes (the Start launcher and the frozen
    no-console exe) these are None. uvicorn configures logging against
    sys.stderr on startup, so a None stream crashes the server thread before
    it binds the port, which surfaces as ERR_CONNECTION_REFUSED in the web
    view. Point any missing stream at devnull so logging has somewhere to go.
    """
    devnull = None
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            if devnull is None:
                devnull = open(os.devnull, "w", encoding="utf-8")
            setattr(sys, name, devnull)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """Block until the local server accepts a connection, or timeout elapses.

    Replaces a fixed sleep so the web view never loads the URL before uvicorn
    is listening (which showed up as ERR_CONNECTION_REFUSED on slower starts).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_server(port: int) -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


def _load_last_picker_dir(state_file: Path = _DESKTOP_STATE_FILE) -> Path | None:
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_path = payload.get("last_picker_dir")
    if not raw_path:
        return None
    path = Path(raw_path)
    return path if path.is_dir() else None


def _save_last_picker_dir(directory: Path, state_file: Path = _DESKTOP_STATE_FILE) -> None:
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"last_picker_dir": str(directory)}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _selection_directory(selection: list[str]) -> Path | None:
    if not selection:
        return None
    first = Path(selection[0])
    if first.is_dir():
        return first
    if first.parent.exists():
        return first.parent
    return None


def main() -> int:
    import atexit

    ensure_std_streams()
    log_path = enable_crash_logging()
    if log_path is not None:
        print(f"Crash log: {log_path}")

    # Choose GPU vs software rendering (auto-falls back to software if a prior
    # launch crashed), then set Qt + Chromium flags before any QtWebEngine
    # import so they take effect. On a clean exit the crash sentinel is cleared.
    render_mode = resolve_render_mode()
    if render_mode == "software":
        # Match the verified-stable config: force Qt itself to software GL too,
        # not just Chromium, so the Qt<->Chromium shared-image path stays off
        # the broken driver (the QDxgiVSyncService crash on FH-UAV-II).
        os.environ["QT_OPENGL"] = "software"
    atexit.register(mark_render_clean_exit)
    applied_flags = configure_webengine(render_mode)
    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"Render mode: {render_mode}\nQtWebEngine flags: {applied_flags}\n")
        except OSError:
            pass

    from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    desktop_dir = Path.home() / "Desktop"
    fallback_dir = desktop_dir if desktop_dir.exists() else Path.home()
    current_dir = _load_last_picker_dir() or fallback_dir

    def pick_directories() -> list[str]:
        nonlocal current_dir
        selections: list[str] = []
        while True:
            directory = QFileDialog.getExistingDirectory(
                None,
                "Select Photo Folder",
                str(current_dir),
                QFileDialog.ShowDirsOnly,
            )
            if not directory:
                break
            if directory not in selections:
                selections.append(directory)
            current_dir = Path(directory)
            _save_last_picker_dir(current_dir)
            choice = QMessageBox.question(
                None,
                "Add Another Folder",
                "Add another folder to this import batch?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if choice != QMessageBox.Yes:
                break
        return selections

    class DesktopBridge(QObject):
        selectionReady = Signal(str, str)

        def _open_files(self, title: str, file_filter: str) -> list[str]:
            nonlocal current_dir
            files, _ = QFileDialog.getOpenFileNames(
                None,
                title,
                str(current_dir),
                file_filter,
            )
            if files:
                next_dir = _selection_directory(files)
                if next_dir is not None:
                    current_dir = next_dir
                    _save_last_picker_dir(current_dir)
            return files

        @Slot(str, str)
        def openDialog(self, request_id: str, kind: str) -> None:
            if kind == "dxf":
                files = self._open_files(
                    "Select Area Files",
                    "Area Files (*.dxf *.kml)",
                )
            elif kind == "overlay":
                files = self._open_files(
                    "Select Georeferenced Overlay",
                    "Overlay Files (*.pdf *.png *.jpg *.jpeg)",
                )
            elif kind == "photos":
                files = self._open_files(
                    "Select Photos",
                    "Images (*.jpg *.jpeg *.png)",
                )
            elif kind == "photo-folder":
                files = pick_directories()
            else:
                files = []
            self.selectionReady.emit(request_id, json.dumps(files))

        @Slot(str, str)
        def openPath(self, path_value: str, mode: str) -> None:
            target = Path(path_value)
            if not target.exists():
                return
            if mode == "folder":
                target = target if target.is_dir() else target.parent
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
                return
            if mode == "reveal":
                subprocess.Popen(["explorer.exe", "/select,", str(target)])
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    port = free_port()
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()
    wait_for_server(port)

    # Qt recommends sharing GL contexts when QtWebEngine is used; without it
    # WebEngine can hit context conflicts on some drivers. Must be set before
    # the QApplication is created.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    view = QWebEngineView()
    channel = QWebChannel(view.page())
    bridge = DesktopBridge()
    channel.registerObject("desktopBridge", bridge)
    view.page().setWebChannel(channel)

    # HTML5 Fullscreen API support. QtWebEngine ignores element.requestFullscreen()
    # unless the setting is enabled AND the page's fullScreenRequested signal is
    # accepted, so the 360 viewer's "Full Screen" button did nothing in the
    # desktop app (it worked in a plain browser). Accept the request and drive
    # the window in/out of fullscreen to match. toggleOn() is true when entering.
    view.page().settings().setAttribute(
        QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True
    )

    def _handle_fullscreen_request(request) -> None:
        request.accept()
        if request.toggleOn():
            view.showFullScreen()
        else:
            view.showNormal()

    view.page().fullScreenRequested.connect(_handle_fullscreen_request)

    view.setWindowTitle(f"PANO PRO v{__version__}")
    view.resize(1440, 960)
    view.load(QUrl(f"http://127.0.0.1:{port}/"))
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
