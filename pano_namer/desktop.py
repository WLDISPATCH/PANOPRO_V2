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


def main() -> int:
    ensure_std_streams()

    from PySide6.QtCore import QObject, QUrl, Signal, Slot
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    desktop_dir = Path.home() / "Desktop"
    default_dir = str(desktop_dir if desktop_dir.exists() else Path.home())

    def pick_directories() -> list[str]:
        selections: list[str] = []
        current_dir = default_dir
        while True:
            directory = QFileDialog.getExistingDirectory(
                None,
                "Select Photo Folder",
                current_dir,
                QFileDialog.ShowDirsOnly,
            )
            if not directory:
                break
            if directory not in selections:
                selections.append(directory)
            current_dir = directory
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

        @Slot(str, str)
        def openDialog(self, request_id: str, kind: str) -> None:
            if kind == "dxf":
                files, _ = QFileDialog.getOpenFileNames(
                    None,
                    "Select Area Files",
                    default_dir,
                    "Area Files (*.dxf *.kml)",
                )
            elif kind == "overlay":
                files, _ = QFileDialog.getOpenFileNames(
                    None,
                    "Select Georeferenced Overlay",
                    default_dir,
                    "Overlay Files (*.pdf *.png *.jpg *.jpeg)",
                )
            elif kind == "photos":
                files, _ = QFileDialog.getOpenFileNames(
                    None,
                    "Select Photos",
                    default_dir,
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
