"""Smart Mode settings: UI mode, import/archive base paths, FTP target."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pano_namer.services.common import utc_now

_SETTING_UI_MODE = "smart_mode.ui_mode"
_SETTING_IMPORT_BASE = "smart_mode.import_base_path"
_SETTING_ARCHIVE_BASE = "smart_mode.archive_base_path"
_SETTING_FTP_HOST = "smart_mode.ftp_host"
_SETTING_FTP_PORT = "smart_mode.ftp_port"
_SETTING_FTP_USERNAME = "smart_mode.ftp_username"
_SETTING_FTP_PASSWORD = "smart_mode.ftp_password"
_SETTING_FTP_REMOTE_PATH = "smart_mode.ftp_remote_path"
_SETTING_FTP_PROTOCOL = "smart_mode.ftp_protocol"

UI_MODE_ADVANCED = "advanced"
UI_MODE_SMART = "smart"

PROTOCOL_FTP = "ftp"
PROTOCOL_FTPS = "ftps"
PROTOCOL_SFTP = "sftp"
UPLOAD_PROTOCOLS = {PROTOCOL_FTP, PROTOCOL_FTPS, PROTOCOL_SFTP}

DEFAULT_PORTS = {PROTOCOL_FTP: 21, PROTOCOL_FTPS: 21, PROTOCOL_SFTP: 22}


@dataclass(slots=True)
class SmartModeSettings:
    ui_mode: str = UI_MODE_ADVANCED
    import_base_path: str = ""
    archive_base_path: str = ""
    ftp_host: str = ""
    ftp_port: int = 0
    ftp_username: str = ""
    ftp_password: str = ""
    ftp_remote_path: str = ""
    ftp_protocol: str = PROTOCOL_FTP

    def ftp_configured(self) -> bool:
        return bool(self.ftp_host and self.ftp_username)

    def resolved_port(self) -> int:
        if self.ftp_port > 0:
            return self.ftp_port
        return DEFAULT_PORTS.get(self.ftp_protocol, 21)


def load_settings(conn: sqlite3.Connection) -> SmartModeSettings:
    rows = conn.execute(
        "SELECT key, value FROM app_settings WHERE key LIKE 'smart_mode.%'"
    ).fetchall()
    values = {row["key"]: row["value"] or "" for row in rows}
    ui_mode = values.get(_SETTING_UI_MODE, "").strip().lower()
    if ui_mode not in {UI_MODE_ADVANCED, UI_MODE_SMART}:
        ui_mode = UI_MODE_ADVANCED
    try:
        ftp_port = int(values.get(_SETTING_FTP_PORT, "").strip() or 0)
    except ValueError:
        ftp_port = 0
    protocol = values.get(_SETTING_FTP_PROTOCOL, "").strip().lower()
    if protocol not in UPLOAD_PROTOCOLS:
        protocol = PROTOCOL_FTP
    return SmartModeSettings(
        ui_mode=ui_mode,
        import_base_path=values.get(_SETTING_IMPORT_BASE, "").strip(),
        archive_base_path=values.get(_SETTING_ARCHIVE_BASE, "").strip(),
        ftp_host=values.get(_SETTING_FTP_HOST, "").strip(),
        ftp_port=ftp_port,
        ftp_username=values.get(_SETTING_FTP_USERNAME, "").strip(),
        ftp_password=values.get(_SETTING_FTP_PASSWORD, ""),
        ftp_remote_path=values.get(_SETTING_FTP_REMOTE_PATH, "").strip(),
        ftp_protocol=protocol,
    )


def save_settings(conn: sqlite3.Connection, settings: SmartModeSettings) -> None:
    now = utc_now()
    values = {
        _SETTING_UI_MODE: settings.ui_mode.strip().lower(),
        _SETTING_IMPORT_BASE: settings.import_base_path.strip(),
        _SETTING_ARCHIVE_BASE: settings.archive_base_path.strip(),
        _SETTING_FTP_HOST: settings.ftp_host.strip(),
        _SETTING_FTP_PORT: str(settings.ftp_port),
        _SETTING_FTP_USERNAME: settings.ftp_username.strip(),
        _SETTING_FTP_PASSWORD: settings.ftp_password,
        _SETTING_FTP_REMOTE_PATH: settings.ftp_remote_path.strip(),
        _SETTING_FTP_PROTOCOL: settings.ftp_protocol.strip().lower(),
    }
    for key, value in values.items():
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
