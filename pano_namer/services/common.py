from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def slugify_filename_stem(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().upper())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "AREA"


def ensure_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    return path.resolve()


def dumps_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def loads_json(value: str | None, default: object) -> object:
    if not value:
        return default
    return json.loads(value)


def normalize_crs(value: str | None) -> str | None:
    if not value:
        return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(value).to_string()
    except Exception:
        return value
