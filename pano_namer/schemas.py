from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    storage_root: str | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    storage_root: str
    crs: str | None
    created_at: str
    updated_at: str


class AppInfoResponse(BaseModel):
    app_name: str
    version: str
    crs: str
    data_dir: str
    db_path: str
    storage_dir: str
    overlay_preview_dir: str
    thumbnail_dir: str


class CacheCleanupResponse(BaseModel):
    deleted_count: int
    deleted_bytes: int
    kept_count: int
    error_count: int


class SharedNamingSettingsPayload(BaseModel):
    enabled: bool = False
    supabase_url: str = ""
    supabase_anon_key: str = ""
    computer_name: str = ""
    sync_areas: bool = False


class SharedNamingSettingsResponse(BaseModel):
    enabled: bool
    supabase_url: str
    supabase_anon_key: str
    computer_name: str
    default_computer_name: str
    sync_areas: bool


class AreaSyncSummary(BaseModel):
    ok: bool
    error: str | None = None
    pulled_new: int = 0
    pulled_updated: int = 0
    pushed_new: int = 0
    pushed_updated: int = 0
    deactivated: int = 0
    tombstoned: int = 0
    skipped: int = 0


class GlobalAreaSyncRequest(BaseModel):
    project_id: int | None = None


class GlobalAreaSyncSummary(BaseModel):
    ok: bool
    error: str | None = None
    templates_created: int = 0
    created_names: list[str] = Field(default_factory=list)
    templates_synced: int = 0
    errors: list[str] = Field(default_factory=list)
    pulled_new: int = 0
    pulled_updated: int = 0
    pushed_new: int = 0
    pushed_updated: int = 0
    deactivated: int = 0
    tombstoned: int = 0
    skipped: int = 0

    @property
    def changed(self) -> int:  # pragma: no cover - convenience only
        return self.pulled_new + self.pulled_updated + self.deactivated


class SharedNamingTestResponse(BaseModel):
    ok: bool
    error: str | None = None


class SharedNamingPreviewGroup(BaseModel):
    prefix: str
    photos: int
    starts_at: int


class SharedNamingPreviewResponse(BaseModel):
    enabled: bool
    connected: bool
    groups: list[SharedNamingPreviewGroup] = []
    error: str | None = None


class SharedNamingBackfillResponse(BaseModel):
    scanned: int
    matched: int
    added: int


class AreaCreate(BaseModel):
    name: str
    source_path: str | None = None
    display_color: str | None = None
    coordinates: list[list[float]] | None = None


class AreaUpdate(BaseModel):
    name: str | None = None
    source_path: str | None = None
    display_color: str | None = None


class AreaGeometryUpdate(BaseModel):
    # One or more exterior rings, each a list of [x, y] points in the project
    # CRS (EPSG:26912). Sent by the map area editor when geometry is edited.
    parts: list[list[list[float]]]


class AreaResponse(BaseModel):
    id: int
    project_id: int
    name: str
    dxf_original_path: str
    dxf_managed_path: str
    display_color: str
    source_crs: str
    footprint_bbox: list[float]
    active: bool
    created_at: str
    updated_at: str


class OverlayCreate(BaseModel):
    source_path: str


class OverlayUpdate(BaseModel):
    display_name: str | None = None


class OverlayResponse(BaseModel):
    id: int
    project_id: int
    display_name: str | None = None
    jpg_original_path: str
    jpg_managed_path: str
    image_url: str | None = None
    tile_url: str | None = None
    tile_min_zoom: int | None = None
    tile_max_zoom: int | None = None
    crs: str | None
    bounds: list[float] | None
    width: int | None
    height: int | None
    active: bool
    error: str | None
    created_at: str
    updated_at: str


class PhotoImportRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class PhotoImportResult(BaseModel):
    path: str
    status: str
    detail: str | None = None
    photo: "PhotoResponse | None" = None


class PhotoImportResponse(BaseModel):
    imported: list["PhotoResponse"] = Field(default_factory=list)
    results: list[PhotoImportResult] = Field(default_factory=list)
    summary: dict[str, int]


class PhotoDeleteRequest(BaseModel):
    photo_ids: list[int] = Field(default_factory=list)


class PhotoUpdateRequest(BaseModel):
    matched_area_id: int | None = None


class PhotoResponse(BaseModel):
    id: int
    project_id: int
    batch_id: str
    photo_batch_id: int | None = None
    original_path: str
    capture_ts: str | None
    gps_lat: float | None
    gps_lon: float | None
    projected_x: float | None
    projected_y: float | None
    matched_area_id: int | None
    area_name: str | None = None
    match_mode: str | None
    proposed_filename: str | None
    applied: bool
    content_hash: str | None = None
    error: str | None
    created_at: str
    updated_at: str


class PhotoBatchResponse(BaseModel):
    id: int
    project_id: int
    batch_uid: str
    source_kind: str
    actor_label: str | None = None
    client_device: str | None = None
    status: str
    photo_count: int
    created_at: str
    completed_at: str | None = None
    updated_at: str


class ArchiveFolderCreate(BaseModel):
    name: str
    parent_id: int | None = None


class ArchiveAssignRequest(BaseModel):
    photo_ids: list[int] = Field(default_factory=list)
    folder_id: int | None = None


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cover_photo_id: int | None = None


class CollectionItemsRequest(BaseModel):
    photo_ids: list[int] = Field(default_factory=list)


class TagCreate(BaseModel):
    name: str


class PhotoTagsRequest(BaseModel):
    tag_ids: list[int] = Field(default_factory=list)


class SavedFilterCreate(BaseModel):
    name: str
    filter_scope: str
    config: dict[str, Any] = Field(default_factory=dict)


class AnnotationCreate(BaseModel):
    annotation_type: str
    label: str | None = None
    yaw: float
    pitch: float
    style: dict[str, Any] = Field(default_factory=dict)


class NoteCreate(BaseModel):
    note_text: str


class IssueCreate(BaseModel):
    title: str
    issue_text: str | None = None
    severity: str = "medium"
    status: str = "open"
    assigned_to: str | None = None
    yaw: float | None = None
    pitch: float | None = None


class HotspotCreate(BaseModel):
    target_photo_id: int | None = None
    yaw: float
    pitch: float
    label: str | None = None
    disabled: bool = False


class ViewerStateUpdate(BaseModel):
    north_offset: float = 0
    default_yaw: float = 0
    default_pitch: float = 0
    default_fov: float = 75


class ReviewUpdate(BaseModel):
    reviewed: bool


class RenameRunCreate(BaseModel):
    photo_ids: list[int] | None = None


class RenamePreviewResponse(BaseModel):
    summary: dict[str, int]
    results: list[dict[str, Any]]


class RenameReservationsCommitRequest(BaseModel):
    photo_ids: list[int] | None = None
    actor_label: str | None = None
    client_device: str | None = None


class RenameReservationItem(BaseModel):
    reservation_id: int
    photo_id: int
    source_path: str
    target_path: str
    final_name: str
    status: str = "reserved"


class RenameReservationsCommitResponse(BaseModel):
    summary: dict[str, int]
    reservations: list[RenameReservationItem]


class RenameReservationResult(BaseModel):
    photo_id: int
    reservation_id: int
    status: str
    final_path: str | None = None
    error: str | None = None


class RenameReservationReportRequest(BaseModel):
    results: list[RenameReservationResult] = Field(default_factory=list)
    actor_label: str | None = None
    client_device: str | None = None


class RenameReservationReportResponse(BaseModel):
    summary: dict[str, int]
    results: list[dict[str, Any]]


class RenameRunResponse(BaseModel):
    id: int
    project_id: int
    batch_id: str
    started_at: str
    completed_at: str | None
    summary: dict[str, Any]
    results: list[dict[str, Any]]
    rollback_started_at: str | None = None
    rollback_completed_at: str | None = None
    rollback_results: list[dict[str, Any]] = Field(default_factory=list)


PhotoImportResult.model_rebuild()
PhotoImportResponse.model_rebuild()


class SmartSettingsPayload(BaseModel):
    ui_mode: str | None = None
    import_base_path: str | None = None
    archive_base_path: str | None = None
    ftp_host: str | None = None
    ftp_port: int | None = None
    ftp_username: str | None = None
    ftp_password: str | None = None
    ftp_remote_path: str | None = None
    ftp_protocol: str | None = None
    ftp_enabled: bool | None = None
    ignore_folders: list[str] | None = None


class SmartSettingsResponse(BaseModel):
    ui_mode: str
    import_base_path: str
    archive_base_path: str
    ftp_host: str
    ftp_port: int
    ftp_username: str
    ftp_password: str
    ftp_remote_path: str
    ftp_protocol: str
    ftp_enabled: bool
    ignore_folders: list[str] = Field(default_factory=list)


class SmartDrivesResponse(BaseModel):
    drives: list[str] = Field(default_factory=list)


class SmartImportRequest(BaseModel):
    project_id: int
    source_path: str | None = None


class SmartImportResponse(BaseModel):
    source_path: str
    panos_found: int
    normal_skipped: int
    unreadable_skipped: int
    duplicates_skipped: int
    copied: int
    already_copied: int
    staged: int
    registry_checked: bool
    import_summary: dict[str, int]


class SmartExportRequest(BaseModel):
    project_id: int


class SmartExportResponse(BaseModel):
    renamed: int
    registered: int
    uploaded: int
    archived: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class SmartFtpTestResponse(BaseModel):
    ok: bool
    error: str | None = None


class MapDataResponse(BaseModel):
    project: ProjectResponse
    overlay: OverlayResponse | None
    areas: list[dict[str, Any]]
    photos: list[dict[str, Any]]
