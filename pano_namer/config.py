from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FIXED_CRS = "EPSG:26912"


def default_data_dir() -> Path:
    return (Path.cwd() / ".pano_namer_data").resolve()


@dataclass(slots=True)
class AppConfig:
    data_dir: Path
    db_path: Path
    storage_dir: Path

    @classmethod
    def load(cls, base_dir: Path | None = None) -> "AppConfig":
        data_dir = (base_dir or default_data_dir()).resolve()
        storage_dir = data_dir / "storage"
        db_path = data_dir / "pano_namer.db"
        return cls(data_dir=data_dir, db_path=db_path, storage_dir=storage_dir)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
