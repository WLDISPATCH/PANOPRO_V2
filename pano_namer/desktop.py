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


def configure_webengine() -> str:
    """Harden QtWebEngine's Chromium bring-up against GPU crashes.

    Field machines (issues #21, #26) die with an access violation inside
    Qt6WebEngineCore.dll — Chromium's GPU path faulting against the display
    driver, not our code. It happens both at launch and mid-session (e.g. on
    the map), and relaxing only the sandbox was not enough. So by default we
    route Chromium's ANGLE layer through the SwiftShader software backend
    (--use-angle=swiftshader): every bit of GPU work, including WebGL, is done
    in software and the real driver is never touched, which removes the fault.
    Crucially this keeps WebGL working for the 360 viewer (just slower) —
    unlike --disable-gpu, which disables WebGL entirely in Qt 6.9.

    Escape hatches:
      PANOPRO_FORCE_GPU=1     use the real GPU (faster 360 viewer) on machines
                              that are known stable
      PANOPRO_CHROMIUM_FLAGS  replace the default Chromium flag string entirely

    Chromium reads QTWEBENGINE_CHROMIUM_FLAGS during QtWebEngine init, so this
    must run before QApplication is constructed. Returns the applied flags.
    """
    if os.environ.get("PANOPRO_FORCE_GPU") == "1":
        # Opt back into hardware acceleration; keep the sandbox relaxed.
        default_flags = "--disable-gpu-sandbox --no-sandbox"
    else:
        # Software rendering via SwiftShader ANGLE: no real GPU driver, but
        # WebGL still works so the 360 viewer keeps rendering.
        default_flags = "--disable-gpu-sandbox --no-sandbox --use-angle=swiftshader"
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
    ensure_std_streams()
    log_path = enable_crash_logging()
    if log_path is not None:
        print(f"Crash log: {log_path}")

    # Set Chromium flags before any QtWebEngine import so they take effect.
    applied_flags = configure_webengine()
    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"QtWebEngine flags: {applied_flags}\n")
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
