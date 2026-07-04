"""Remote upload of renamed panos for Smart Export (FTP, FTPS, or SFTP).

Uploads are idempotent per photo: callers pass only photos whose
upload_status is not "uploaded", and each file's result is reported
individually so a partial failure can be retried without re-sending
what already made it.
"""

from __future__ import annotations

import ftplib
from dataclasses import dataclass
from pathlib import Path

from pano_namer.services.smart_mode import PROTOCOL_SFTP, SmartModeSettings

UPLOAD_TIMEOUT_SECONDS = 30.0


class FtpExportError(Exception):
    """The upload server could not be reached or rejected the login."""


@dataclass(slots=True)
class UploadItem:
    photo_id: int
    path: Path
    remote_subdir: str = ""


@dataclass(slots=True)
class UploadResult:
    photo_id: int
    filename: str
    status: str  # "uploaded" | "failed"
    detail: str | None = None


def _remote_dir_for(settings: SmartModeSettings, subdir: str) -> str:
    return "/".join(part for part in (settings.ftp_remote_path, subdir) if part)


# ---- FTP / FTPS ----


def _ftp_connect(settings: SmartModeSettings) -> ftplib.FTP:
    ftp_class = ftplib.FTP_TLS if settings.ftp_protocol == "ftps" else ftplib.FTP
    try:
        ftp = ftp_class(timeout=UPLOAD_TIMEOUT_SECONDS)
        ftp.connect(settings.ftp_host, settings.resolved_port())
        ftp.login(settings.ftp_username, settings.ftp_password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
    except (ftplib.all_errors, OSError) as exc:
        raise FtpExportError(
            f"Could not connect to FTP server {settings.ftp_host}: {exc}"
        ) from exc
    return ftp


def _ftp_ensure_dir(ftp: ftplib.FTP, remote_dir: str) -> None:
    for part in [p for p in remote_dir.replace("\\", "/").split("/") if p]:
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def _ftp_upload(
    settings: SmartModeSettings, items: list[UploadItem]
) -> list[UploadResult]:
    results: list[UploadResult] = []
    ftp = _ftp_connect(settings)
    try:
        for item in items:
            try:
                ftp.cwd("/")
                remote_dir = _remote_dir_for(settings, item.remote_subdir)
                if remote_dir:
                    _ftp_ensure_dir(ftp, remote_dir)
                with item.path.open("rb") as handle:
                    ftp.storbinary(f"STOR {item.path.name}", handle)
                results.append(
                    UploadResult(
                        photo_id=item.photo_id,
                        filename=item.path.name,
                        status="uploaded",
                    )
                )
            except (ftplib.all_errors, OSError) as exc:
                results.append(
                    UploadResult(
                        photo_id=item.photo_id,
                        filename=item.path.name,
                        status="failed",
                        detail=str(exc),
                    )
                )
    finally:
        try:
            ftp.quit()
        except (ftplib.all_errors, OSError):
            ftp.close()
    return results


# ---- SFTP ----


def _sftp_upload(
    settings: SmartModeSettings, items: list[UploadItem]
) -> list[UploadResult]:
    import paramiko

    try:
        transport = paramiko.Transport(
            (settings.ftp_host, settings.resolved_port())
        )
        transport.banner_timeout = UPLOAD_TIMEOUT_SECONDS
        transport.connect(
            username=settings.ftp_username, password=settings.ftp_password
        )
        sftp = paramiko.SFTPClient.from_transport(transport)
    except (paramiko.SSHException, OSError) as exc:
        raise FtpExportError(
            f"Could not connect to SFTP server {settings.ftp_host}: {exc}"
        ) from exc

    def ensure_dir(remote_dir: str) -> str:
        current = ""
        for part in [p for p in remote_dir.replace("\\", "/").split("/") if p]:
            current = f"{current}/{part}"
            try:
                sftp.stat(current)
            except FileNotFoundError:
                sftp.mkdir(current)
        return current or "/"

    results: list[UploadResult] = []
    try:
        for item in items:
            try:
                remote_dir = ensure_dir(_remote_dir_for(settings, item.remote_subdir))
                sftp.put(str(item.path), f"{remote_dir.rstrip('/')}/{item.path.name}")
                results.append(
                    UploadResult(
                        photo_id=item.photo_id,
                        filename=item.path.name,
                        status="uploaded",
                    )
                )
            except (paramiko.SSHException, OSError) as exc:
                results.append(
                    UploadResult(
                        photo_id=item.photo_id,
                        filename=item.path.name,
                        status="failed",
                        detail=str(exc),
                    )
                )
    finally:
        sftp.close()
        transport.close()
    return results


# ---- Public API ----


def upload_files(
    settings: SmartModeSettings, items: list[UploadItem]
) -> list[UploadResult]:
    """Upload files, returning a per-file result. Connection errors raise."""
    if not items:
        return []
    if settings.ftp_protocol == PROTOCOL_SFTP:
        return _sftp_upload(settings, items)
    return _ftp_upload(settings, items)


def test_connection(settings: SmartModeSettings) -> None:
    if settings.ftp_protocol == PROTOCOL_SFTP:
        import paramiko

        try:
            transport = paramiko.Transport(
                (settings.ftp_host, settings.resolved_port())
            )
            transport.banner_timeout = UPLOAD_TIMEOUT_SECONDS
            transport.connect(
                username=settings.ftp_username, password=settings.ftp_password
            )
            transport.close()
        except (paramiko.SSHException, OSError) as exc:
            raise FtpExportError(
                f"Could not connect to SFTP server {settings.ftp_host}: {exc}"
            ) from exc
        return
    ftp = _ftp_connect(settings)
    try:
        ftp.voidcmd("NOOP")
    finally:
        try:
            ftp.quit()
        except (ftplib.all_errors, OSError):
            ftp.close()
