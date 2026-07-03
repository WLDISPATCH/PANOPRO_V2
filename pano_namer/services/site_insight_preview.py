from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PREVIEW_TIMEOUT_SECONDS = 45


@dataclass(frozen=True, slots=True)
class PreviewResult:
    status: str
    error: str | None = None


def safe_preview_error(message: str | None) -> str | None:
    if not message:
        return None
    cleaned = " ".join(message.replace("\x00", "").split())
    return cleaned[:240] or None


def generate_preview(model_path: Path, preview_path: Path, *, timeout_seconds: int = PREVIEW_TIMEOUT_SECONDS) -> PreviewResult:
    """Generate a model preview with F3D when the binary is available.

    F3D is optional for SITE-INSIGHT incubation. Uploads must continue to work
    even on servers that do not have GPU/software rendering dependencies ready.
    """

    f3d_path = shutil.which("f3d")
    if not f3d_path:
        return PreviewResult(status="skipped", error="F3D is not installed.")

    preview_path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for backend in ("egl", "osmesa"):
        command = [
            f3d_path,
            str(model_path),
            "--output",
            str(preview_path),
            f"--rendering-backend={backend}",
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"{backend}: preview generation timed out")
            continue
        except OSError as exc:
            errors.append(f"{backend}: {exc}")
            continue

        if completed.returncode == 0 and preview_path.exists():
            return PreviewResult(status="succeeded")

        detail = completed.stderr or completed.stdout or f"F3D exited with {completed.returncode}"
        errors.append(f"{backend}: {detail}")

    if preview_path.exists():
        preview_path.unlink(missing_ok=True)
    return PreviewResult(status="failed", error=safe_preview_error("; ".join(errors)))
