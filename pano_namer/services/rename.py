from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pano_namer.services.common import slugify_filename_stem


@dataclass(slots=True)
class RenamePlanItem:
    photo_id: int
    source_path: Path
    original_path: Path
    target_path: Path
    final_name: str
    reservation_id: int | None = None


def preview_renames(photo_rows: list[dict]) -> dict[str, list[dict] | dict[str, int]]:
    plans = plan_renames(photo_rows)
    plan_lookup = {plan.photo_id: plan for plan in plans}
    preview_rows: list[dict] = []
    planned_count = 0
    skipped_count = 0

    for row in sorted(
        photo_rows,
        key=lambda item: (
            item.get("capture_ts") or "",
            item.get("original_path") or "",
        ),
    ):
        plan = plan_lookup.get(row.get("id"))
        if plan:
            planned_count += 1
            preview_rows.append(
                {
                    "photo_id": plan.photo_id,
                    "capture_ts": row.get("capture_ts"),
                    "area_name": row.get("area_name"),
                    "original_path": str(plan.original_path),
                    "target_path": str(plan.target_path),
                    "final_name": plan.final_name,
                    "status": "planned",
                }
            )
            continue

        skipped_count += 1
        if row.get("error"):
            reason = row["error"]
        elif not row.get("capture_ts"):
            reason = "Missing capture timestamp."
        elif not row.get("area_name"):
            reason = "Area is not assigned."
        else:
            reason = "Photo is not eligible for rename."
        preview_rows.append(
            {
                "photo_id": row.get("id"),
                "capture_ts": row.get("capture_ts"),
                "area_name": row.get("area_name"),
                "original_path": row.get("original_path"),
                "target_path": None,
                "final_name": None,
                "status": "skipped",
                "detail": reason,
            }
        )

    return {
        "summary": {"planned": planned_count, "skipped": skipped_count},
        "results": preview_rows,
    }


def build_filename(capture_ts: str, area_name: str, sequence: int, extension: str) -> str:
    stamp = datetime.fromisoformat(capture_ts).strftime("%y%m%d")
    area = slugify_filename_stem(area_name)
    return f"{stamp}_{area}_{sequence:03d}{extension.lower()}"


def plan_renames(photo_rows: list[dict]) -> list[RenamePlanItem]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in photo_rows:
        if row.get("error") or not row.get("capture_ts") or not row.get("area_name"):
            continue
        stamp = datetime.fromisoformat(row["capture_ts"]).strftime("%y%m%d")
        groups[stamp].append(row)

    existing_by_dir: dict[Path, set[str]] = defaultdict(set)
    source_paths = {Path(row["original_path"]).resolve() for row in photo_rows if row.get("original_path")}
    for path in source_paths:
        if path.parent.exists():
            existing_by_dir[path.parent] = {child.name for child in path.parent.iterdir()}

    plans: list[RenamePlanItem] = []
    for _, rows in groups.items():
        rows.sort(key=lambda item: (item["capture_ts"], item["original_path"]))
        sequence = 1
        for row in rows:
            source_path = Path(row["original_path"]).resolve()
            while True:
                candidate = build_filename(row["capture_ts"], row["area_name"], sequence, source_path.suffix)
                target_path = source_path.with_name(candidate)
                occupied = candidate in existing_by_dir[source_path.parent]
                planned_duplicate = any(plan.target_path == target_path for plan in plans)
                occupied_by_source = target_path in source_paths
                if target_path == source_path or (not planned_duplicate and (not occupied or occupied_by_source)):
                    break
                sequence += 1
            existing_by_dir[source_path.parent].add(candidate)
            plans.append(
                RenamePlanItem(
                    photo_id=row["id"],
                    source_path=source_path,
                    original_path=source_path,
                    target_path=target_path,
                    final_name=candidate,
                )
            )
            sequence += 1
    return plans


def apply_rename_plan(plans: list[RenamePlanItem]) -> list[dict]:
    staged: list[tuple[int, Path, Path, Path]] = []
    results: list[dict] = []

    for plan in plans:
        if not plan.source_path.exists():
            results.append(
                {
                    "photo_id": plan.photo_id,
                    "source_path": str(plan.original_path),
                    "target_path": str(plan.target_path),
                    "status": "missing_source",
                }
            )
            continue
        if plan.source_path == plan.target_path:
            results.append(
                {
                    "photo_id": plan.photo_id,
                    "source_path": str(plan.original_path),
                    "target_path": str(plan.target_path),
                    "status": "unchanged",
                }
            )
            continue
        temp_path = plan.source_path.with_name(f".pano_namer_tmp_{uuid4().hex}{plan.source_path.suffix}")
        plan.source_path.rename(temp_path)
        staged.append((plan.photo_id, temp_path, plan.target_path, plan.original_path))

    try:
        for photo_id, temp_path, target_path, original_path in staged:
            temp_path.rename(target_path)
            results.append(
                {
                    "photo_id": photo_id,
                    "source_path": str(original_path),
                    "target_path": str(target_path),
                    "status": "renamed",
                }
            )
    except Exception:
        for _, temp_path, _, original_path in reversed(staged):
            if temp_path.exists():
                temp_path.rename(original_path)
        raise

    return results


def rollback_rename_results(results: list[dict]) -> list[dict]:
    rollback_results: list[dict] = []
    for result in results:
        photo_id = result.get("photo_id")
        source_path = Path(result["source_path"])
        target_path = Path(result["target_path"])
        status = result.get("status")

        if status == "renamed":
            if not target_path.exists():
                rollback_results.append(
                    {
                        "photo_id": photo_id,
                        "source_path": str(source_path),
                        "target_path": str(target_path),
                        "status": "missing_target",
                    }
                )
                continue
            if source_path.exists():
                rollback_results.append(
                    {
                        "photo_id": photo_id,
                        "source_path": str(source_path),
                        "target_path": str(target_path),
                        "status": "blocked_target_exists",
                    }
                )
                continue
            try:
                target_path.rename(source_path)
            except Exception as exc:
                rollback_results.append(
                    {
                        "photo_id": photo_id,
                        "source_path": str(source_path),
                        "target_path": str(target_path),
                        "status": "rollback_error",
                        "detail": str(exc),
                    }
                )
                continue
            rollback_results.append(
                {
                    "photo_id": photo_id,
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "rolled_back",
                }
            )
            continue

        if status == "unchanged":
            rollback_results.append(
                {
                    "photo_id": photo_id,
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "status": "restored_pending",
                }
            )
            continue

        rollback_results.append(
            {
                "photo_id": photo_id,
                "source_path": str(source_path),
                "target_path": str(target_path),
                "status": "not_applicable",
            }
        )

    return rollback_results
