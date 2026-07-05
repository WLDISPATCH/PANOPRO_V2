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
    return log_path


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

    from PySide6.QtCore import QObject, QUrl, Signal, Slot
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
