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


def resolve_render_mode(state_file: Path = _RENDER_STATE_FILE) -> str:
    """Decide 'gpu' or 'software' rendering, with crash auto-fallback.

    Machines vary: a healthy GPU runs great with hardware acceleration (and the
    WebGL 360 viewer), but on some field machines (issues #21/#26/#39) the GPU
    driver faults inside Qt6WebEngineCore.dll and the app crashes at launch. No
    single static default fits both, and SwiftShader (the 2.7.6 attempt) turned
    out to crash healthy machines too (Qt/Chromium shared-image mismatch).

    So we default to the GPU and self-heal: a launch writes a "running"
    sentinel and clears it on clean exit. A new launch that still finds the
    sentinel knows the previous run never exited cleanly and counts a crash;
    after two in a row it permanently falls back to software for this machine.
    Healthy machines exit cleanly and never trip it.

    We require TWO consecutive crashes before falling back, so a one-off
    unclean exit (Task Manager kill, power loss, Windows shutdown) doesn't
    demote a healthy machine — a clean run resets the counter.

    Overrides: PANOPRO_FORCE_GPU=1 pins the GPU (and clears a past fallback);
    PANOPRO_DISABLE_GPU=1 pins software.
    """
    if os.environ.get("PANOPRO_FORCE_GPU") == "1":
        _write_render_state(state_file, {"running": True, "crashes": 0})
        return "gpu"
    if os.environ.get("PANOPRO_DISABLE_GPU") == "1":
        return "software"

    state = _read_render_state(state_file)
    if state.get("mode") == "software":
        return "software"
    # A leftover "running" flag means the previous launch never cleanly exited.
    crashes = int(state.get("crashes", 0))
    if state.get("running"):
        crashes += 1
    if crashes >= 2:
        # Two crashes in a row: this machine's GPU path is genuinely broken.
        _write_render_state(state_file, {"mode": "software"})
        return "software"
    _write_render_state(state_file, {"running": True, "crashes": crashes})
    return "gpu"


def mark_render_clean_exit(state_file: Path = _RENDER_STATE_FILE) -> None:
    """On a clean shutdown, clear the sentinel and reset the crash counter."""
    state = _read_render_state(state_file)
    if state.get("mode") == "software":
        return
    _write_render_state(state_file, {})


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

    'gpu' keeps hardware acceleration (relaxed sandbox) so the WebGL 360 viewer
    works. 'software' disables the GPU entirely — verified stable on a broken
    driver; the 360 viewer's WebGL is unavailable in this mode, but the app no
    longer crashes. PANOPRO_CHROMIUM_FLAGS overrides the string entirely.

    Chromium reads QTWEBENGINE_CHROMIUM_FLAGS during QtWebEngine init, so this
    must run before QApplication is constructed. Returns the applied flags.
    """
    if mode == "software":
        default_flags = "--disable-gpu-sandbox --no-sandbox --disable-gpu --disable-gpu-compositing"
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
    view.setWindowTitle(f"PANO PRO v{__version__}")
    view.resize(1440, 960)
    view.load(QUrl(f"http://127.0.0.1:{port}/"))
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
