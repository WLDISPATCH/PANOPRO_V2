from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from pano_namer.config import AppConfig


class StorageService:
    def __init__(self, config: AppConfig):
        self.config = config

    def project_dir(self, project_id: int) -> Path:
        path = self.config.storage_dir / f"project_{project_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def copy_into_project(self, project_id: int, category: str, source_path: Path) -> Path:
        dest_dir = self.project_dir(project_id) / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{uuid4().hex}_{source_path.name}"
        shutil.copy2(source_path, dest_path)
        return dest_path
