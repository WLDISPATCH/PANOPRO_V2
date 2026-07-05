const state = {
  appInfo: null,
  projects: [],
  currentProjectId: null,
  archiveFolders: [],
  archivePhotos: [],
  collections: [],
  collectionDetail: null,
  tags: [],
  savedFilters: [],
  duplicatePairs: [],
  auditEvents: [],
  areas: [],
  photos: [],
  overlay: null,
  overlays: [],
  runs: [],
  mapData: null,
  mapDataSerialized: null,
  selectedOverlayId: null,
  mapDataLoading: false,
  mapDataError: null,
  mapDataRequestKey: null,
  hoveredPhotoId: null,
  selectedPhotoId: null,
  mapAreaDraftPhotoId: null,
  mapAreaDraftId: null,
  mapAreaMenuOpen: false,
  pendingAreaMenuPhotoId: null,
  pendingAreaMenuScope: null,
  selectedPhotoIds: new Set(),
  collapsedProcessedGroups: new Set(),
  seenProcessedGroups: new Set(),
  leaflet: null,
  mapDataVersion: 0,
  sharedNamingSettings: null,
  smartSettings: null,
  smartBusy: false,
  areaSyncInFlight: false,
  areaSyncRefreshing: false,
  collectionMapTransform: null,
  busyDepth: 0,
  suppressHover: false,
  openCustomSelectId: null,
  currentArchiveFolderId: null,
  currentCollectionId: null,
  viewerPayload: null,
  viewerImageCache: {},
  viewerContext: { source: "viewer", collectionId: null },
  viewerPose: null,
  viewerDrag: null,
  pendingView: {
    sortBy: "date_desc",
    search: "",
    showOriginal: true,
    showDate: true,
    showProposed: true,
  },
  mapVisibility: {
    showProcessed: false,
  },
  mapLabels: {
    enabled: false,
    showOriginal: false,
    showProposed: true,
  },
  drawArea: {
    active: false,
    points: [],
    name: "",
    color: "#175c4c",
  },
  bridge: null,
  modalResolver: null,
};

const DEG2RAD = Math.PI / 180;
const TWO_PI = Math.PI * 2;

const elements = {
  projectForm: document.getElementById("project-form"),
  projectName: document.getElementById("project-name"),
  projectSelect: document.getElementById("project-select"),
  refreshButton: document.getElementById("refresh-button"),
  deleteProjectButton: document.getElementById("delete-project-button"),
  overlayImportButton: document.getElementById("overlay-import-button"),
  overlayWorkspace: document.getElementById("overlay-workspace"),
  overlayEmptyState: document.getElementById("overlay-empty-state"),
  overlayLibraryCard: document.getElementById("overlay-library-card"),
  overlayCardTitle: document.getElementById("overlay-card-title"),
  overlayCardNote: document.getElementById("overlay-card-note"),
  overlayCardStatus: document.getElementById("overlay-card-status"),
  overlayTable: document.getElementById("overlay-table"),
  renameButton: document.getElementById("rename-button"),
  rollbackButton: document.getElementById("rollback-button"),
  sharedNamingEnabled: document.getElementById("shared-naming-enabled"),
  sharedNamingUrl: document.getElementById("shared-naming-url"),
  sharedNamingKey: document.getElementById("shared-naming-key"),
  sharedNamingComputer: document.getElementById("shared-naming-computer"),
  sharedNamingSaveButton: document.getElementById("shared-naming-save-button"),
  sharedNamingTestButton: document.getElementById("shared-naming-test-button"),
  sharedNamingStatus: document.getElementById("shared-naming-status"),
  sharedNamingBackfillButton: document.getElementById("shared-naming-backfill-button"),
  sharedNamingBackfillResult: document.getElementById("shared-naming-backfill-result"),
  sharedNamingSyncAreas: document.getElementById("shared-naming-sync-areas"),
  areaSyncNowButton: document.getElementById("area-sync-now-button"),
  areaSyncResult: document.getElementById("area-sync-result"),
  modeToggleButton: document.getElementById("mode-toggle-button"),
  smartActionbar: document.getElementById("smart-actionbar"),
  smartImportButton: document.getElementById("smart-import-button"),
  smartExportButton: document.getElementById("smart-export-button"),
  reviewEyebrow: document.getElementById("review-eyebrow"),
  reviewTitle: document.getElementById("review-title"),
  reviewDescription: document.getElementById("review-description"),
  smartImportBase: document.getElementById("smart-import-base"),
  smartArchiveBase: document.getElementById("smart-archive-base"),
  smartFtpHost: document.getElementById("smart-ftp-host"),
  smartFtpPort: document.getElementById("smart-ftp-port"),
  smartFtpUsername: document.getElementById("smart-ftp-username"),
  smartFtpPassword: document.getElementById("smart-ftp-password"),
  smartFtpRemotePath: document.getElementById("smart-ftp-remote-path"),
  smartFtpProtocol: document.getElementById("smart-ftp-protocol"),
  smartFtpEnabled: document.getElementById("smart-ftp-enabled"),
  smartSettingsSaveButton: document.getElementById("smart-settings-save-button"),
  smartFtpTestButton: document.getElementById("smart-ftp-test-button"),
  smartSettingsStatus: document.getElementById("smart-settings-status"),
  smartProgressModal: document.getElementById("smart-progress-modal"),
  smartProgressTitle: document.getElementById("smart-progress-title"),
  smartProgressSummary: document.getElementById("smart-progress-summary"),
  smartProgressSteps: document.getElementById("smart-progress-steps"),
  smartProgressLive: document.getElementById("smart-progress-live"),
  smartProgressLiveText: document.getElementById("smart-progress-live-text"),
  smartProgressCloseButton: document.getElementById("smart-progress-close-button"),
  appVersionBadge: document.getElementById("app-version-badge"),
  statusPill: document.getElementById("status-pill"),
  tabs: [...document.querySelectorAll(".tab")],
  panels: [...document.querySelectorAll(".panel")],
  areasTable: document.getElementById("areas-table"),
  addAreaButton: document.getElementById("add-area-button"),
  addBlankAreaButton: document.getElementById("add-blank-area-button"),
  areaFileInput: document.getElementById("area-file-input"),
  overlayFileInput: document.getElementById("overlay-file-input"),
  photoFileInput: document.getElementById("photo-file-input"),
  photoFolderInput: document.getElementById("photo-folder-input"),
  photosTable: document.getElementById("photos-table"),
  processedTable: document.getElementById("processed-table"),
  photoFilter: document.getElementById("photo-filter"),
  pendingCount: document.getElementById("pending-count"),
  pendingGuidance: document.getElementById("pending-guidance"),
  pendingTotalCount: document.getElementById("pending-total-count"),
  pendingReadyCount: document.getElementById("pending-ready-count"),
  pendingAttentionCount: document.getElementById("pending-attention-count"),
  pendingNearestCount: document.getElementById("pending-nearest-count"),
  pendingMetadataCount: document.getElementById("pending-metadata-count"),
  pendingSearch: document.getElementById("pending-search"),
  photosHeaderRow: document.getElementById("photos-header-row"),
  importPhotosButton: document.getElementById("import-photos-button"),
  importFolderButton: document.getElementById("import-folder-button"),
  pendingShowOriginalToggle: document.getElementById("pending-show-original-toggle"),
  pendingShowDateToggle: document.getElementById("pending-show-date-toggle"),
  pendingShowProposedToggle: document.getElementById("pending-show-proposed-toggle"),
  selectAllPendingButton: document.getElementById("select-all-pending-button"),
  removeSelectedPendingButton: document.getElementById("remove-selected-pending-button"),
  selectAllProcessedButton: document.getElementById("select-all-processed-button"),
  removeSelectedProcessedButton: document.getElementById("remove-selected-processed-button"),
  archiveFolderName: document.getElementById("archive-folder-name"),
  createArchiveFolderButton: document.getElementById("create-archive-folder-button"),
  archiveSelectedButton: document.getElementById("archive-selected-button"),
  archiveFoldersList: document.getElementById("archive-folders-list"),
  archivePhotosTable: document.getElementById("archive-photos-table"),
  collectionName: document.getElementById("collection-name"),
  createCollectionButton: document.getElementById("create-collection-button"),
  addSelectedToCollectionButton: document.getElementById("add-selected-to-collection-button"),
  exportCollectionCsvButton: document.getElementById("export-collection-csv-button"),
  exportCollectionPdfButton: document.getElementById("export-collection-pdf-button"),
  collectionsList: document.getElementById("collections-list"),
  collectionMapSvg: document.getElementById("collection-map-svg"),
  collectionPhotosTable: document.getElementById("collection-photos-table"),
  collectionViewerCanvas: document.getElementById("collection-viewer-canvas"),
  collectionViewerOverlay: document.getElementById("collection-viewer-overlay"),
  viewerCanvas: document.getElementById("viewer-canvas"),
  viewerOverlay: document.getElementById("viewer-overlay"),
  viewerSelectedName: document.getElementById("viewer-selected-name"),
  viewerSelectedState: document.getElementById("viewer-selected-state"),
  viewerAreaName: document.getElementById("viewer-area-name"),
  viewerMatchMode: document.getElementById("viewer-match-mode"),
  viewerCaptureDate: document.getElementById("viewer-capture-date"),
  viewerReviewStatus: document.getElementById("viewer-review-status"),
  viewerArchiveStatus: document.getElementById("viewer-archive-status"),
  viewerTagsCount: document.getElementById("viewer-tags-count"),
  viewerIssuesCount: document.getElementById("viewer-issues-count"),
  viewerNotesCount: document.getElementById("viewer-notes-count"),
  viewerStageTitle: document.getElementById("viewer-stage-title"),
  viewerStageBadge: document.getElementById("viewer-stage-badge"),
  viewerEmptyState: document.getElementById("viewer-empty-state"),
  viewerDetailsBody: document.getElementById("viewer-details-body"),
  viewerDetailStatus: document.getElementById("viewer-detail-status"),
  viewerOpenMapButton: document.getElementById("viewer-open-map-button"),
  viewerFullscreenButton: document.getElementById("viewer-fullscreen-button"),
  viewerPrevButton: document.getElementById("viewer-prev-button"),
  viewerNextButton: document.getElementById("viewer-next-button"),
  viewerOpenFileButton: document.getElementById("viewer-open-file-button"),
  viewerOpenFolderButton: document.getElementById("viewer-open-folder-button"),
  viewerRevealButton: document.getElementById("viewer-reveal-button"),
  viewerNorthOffset: document.getElementById("viewer-north-offset"),
  viewerDefaultYaw: document.getElementById("viewer-default-yaw"),
  saveViewerStateButton: document.getElementById("save-viewer-state-button"),
  viewerTagsList: document.getElementById("viewer-tags-list"),
  viewerTagsBadge: document.getElementById("viewer-tags-badge"),
  viewerTagName: document.getElementById("viewer-tag-name"),
  addViewerTagButton: document.getElementById("add-viewer-tag-button"),
  annotationLabel: document.getElementById("annotation-label"),
  addAnnotationButton: document.getElementById("add-annotation-button"),
  viewerAnnotationsList: document.getElementById("viewer-annotations-list"),
  viewerAnnotationsBadge: document.getElementById("viewer-annotations-badge"),
  issueTitle: document.getElementById("issue-title"),
  addIssueButton: document.getElementById("add-issue-button"),
  viewerIssuesList: document.getElementById("viewer-issues-list"),
  viewerIssuesBadge: document.getElementById("viewer-issues-badge"),
  viewerNoteText: document.getElementById("viewer-note-text"),
  addNoteButton: document.getElementById("add-note-button"),
  viewerNotesList: document.getElementById("viewer-notes-list"),
  viewerNotesBadge: document.getElementById("viewer-notes-badge"),
  addHotspotButton: document.getElementById("add-hotspot-button"),
  viewerHotspotsList: document.getElementById("viewer-hotspots-list"),
  viewerHotspotsBadge: document.getElementById("viewer-hotspots-badge"),
  auditTable: document.getElementById("audit-table"),
  dropzone: document.getElementById("dropzone"),
  mapCanvas: document.getElementById("map-canvas"),
  leafletMap: document.getElementById("leaflet-map"),
  mapStateOverlay: document.getElementById("map-state-overlay"),
  mapDetail: document.getElementById("map-detail-body"),
  mapAreaCount: document.getElementById("map-area-count"),
  mapPendingCount: document.getElementById("map-pending-count"),
  mapProcessedCount: document.getElementById("map-processed-count"),
  mapSelectedLabel: document.getElementById("map-selected-label"),
  mapSelectedStatus: document.getElementById("map-selected-status"),
  mapOverlayStatus: document.getElementById("map-overlay-status"),
  mapDataStatus: document.getElementById("map-data-status"),
  mapDataDetail: document.getElementById("map-data-detail"),
  drawAreaButton: document.getElementById("draw-area-button"),
  mapShowProcessedToggle: document.getElementById("map-show-processed-toggle"),
  mapLabelsToggle: document.getElementById("map-labels-toggle"),
  mapOriginalLabelToggle: document.getElementById("map-original-label-toggle"),
  mapProposedLabelToggle: document.getElementById("map-proposed-label-toggle"),
  zoomResetButton: document.getElementById("zoom-reset-button"),
  runsTable: document.getElementById("runs-table"),
  busyOverlay: document.getElementById("busy-overlay"),
  busyMessage: document.getElementById("busy-message"),
  busyDetail: document.getElementById("busy-detail"),
  appModal: document.getElementById("app-modal"),
  appModalForm: document.getElementById("app-modal-form"),
  appModalKicker: document.getElementById("app-modal-kicker"),
  appModalTitle: document.getElementById("app-modal-title"),
  appModalDescription: document.getElementById("app-modal-description"),
  appModalFields: document.getElementById("app-modal-fields"),
  appModalTextWrap: document.getElementById("app-modal-text-wrap"),
  appModalTextLabel: document.getElementById("app-modal-text-label"),
  appModalTextInput: document.getElementById("app-modal-text-input"),
  appModalColorWrap: document.getElementById("app-modal-color-wrap"),
  appModalColorInput: document.getElementById("app-modal-color-input"),
  appModalCancelButton: document.getElementById("app-modal-cancel-button"),
  appModalPrimaryButton: document.getElementById("app-modal-primary-button"),
};

function fmtDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function shortPath(value) {
  if (!value) return "-";
  const bits = value.split(/[/\\]/);
  return bits.slice(-2).join("\\");
}

function baseName(value) {
  if (!value) return "";
  const bits = value.split(/[/\\]/);
  return bits[bits.length - 1] || value;
}

function fileExtension(value) {
  const name = baseName(value);
  const match = name.match(/\.([^.]+)$/);
  return match ? match[1].toUpperCase() : "-";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stemName(value) {
  return baseName(value).replace(/\.[^.]+$/, "").trim();
}

function closeAppModal(result = null) {
  if (!elements.appModal || elements.appModal.hidden) return;
  elements.appModal.hidden = true;
  document.body.classList.remove("is-modal-open");
  elements.appModalForm.classList.remove("danger");
  const resolver = state.modalResolver;
  state.modalResolver = null;
  if (resolver) resolver(result);
}

function showAppModal(options = {}) {
  const {
    title = "Action Required",
    description = "Complete this action to continue.",
    kicker = "PANO PRO",
    primaryLabel = "Continue",
    textLabel = "Name",
    textValue = "",
    textPlaceholder = "",
    showText = true,
    showColor = false,
    colorValue = "#175c4c",
    danger = false,
  } = options;

  if (state.modalResolver) {
    closeAppModal(null);
  }

  elements.appModalKicker.textContent = kicker;
  elements.appModalTitle.textContent = title;
  elements.appModalDescription.textContent = description;
  elements.appModalPrimaryButton.textContent = primaryLabel;
  elements.appModalTextLabel.textContent = textLabel;
  elements.appModalTextInput.value = textValue || "";
  elements.appModalTextInput.placeholder = textPlaceholder || "";
  elements.appModalColorInput.value = colorValue || "#175c4c";
  elements.appModalTextWrap.hidden = !showText;
  elements.appModalColorWrap.hidden = !showColor;
  elements.appModalFields.hidden = !showText && !showColor;
  elements.appModalForm.classList.toggle("danger", Boolean(danger));
  elements.appModal.hidden = false;
  document.body.classList.add("is-modal-open");
  requestAnimationFrame(() => (showText ? elements.appModalTextInput : elements.appModalPrimaryButton).focus());

  return new Promise((resolve) => {
    state.modalResolver = resolve;
  });
}

function showTextModal(options = {}) {
  return showAppModal({ ...options, showText: true }).then((result) => result?.text || "");
}

function showAreaModal(options = {}) {
  return showAppModal({ ...options, showText: true, showColor: true }).then((result) => result);
}

function showDecisionModal(options = {}) {
  return showAppModal({ ...options, showText: false, showColor: false }).then((result) => Boolean(result?.accepted));
}

function compareText(left, right) {
  return (left || "").localeCompare(right || "", undefined, { sensitivity: "base", numeric: true });
}

function badge(label, kind = "") {
  return `<span class="badge ${kind}">${label}</span>`;
}

function rgbaFromHex(hex, alpha) {
  const normalized = (hex || "#175c4c").replace("#", "");
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function resetDrawArea() {
  state.drawArea = {
    active: false,
    points: [],
    name: "",
    color: "#175c4c",
  };
}

function pendingPhotos() {
  return state.photos.filter((photo) => !photo.applied);
}

function processedPhotos() {
  return state.photos.filter((photo) => photo.applied);
}

function photoHasMetadataIssue(photo) {
  return Boolean(photo.error || !photo.capture_ts || photo.projected_x == null || photo.projected_y == null);
}

function photoReadyToRename(photo) {
  return Boolean(!photo.error && photo.matched_area_id && photo.proposed_filename && photo.capture_ts);
}

function photoNeedsAttention(photo) {
  return !photoReadyToRename(photo) || photo.match_mode === "nearest" || photoHasMetadataIssue(photo);
}

function matchBadgeForPhoto(photo) {
  if (photo.error) return badge("Error", "error");
  if (!photo.capture_ts) return badge("Missing Date", "warn");
  if (photo.projected_x == null || photo.projected_y == null) return badge("Missing GPS", "warn");
  if (photo.match_mode === "manual") return badge("Manual");
  if (photo.match_mode === "nearest") return badge("Nearest", "warn");
  if (!photo.matched_area_id) return badge("Unmatched", "warn");
  return badge("Inside");
}

function processedPhotoGroups() {
  const photoToRun = new Map();
  for (const run of state.runs) {
    for (const result of run.results || []) {
      if (result.status === "renamed" || result.status === "unchanged") {
        photoToRun.set(result.photo_id, run);
      }
    }
  }

  const grouped = new Map();
  for (const photo of processedPhotos()) {
    const run = photoToRun.get(photo.id) || null;
    const key = run ? `run-${run.id}` : `unassigned-${photo.batch_id || photo.id}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        key,
        run,
        label: run ? fmtDate(run.started_at || run.completed_at) : `Older processed photos`,
        photos: [],
      });
    }
    grouped.get(key).photos.push(photo);
  }

  return [...grouped.values()]
    .sort((left, right) => {
      const leftTime = left.run ? Date.parse(left.run.started_at || left.run.completed_at || "") : 0;
      const rightTime = right.run ? Date.parse(right.run.started_at || right.run.completed_at || "") : 0;
      return rightTime - leftTime;
    })
    .map((group) => ({
      ...group,
      photos: group.photos.sort((left, right) => {
        const leftTime = Date.parse(left.capture_ts || "") || 0;
        const rightTime = Date.parse(right.capture_ts || "") || 0;
        return leftTime - rightTime;
      }),
    }));
}

async function api(path, options = {}) {
  const { timeoutMs = 15000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = timeoutMs > 0
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null;
  let response;
  try {
    const headers = fetchOptions.body instanceof FormData
      ? { ...(fetchOptions.headers || {}) }
      : { "Content-Type": "application/json", ...(fetchOptions.headers || {}) };
    response = await fetch(path, {
      signal: controller.signal,
      ...fetchOptions,
      headers,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("Request timed out while loading project data.");
    }
    throw error;
  } finally {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_error) {
      // Ignore JSON parse failures.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function setStatus(message, isError = false) {
  elements.statusPill.textContent = message;
  elements.statusPill.style.background = isError ? "rgba(143, 45, 45, 0.14)" : "";
  elements.statusPill.style.color = isError ? "#8f2d2d" : "";
}

function requireCurrentProject(actionLabel) {
  if (state.currentProjectId) return true;
  setStatus(`Select a template before you ${actionLabel}.`, true);
  return false;
}

function customSelectNodes(select) {
  const shell = select?.nextElementSibling;
  if (!shell || !shell.classList.contains("app-select")) return null;
  return {
    shell,
    trigger: shell.querySelector(".app-select-trigger"),
    label: shell.querySelector(".app-select-label"),
    menu: shell.querySelector(".app-select-menu"),
  };
}

function closeCustomSelect(selectId = null) {
  const targets = [elements.projectSelect, elements.photoFilter];
  for (const select of targets) {
    const id = select.dataset.customSelectId;
    if (selectId && id !== selectId) continue;
    const nodes = customSelectNodes(select);
    if (!nodes) continue;
    nodes.shell.classList.remove("is-open");
    nodes.trigger?.setAttribute("aria-expanded", "false");
  }
  if (!selectId || state.openCustomSelectId === selectId) {
    state.openCustomSelectId = null;
  }
}

function syncCustomSelect(select) {
  const nodes = customSelectNodes(select);
  if (!nodes) return;
  const selectedOption = select.options[select.selectedIndex] || select.options[0] || null;
  nodes.label.textContent = selectedOption?.textContent || "Select";
  nodes.menu.innerHTML = [...select.options].map((option) => `
    <button
      class="app-select-option ${option.value === select.value ? "is-active" : ""}"
      type="button"
      data-select-option-value="${option.value.replace(/"/g, "&quot;")}"
    >
      ${option.textContent}
    </button>
  `).join("");
}

function ensureCustomSelect(select) {
  if (!select) return;
  if (!select.dataset.customSelectId) {
    select.dataset.customSelectId = `${select.id || "select"}-${Math.random().toString(16).slice(2)}`;
  }
  if (!customSelectNodes(select)) {
    const shell = document.createElement("div");
    shell.className = "app-select";
    shell.dataset.customSelectId = select.dataset.customSelectId;
    shell.innerHTML = `
      <button class="app-select-trigger secondary" type="button" aria-expanded="false">
        <span class="app-select-label"></span>
        <span class="app-select-caret">▾</span>
      </button>
      <div class="app-select-menu"></div>
    `;
    select.classList.add("native-select-hidden");
    select.setAttribute("tabindex", "-1");
    select.insertAdjacentElement("afterend", shell);
  }
  syncCustomSelect(select);
}

function setBusy(active, message = "Working…", detail = "Please wait while the app finishes the current task.") {
  if (active) {
    state.busyDepth += 1;
    elements.busyMessage.textContent = message;
    elements.busyDetail.textContent = detail;
    elements.busyOverlay.hidden = false;
    document.body.classList.add("is-busy");
    return;
  }

  state.busyDepth = Math.max(0, state.busyDepth - 1);
  if (state.busyDepth > 0) {
    return;
  }
  elements.busyOverlay.hidden = true;
  document.body.classList.remove("is-busy");
}

async function withBusy(message, detail, action) {
  setBusy(true, message, detail);
  try {
    return await action();
  } finally {
    setBusy(false);
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function currentProject() {
  let project = state.projects.find((item) => item.id === state.currentProjectId) || null;
  const selectedProjectId = Number(elements.projectSelect.value) || null;
  if (!project && selectedProjectId) {
    project = state.projects.find((item) => item.id === selectedProjectId) || null;
    if (project) {
      state.currentProjectId = project.id;
    }
  }
  return project;
}

// Routes legacy tab names (still used throughout the code and in deep links
// between features) onto the six navigation destinations, optionally landing
// on a specific mode inside a composite destination.
const TAB_ROUTES = {
  home: { tab: "setup" },
  dashboard: { tab: "setup" },
  setup: { tab: "setup" },
  areas: { tab: "setup" },
  overlay: { tab: "setup" },
  process: { tab: "process" },
  photos: { tab: "process" },
  completed: { tab: "completed" },
  processed: { tab: "completed" },
  runs: { tab: "process", expand: "runs" },
  map: { tab: "review", mode: "map" },
  viewer: { tab: "review", mode: "viewer" },
  review: { tab: "review" },
  library: { tab: "library" },
  archive: { tab: "library", mode: "archive" },
  collections: { tab: "library", mode: "collections" },
  system: { tab: "system" },
  settings: { tab: "system", mode: "settings" },
  audit: { tab: "system", mode: "audit" },
};

function setModeSections(kind, mode) {
  document.querySelectorAll(`[data-${kind}-mode]`).forEach((button) => {
    button.classList.toggle("active", button.dataset[`${kind}Mode`] === mode);
  });
  document.querySelectorAll(`[data-${kind}-section]`).forEach((section) => {
    section.classList.toggle("active", section.dataset[`${kind}Section`] === mode);
  });
}

function setReviewMode(mode) {
  state.reviewMode = mode;
  setModeSections("review", mode);
  if (mode === "map") {
    maybeRefreshMapForTab("map");
    // Leaflet measures a hidden container as 0x0; re-measure now that the
    // section is visible (class toggles above force a synchronous layout)
    // and complete any fit that was deferred while the map was hidden.
    const leaf = state.leaflet;
    if (leaf) {
      leaf.map.invalidateSize();
      if (!leaf.fitted) {
        fitMapToData(leaf);
      }
    }
  }
}

function setLibraryMode(mode) {
  state.libraryMode = mode;
  setModeSections("library", mode);
}

function setSystemMode(mode) {
  state.systemMode = mode;
  setModeSections("system", mode);
  if (mode === "settings") {
    maybeLoadSettingsForTab("settings");
  }
}

function setProcessSection(name, open) {
  const section = document.querySelector(`[data-process-section="${name}"]`);
  if (!section) return;
  section.hidden = !open;
  const toggle = document.getElementById(`process-${name}-toggle`);
  if (toggle) {
    const label = name === "runs" ? "Recent Runs" : "Processed";
    toggle.textContent = `${label} ${open ? "▴" : "▾"}`;
  }
}

function setTab(tabName) {
  const route = TAB_ROUTES[tabName] || { tab: tabName };
  elements.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === route.tab));
  elements.panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === route.tab));
  if (route.tab === "review") {
    setReviewMode(route.mode || state.reviewMode || "map");
  } else if (route.tab === "library") {
    setLibraryMode(route.mode || state.libraryMode || "archive");
  } else if (route.tab === "system") {
    setSystemMode(route.mode || state.systemMode || "settings");
  }
  if (route.expand) {
    setProcessSection(route.expand, true);
  }
}

function maybeRefreshMapForTab(tabName) {
  if (tabName === "map" && state.currentProjectId && !state.mapData && !state.mapDataLoading) {
    refreshMapData().catch(() => {
      // Error state is handled inside refreshMapData.
    });
  }
}

function ensureBridge() {
  if (!window.QWebChannel || !window.qt || state.bridge) return;
  new QWebChannel(qt.webChannelTransport, (channel) => {
    state.bridge = channel.objects.desktopBridge || null;
  });
}

function pickPathsFallback(kind) {
  setStatus(`File path selection is only available in the desktop app. Use the ${kind} file picker in the web app.`, true);
  return [];
}

function pickPaths(kind) {
  ensureBridge();
  if (!state.bridge) {
    return Promise.resolve(pickPathsFallback(kind));
  }
  return new Promise((resolve) => {
    const requestId = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const handler = (replyId, payload) => {
      if (replyId !== requestId) return;
      state.bridge.selectionReady.disconnect(handler);
      resolve(JSON.parse(payload));
    };
    state.bridge.selectionReady.connect(handler);
    state.bridge.openDialog(requestId, kind);
  });
}

function usingDesktopBridge() {
  ensureBridge();
  return Boolean(state.bridge);
}

function chooseBrowserFiles(input) {
  return new Promise((resolve) => {
    const handler = () => resolve([...input.files]);
    input.value = "";
    input.addEventListener("change", handler, { once: true });
    input.click();
  });
}

function buildUploadFormData(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file, file.webkitRelativePath || file.name);
  }
  return formData;
}

async function loadProjects() {
  state.projects = await api("/api/projects");
  elements.projectSelect.innerHTML = "";
  if (!state.projects.length) {
    elements.projectSelect.innerHTML = `<option value="">Create a template to begin</option>`;
    syncCustomSelect(elements.projectSelect);
    state.currentProjectId = null;
    state.areas = [];
    state.photos = [];
    state.overlay = null;
    state.overlays = [];
    state.runs = [];
    state.archiveFolders = [];
    state.archivePhotos = [];
    state.collections = [];
    state.collectionDetail = null;
    state.tags = [];
    state.savedFilters = [];
    state.duplicatePairs = [];
    state.auditEvents = [];
    state.mapData = null;
    state.mapDataLoading = false;
    state.mapDataError = null;
    state.mapDataRequestKey = null;
    resetDrawArea();
    state.collapsedProcessedGroups = new Set();
    state.seenProcessedGroups = new Set();
    renderAll();
    return;
  }

  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.name}${project.crs ? ` (${project.crs})` : ""}`;
    elements.projectSelect.appendChild(option);
  }

  if (!state.currentProjectId || !state.projects.some((project) => project.id === state.currentProjectId)) {
    state.currentProjectId = state.projects[0].id;
  }
  elements.projectSelect.value = String(state.currentProjectId);
  syncCustomSelect(elements.projectSelect);
  await refreshProjectData();
}

async function loadAppInfo() {
  state.appInfo = await api("/api/app-info");
}

async function refreshProjectData() {
  const selectedProjectId = Number(elements.projectSelect.value) || null;
  if (!state.currentProjectId && selectedProjectId) {
    state.currentProjectId = selectedProjectId;
  }
  if (!state.currentProjectId) {
    state.areas = [];
    state.photos = [];
    state.overlay = null;
    state.overlays = [];
    state.runs = [];
    state.archiveFolders = [];
    state.archivePhotos = [];
    state.collections = [];
    state.collectionDetail = null;
    state.tags = [];
    state.savedFilters = [];
    state.duplicatePairs = [];
    state.auditEvents = [];
    state.mapData = null;
    state.mapDataLoading = false;
    state.mapDataError = null;
    state.mapDataRequestKey = null;
    renderAll();
    return;
  }
  const projectId = state.currentProjectId;
  const [areas, photos, overlay, overlays, runs, archiveLibrary, collections, tags, savedFilters, duplicatePairs, auditEvents] = await Promise.all([
    api(`/api/projects/${projectId}/areas`),
    api(`/api/projects/${projectId}/photos`),
    api(`/api/projects/${projectId}/overlay`),
    api(`/api/projects/${projectId}/overlays`),
    api(`/api/projects/${projectId}/rename-runs`),
    api(`/api/archive/library`),
    api(`/api/collections`),
    api(`/api/tags`),
    api(`/api/saved-filters`),
    api(`/api/projects/${projectId}/duplicates`),
    api(`/api/audit-events`),
  ]);
  state.areas = areas;
  state.photos = photos;
  state.overlay = overlay;
  state.overlays = overlays;
  state.runs = runs;
  state.archiveFolders = archiveLibrary.folders || [];
  state.archivePhotos = archiveLibrary.photos || [];
  state.collections = collections;
  state.tags = tags;
  state.savedFilters = savedFilters;
  state.duplicatePairs = duplicatePairs;
  state.auditEvents = auditEvents;
  // A failed collection-detail fetch must never abort the refresh — that
  // would leave the whole UI unrendered (empty tables, "v-" badge).
  try {
    if (!state.currentCollectionId || !state.collections.some((item) => item.id === state.currentCollectionId)) {
      state.currentCollectionId = state.collections[0]?.id || null;
    }
    state.collectionDetail = state.currentCollectionId
      ? await api(`/api/collections/${state.currentCollectionId}/detail`)
      : null;
  } catch (_error) {
    state.collectionDetail = null;
  }
  state.mapData = null;
  state.mapDataLoading = true;
  state.mapDataError = null;
  const validIds = new Set(state.photos.map((photo) => photo.id));
  state.selectedPhotoIds = new Set([...state.selectedPhotoIds].filter((photoId) => validIds.has(photoId)));
  if (state.selectedPhotoId && !validIds.has(state.selectedPhotoId)) {
    state.selectedPhotoId = null;
  }
  renderAll();
  refreshMapData(projectId).catch(() => {
    // Error state is handled inside refreshMapData.
  });
  maybeRunAreaSync(projectId);
}

// Fire-and-forget area sync: runs after each project refresh when enabled.
// A second refresh is triggered only when the sync pulled changes, and the
// in-flight/again guards keep that from looping.
async function maybeRunAreaSync(projectId) {
  if (!projectId || state.areaSyncInFlight) return;
  state.areaSyncInFlight = true;
  try {
    if (!state.sharedNamingSettings) {
      state.sharedNamingSettings = await api("/api/settings/shared-naming");
    }
    if (!state.sharedNamingSettings.sync_areas) return;
    const summary = await api(`/api/projects/${projectId}/area-sync/run`, {
      method: "POST",
      body: JSON.stringify({}),
      timeoutMs: 60000,
    });
    reportAreaSync(summary);
    const pulledChanges = summary.ok
      && (summary.pulled_new + summary.pulled_updated + summary.deactivated) > 0;
    if (pulledChanges && state.currentProjectId === projectId && !state.areaSyncRefreshing) {
      state.areaSyncRefreshing = true;
      try {
        await refreshProjectData();
      } finally {
        state.areaSyncRefreshing = false;
      }
    }
  } catch (error) {
    if (elements.areaSyncResult) {
      elements.areaSyncResult.textContent = `Area sync failed: ${error.message}`;
    }
  } finally {
    state.areaSyncInFlight = false;
  }
}

// New-computer bootstrap: with no local templates, pull everything the
// network knows about (templates are auto-created server-side) so a fresh
// session starts with the same parameters as everyone else.
async function maybeBootstrapFromNetwork() {
  if (state.projects.length || state.areaSyncInFlight) return;
  state.areaSyncInFlight = true;
  try {
    if (!state.sharedNamingSettings) {
      state.sharedNamingSettings = await api("/api/settings/shared-naming");
    }
    const settings = state.sharedNamingSettings;
    if (!settings.sync_areas || !settings.supabase_url || !settings.supabase_anon_key) return;
    setStatus("Checking the shared network for templates…");
    const summary = await api("/api/area-sync/run", {
      method: "POST",
      body: JSON.stringify({ project_id: null }),
      timeoutMs: 120000,
    });
    reportAreaSync(summary);
    if (summary.ok && summary.templates_created > 0) {
      state.areaSyncInFlight = false;
      await loadProjects();
    }
  } catch (error) {
    if (elements.areaSyncResult) {
      elements.areaSyncResult.textContent = `Network bootstrap failed: ${error.message}`;
    }
  } finally {
    state.areaSyncInFlight = false;
  }
}

function reportAreaSync(summary) {
  if (!elements.areaSyncResult) return;
  if (!summary.ok) {
    elements.areaSyncResult.textContent = `Area sync unavailable: ${summary.error || "unknown error"}`;
    return;
  }
  const parts = [];
  if (summary.templates_created) {
    parts.push(`${summary.templates_created} template${summary.templates_created === 1 ? "" : "s"} created (${(summary.created_names || []).join(", ")})`);
  }
  if (summary.pulled_new) parts.push(`${summary.pulled_new} pulled`);
  if (summary.pulled_updated) parts.push(`${summary.pulled_updated} updated`);
  if (summary.pushed_new) parts.push(`${summary.pushed_new} pushed`);
  if (summary.pushed_updated) parts.push(`${summary.pushed_updated} re-pushed`);
  if (summary.deactivated) parts.push(`${summary.deactivated} removed`);
  if (summary.tombstoned) parts.push(`${summary.tombstoned} deletions pushed`);
  if (summary.skipped) parts.push(`${summary.skipped} skipped`);
  let text = parts.length ? `Areas synced: ${parts.join(", ")}.` : "Areas are in sync.";
  if (summary.errors && summary.errors.length) {
    text += ` Problems: ${summary.errors.join(" ")}`;
  }
  elements.areaSyncResult.textContent = text;
  if (parts.length) {
    setStatus(`Areas synced: ${parts.join(", ")}.`);
  }
}

async function refreshMapData(projectId = state.currentProjectId) {
  if (!projectId) {
    state.mapData = null;
    state.mapDataLoading = false;
    state.mapDataError = null;
    state.mapDataRequestKey = null;
    renderMap();
    return;
  }
  const requestKey = `${projectId}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  state.mapDataRequestKey = requestKey;
  state.mapDataLoading = true;
  state.mapDataError = null;
  renderMap();
  try {
    const mapData = await api(`/api/projects/${projectId}/map-data`, { timeoutMs: 30000 });
    if (state.currentProjectId !== projectId || state.mapDataRequestKey !== requestKey) {
      return;
    }
    // Only bump the version when the payload actually changed; the version
    // invalidates the Leaflet layer cache, and rebuilding every polygon and
    // marker after each refresh is what made deletes/tab switches laggy.
    const serialized = JSON.stringify(mapData);
    if (state.mapDataSerialized !== serialized) {
      state.mapDataSerialized = serialized;
      state.mapDataVersion += 1;
    }
    state.mapData = mapData;
    state.mapDataError = null;
  } catch (error) {
    if (state.currentProjectId !== projectId || state.mapDataRequestKey !== requestKey) {
      return;
    }
    state.mapData = null;
    state.mapDataError = error.message || "Map data failed to load.";
  } finally {
    if (state.currentProjectId === projectId && state.mapDataRequestKey === requestKey) {
      state.mapDataLoading = false;
      renderMap();
    }
  }
}

function renderAll() {
  const project = currentProject();
  setStatus(project ? `${project.name}${project.crs ? ` | ${project.crs}` : ""}` : "No template selected");
  const hasTemplate = Boolean(project);
  elements.renameButton.disabled = !hasTemplate;
  elements.deleteProjectButton.disabled = !hasTemplate;
  renderAppInfo();
  renderAreas();
  renderOverlayLibrary();
  renderPhotos();
  renderProcessed();
  renderArchive();
  renderCollections();
  renderViewer();
  renderRuns();
  renderAudit();
  renderMap();
}

function renderAppInfo() {
  const version = state.appInfo?.version || "-";
  elements.appVersionBadge.textContent = `v${version}`;
}

function queueMapRefit() {
  if (state.leaflet) {
    state.leaflet.fitted = false;
  }
}

function renderAreas() {
  if (!state.currentProjectId) {
    elements.areasTable.innerHTML = `<tr><td colspan="6">Create a template first.</td></tr>`;
    return;
  }
  if (!state.areas.length) {
    elements.areasTable.innerHTML = `<tr><td colspan="6">No areas loaded yet.</td></tr>`;
    return;
  }
  elements.areasTable.innerHTML = state.areas.map((area) => `
    <tr>
      <td>${area.name}</td>
      <td>${area.dxf_original_path ? shortPath(area.dxf_original_path) : "Manual only"}</td>
      <td>
        <input
          type="color"
          value="${area.display_color}"
          data-action="color-area"
          data-id="${area.id}"
          title="Area color"
        >
      </td>
      <td>${area.source_crs}</td>
      <td>${area.footprint_bbox.map((value) => Number(value).toFixed(2)).join(", ")}</td>
      <td>
        <div class="inline-actions">
          <button class="secondary" type="button" data-action="rename-area" data-id="${area.id}">Rename</button>
          <button class="secondary" type="button" data-action="replace-area" data-id="${area.id}">Replace File</button>
          <button class="danger" type="button" data-action="delete-area" data-id="${area.id}">Delete</button>
        </div>
      </td>
    </tr>
  `).join("");
}


function overlayStatus() {
  if (!state.currentProjectId) return { label: "No template", kind: "warn" };
  if (!state.overlay) return { label: "Not loaded", kind: "warn" };
  if (state.overlay.error) return { label: "Needs review", kind: "error" };
  if (!state.overlay.bounds) return { label: "Loaded", kind: "warn" };
  return { label: "Map ready", kind: "" };
}

function overlayDisplayName(overlay) {
  if (!overlay) return "";
  const sourcePath = overlay.jpg_original_path || overlay.jpg_managed_path || "";
  return overlay.display_name || stemName(sourcePath) || `Overlay ${overlay.id || ""}`.trim();
}

function overlayRowStatus(overlay) {
  if (!overlay) return { label: "Not loaded", kind: "warn" };
  if (overlay.error) return { label: "Needs review", kind: "error" };
  if (!overlay.bounds) return { label: "Loaded", kind: "warn" };
  return { label: "Map ready", kind: "" };
}

function renderOverlayLibrary() {
  if (!elements.overlayWorkspace) return;
  const hasTemplate = Boolean(state.currentProjectId);
  const overlays = state.overlays?.length ? state.overlays : (state.overlay ? [state.overlay] : []);
  const overlay = state.overlay || overlays[0] || null;
  const hasOverlay = overlays.length > 0;
  const status = overlayStatus();

  elements.overlayImportButton.disabled = !hasTemplate;

  elements.overlayEmptyState.hidden = hasOverlay;
  elements.overlayLibraryCard.hidden = !hasOverlay;

  if (!hasTemplate) {
    elements.overlayEmptyState.innerHTML = `
      <div>
        <p class="eyebrow">Overlay Workspace</p>
        <h3>Create a template first.</h3>
        <p>Select or create a template before importing a site map overlay.</p>
      </div>
    `;
    return;
  }

  if (!hasOverlay) {
    elements.overlayEmptyState.innerHTML = `
      <div>
        <p class="eyebrow">Overlay Workspace</p>
        <h3>No overlay loaded yet.</h3>
        <p>Use Add Overlay to import a PDF or supported overlay file for map context.</p>
      </div>
    `;
    return;
  }

  const sourcePath = overlay?.jpg_original_path || overlay?.jpg_managed_path || "";
  const overlayName = overlayDisplayName(overlay);
  const uploadedDate = overlay.updated_at || overlay.created_at || "";
  elements.overlayCardTitle.textContent = `${overlays.length} Overlay${overlays.length === 1 ? "" : "s"}`;
  elements.overlayCardNote.textContent = overlay.error
    ? "This overlay is loaded, but PanoPro could not read all map registration metadata."
    : `${overlayName} is the newest overlay and is used in the Map workspace for site context.`;
  elements.overlayCardStatus.textContent = status.label;
  elements.overlayCardStatus.className = `overlay-status-pill ${status.kind}`.trim();
  elements.overlayTable.innerHTML = overlays.map((item) => {
    const rowSourcePath = item.jpg_original_path || item.jpg_managed_path || "";
    const rowStatus = overlayRowStatus(item);
    const rowName = overlayDisplayName(item);
    const isMapOverlay = overlay && item.id === overlay.id;
    return `
      <tr>
        <td><strong>${escapeHtml(rowName)}</strong>${isMapOverlay ? `<div class="muted">Map overlay</div>` : ""}</td>
        <td title="${escapeHtml(rowSourcePath)}">${escapeHtml(shortPath(rowSourcePath))}</td>
        <td>${escapeHtml(fileExtension(rowSourcePath))}</td>
        <td>${escapeHtml(fmtDate(item.updated_at || item.created_at || ""))}</td>
        <td>${badge(escapeHtml(rowStatus.label), rowStatus.kind)}${item.error ? `<div class="overlay-warning">${escapeHtml(item.error)}</div>` : ""}</td>
        <td>
          <div class="inline-actions">
            <button class="secondary" type="button" data-overlay-action="rename" data-overlay-id="${item.id}">Rename</button>
            <button class="secondary" type="button" data-overlay-action="open-map" data-overlay-id="${item.id}">Open Map</button>
            <button class="danger" type="button" data-overlay-action="delete" data-overlay-id="${item.id}">Delete</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function filteredPhotos() {
  const filter = elements.photoFilter.value;
  const search = (state.pendingView.search || "").trim().toLowerCase();
  let rows = pendingPhotos();
  if (filter === "ready") rows = rows.filter(photoReadyToRename);
  if (filter === "attention") rows = rows.filter(photoNeedsAttention);
  if (filter === "nearest") rows = rows.filter((photo) => photo.match_mode === "nearest");
  if (filter === "errors") rows = rows.filter((photo) => photo.error || photoHasMetadataIssue(photo));
  if (search) {
    rows = rows.filter((photo) => [
      baseName(photo.original_path),
      photo.area_name,
      photo.proposed_filename,
      photo.error,
    ].some((value) => String(value || "").toLowerCase().includes(search)));
  }
  return rows;
}

function sortedPendingPhotos(rows) {
  const sortBy = state.pendingView.sortBy;
  const sorted = [...rows];
  sorted.sort((left, right) => {
    let comparison = 0;
    if (sortBy === "date_asc" || sortBy === "date_desc") {
      comparison = (Date.parse(left.capture_ts || "") || 0) - (Date.parse(right.capture_ts || "") || 0);
    } else if (sortBy === "original_asc" || sortBy === "original_desc") {
      comparison = compareText(baseName(left.original_path), baseName(right.original_path));
    } else if (sortBy === "proposed_asc" || sortBy === "proposed_desc") {
      comparison = compareText(left.proposed_filename || "", right.proposed_filename || "");
    }
    if (comparison === 0) {
      comparison = compareText(baseName(left.original_path), baseName(right.original_path));
    }
    return sortBy.endsWith("_desc") ? -comparison : comparison;
  });
  return sorted;
}

function pendingColumnCount() {
  return 5
    + (state.pendingView.showOriginal ? 1 : 0)
    + (state.pendingView.showDate ? 1 : 0)
    + (state.pendingView.showProposed ? 1 : 0);
}

function renderPendingHeader() {
  const headers = [`<th>Select</th>`];
  if (state.pendingView.showOriginal) headers.push(`<th>Original File</th>`);
  if (state.pendingView.showDate) headers.push(`<th>Capture Date</th>`);
  headers.push(`<th>Matched Area</th>`);
  headers.push(`<th>Match Status</th>`);
  if (state.pendingView.showProposed) headers.push(`<th>Proposed Filename</th>`);
  headers.push(`<th>Review State</th>`);
  headers.push(`<th>Actions</th>`);
  elements.photosHeaderRow.innerHTML = headers.join("");
}

function pendingSummary() {
  const rows = pendingPhotos();
  return {
    total: rows.length,
    ready: rows.filter(photoReadyToRename).length,
    attention: rows.filter(photoNeedsAttention).length,
    nearest: rows.filter((photo) => photo.match_mode === "nearest").length,
    metadata: rows.filter(photoHasMetadataIssue).length,
  };
}

function pendingGuidance(summary) {
  if (!state.currentProjectId) return "Create or select a template first.";
  if (!state.areas.length) return "Add DXF/KML areas before importing photos so PANO PRO can match locations.";
  if (!summary.total) return "Import DJI pano photos to start a review queue.";
  if (summary.attention) return "Fix photos needing attention before renaming.";
  return "Review matches, then run Rename Eligible Photos.";
}

function renderPendingSummary(rows) {
  const summary = pendingSummary();
  const shownSuffix = rows.length !== summary.total ? ` | ${rows.length} shown` : "";
  elements.pendingCount.textContent = state.currentProjectId
    ? `${summary.total} file${summary.total === 1 ? "" : "s"} pending${shownSuffix}`
    : "Create a template first";
  elements.pendingTotalCount.textContent = summary.total;
  elements.pendingReadyCount.textContent = summary.ready;
  elements.pendingAttentionCount.textContent = summary.attention;
  elements.pendingNearestCount.textContent = summary.nearest;
  elements.pendingMetadataCount.textContent = summary.metadata;
  elements.pendingGuidance.textContent = pendingGuidance(summary);
}

// The queue's area picker deliberately avoids a native <select>: QtWebEngine
// renders native option popups outside the page (OS-styled, and glitchy with
// display scaling), so this reuses the map panel's fully in-page picker.
function pendingAreaPickerHtml(photo, scope) {
  const open =
    state.pendingAreaMenuPhotoId === photo.id && state.pendingAreaMenuScope === scope;
  const options = [
    `<button class="area-option${photo.matched_area_id ? "" : " is-active"}" type="button" data-assign-area-photo-id="${photo.id}" data-assign-area-id="">Unassigned</button>`,
    ...state.areas.map(
      (area) =>
        `<button class="area-option${area.id === photo.matched_area_id ? " is-active" : ""}" type="button" data-assign-area-photo-id="${photo.id}" data-assign-area-id="${area.id}">${area.name}</button>`,
    ),
  ].join("");
  return `
    <div class="area-picker queue-area-picker">
      <button class="area-picker-trigger secondary queue-area-trigger" type="button" data-area-menu-photo-id="${photo.id}" data-area-menu-scope="${scope}" aria-expanded="${open ? "true" : "false"}">
        <span>${photo.area_name || "Unassigned"}</span>
        <span>${open ? "▴" : "▾"}</span>
      </button>
      <div class="area-option-list${open ? " is-open" : ""}">${options}</div>
    </div>
  `;
}

function positionPendingAreaMenu() {
  const openList = document.querySelector(
    ".queue-area-picker .area-option-list.is-open",
  );
  if (!openList) return;
  const trigger = openList.parentElement.querySelector(".area-picker-trigger");
  if (!trigger) return;
  // Fixed positioning escapes the table's overflow clipping; clamp to the
  // viewport so the menu never opens off-screen.
  const rect = trigger.getBoundingClientRect();
  const width = Math.max(rect.width, 200);
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
  openList.style.position = "fixed";
  openList.style.left = `${left}px`;
  openList.style.right = "auto";
  openList.style.width = `${width}px`;
  openList.style.top = `${rect.bottom + 6}px`;
  const height = openList.offsetHeight;
  let top = rect.bottom + 6;
  if (top + height > window.innerHeight - 8) {
    top =
      rect.top - 6 - height >= 8
        ? rect.top - 6 - height
        : Math.max(8, window.innerHeight - height - 8);
  }
  openList.style.top = `${top}px`;
}

function closePendingAreaMenu() {
  if (state.pendingAreaMenuPhotoId == null) return false;
  state.pendingAreaMenuPhotoId = null;
  state.pendingAreaMenuScope = null;
  return true;
}

function renderPhotos() {
  renderPendingHeader();
  const rows = sortedPendingPhotos(filteredPhotos());
  renderPendingSummary(rows);
  if (!state.currentProjectId) {
    elements.photosTable.innerHTML = `<tr><td colspan="${pendingColumnCount()}"><div class="pending-empty-state"><strong>Create or select a template first.</strong><span>Templates hold area definitions, photo batches, rename runs, and review outputs.</span></div></td></tr>`;
    return;
  }
  if (!state.areas.length) {
    elements.photosTable.innerHTML = `<tr><td colspan="${pendingColumnCount()}"><div class="pending-empty-state"><strong>No areas loaded yet.</strong><span>Add DXF/KML areas before importing photos so PANO PRO can match locations.</span></div></td></tr>`;
    return;
  }
  if (!rows.length) {
    const hasPending = pendingPhotos().length > 0;
    elements.photosTable.innerHTML = `<tr><td colspan="${pendingColumnCount()}"><div class="pending-empty-state"><strong>${hasPending ? "No photos match the current filters." : "No pending photos yet."}</strong><span>${hasPending ? "Adjust filters or search terms to review the queue." : "Import DJI pano photos to start a review queue."}</span></div></td></tr>`;
    return;
  }
  elements.photosTable.innerHTML = rows.map((photo) => {
    const selected = photo.id === state.selectedPhotoId ? "is-selected" : "";
    const checked = state.selectedPhotoIds.has(photo.id) ? "checked" : "";
    const status = photoReadyToRename(photo)
      ? badge("Ready")
      : photo.error
        ? badge("Needs Attention", "error")
        : badge("Review", "warn");
    const cells = [`<td class="selection-cell"><input type="checkbox" data-select-photo-id="${photo.id}" ${checked}></td>`];
    if (state.pendingView.showOriginal) {
      cells.push(`<td><strong>${baseName(photo.original_path)}</strong><small class="queue-subtext">${shortPath(photo.original_path)}</small></td>`);
    }
    if (state.pendingView.showDate) {
      cells.push(`<td>${fmtDate(photo.capture_ts)}</td>`);
    }
    cells.push(`<td>${pendingAreaPickerHtml(photo, "queue")}</td>`);
    cells.push(`<td>${matchBadgeForPhoto(photo)}</td>`);
    if (state.pendingView.showProposed) {
      cells.push(`<td><strong>${photo.proposed_filename || "Not ready"}</strong></td>`);
    }
    cells.push(`<td>${photo.error ? `<span class="queue-error">${photo.error}</span>` : status}</td>`);
    cells.push(`
      <td>
        <div class="inline-actions queue-actions">
          <button class="secondary" type="button" data-action="view-map" data-photo-id="${photo.id}">View on Map</button>
          <button class="danger subtle-danger" type="button" data-action="remove-photo" data-photo-id="${photo.id}">Remove</button>
        </div>
      </td>
    `);
    return `
      <tr class="pending-row ${selected}" data-photo-id="${photo.id}">
        ${cells.join("")}
      </tr>
    `;
  }).join("");
  positionPendingAreaMenu();
}

function renderProcessed() {
  const groups = processedPhotoGroups();
  if (!state.currentProjectId) {
    elements.processedTable.innerHTML = `<tr><td colspan="6">Create a template first.</td></tr>`;
    return;
  }
  if (!groups.length) {
    elements.processedTable.innerHTML = `<tr><td colspan="6">No processed photos yet.</td></tr>`;
    return;
  }
  const validKeys = new Set(groups.map((group) => group.key));
  state.collapsedProcessedGroups = new Set(
    [...state.collapsedProcessedGroups].filter((key) => validKeys.has(key)),
  );
  state.seenProcessedGroups = new Set(
    [...state.seenProcessedGroups].filter((key) => validKeys.has(key)),
  );
  for (const group of groups) {
    if (!state.seenProcessedGroups.has(group.key)) {
      state.seenProcessedGroups.add(group.key);
      state.collapsedProcessedGroups.add(group.key);
    }
  }
  elements.processedTable.innerHTML = groups.map((group) => {
    const expanded = !state.collapsedProcessedGroups.has(group.key);
    const header = `
      <tr class="group-row">
        <td colspan="6">
          <button class="group-toggle" type="button" data-group-key="${group.key}">
            <span>${expanded ? "▾" : "▸"}</span>
            <span>${group.label} | ${group.photos.length} photo${group.photos.length === 1 ? "" : "s"}</span>
          </button>
        </td>
      </tr>
    `;
    if (!expanded) {
      return header;
    }
    const rows = group.photos.map((photo) => {
      const selected = photo.id === state.selectedPhotoId ? "is-selected" : "";
      const checked = state.selectedPhotoIds.has(photo.id) ? "checked" : "";
      return `
        <tr class="${selected}" data-photo-id="${photo.id}">
          <td class="selection-cell"><input type="checkbox" data-select-photo-id="${photo.id}" ${checked}></td>
          <td>${shortPath(photo.original_path)}</td>
          <td>${fmtDate(photo.capture_ts)}</td>
          <td>${photo.area_name || "-"}</td>
          <td>${photo.proposed_filename || "-"}</td>
          <td>${badge("Renamed")}</td>
        </tr>
      `;
    }).join("");
    return `${header}${rows}`;
  }).join("");
}

function archiveSelectedPhotos() {
  const targetFolderId = state.currentArchiveFolderId;
  const photoIds = [...state.selectedPhotoIds];
  if (!photoIds.length) {
    throw new Error("Select one or more photos first.");
  }
  return api("/api/archive/assign", {
    method: "POST",
    body: JSON.stringify({ photo_ids: photoIds, folder_id: targetFolderId }),
  });
}

function renderArchive() {
  const folders = [{ id: null, name: "Unfiled" }, ...state.archiveFolders];
  elements.archiveFoldersList.innerHTML = folders.map((folder) => {
    const active = folder.id === state.currentArchiveFolderId || (!folder.id && state.currentArchiveFolderId == null);
    return `<button class="stack-item ${active ? "is-active" : ""}" type="button" data-archive-folder-id="${folder.id ?? ""}">${folder.name}</button>`;
  }).join("");
  const visiblePhotos = state.currentArchiveFolderId == null
    ? state.archivePhotos.filter((photo) => photo.archive_folder_id == null)
    : state.archivePhotos.filter((photo) => photo.archive_folder_id === state.currentArchiveFolderId);
  if (!visiblePhotos.length) {
    elements.archivePhotosTable.innerHTML = `<tr><td colspan="6">No archived panos in this folder.</td></tr>`;
    return;
  }
  elements.archivePhotosTable.innerHTML = visiblePhotos.map((photo) => `
    <tr data-photo-id="${photo.id}">
      <td>${photo.thumbnail_url ? `<img class="thumb" src="${photo.thumbnail_url}" alt="">` : "-"}</td>
      <td>${baseName(photo.original_path)}</td>
      <td>${photo.archive_folder_name || "-"}</td>
      <td>${(photo.tags || []).map((tag) => `<span class="mini-pill">${tag.name}</span>`).join("") || "-"}</td>
      <td>${photo.reviewed ? badge("Reviewed") : badge("Pending", "warn")}</td>
      <td>
        <div class="inline-actions">
          <button class="secondary" type="button" data-view-photo-id="${photo.id}">View</button>
          <button class="secondary" type="button" data-open-file-photo-id="${photo.id}">File</button>
          <button class="secondary" type="button" data-open-folder-photo-id="${photo.id}">Folder</button>
        </div>
      </td>
    </tr>
  `).join("");
}

function viewerSequence() {
  if (state.viewerContext.source === "collection" && state.collectionDetail?.photos?.length) {
    return state.collectionDetail.photos;
  }
  if (state.viewerContext.source === "archive") {
    return state.currentArchiveFolderId == null
      ? state.archivePhotos.filter((photo) => photo.archive_folder_id == null)
      : state.archivePhotos.filter((photo) => photo.archive_folder_id === state.currentArchiveFolderId);
  }
  return state.photos;
}

function currentViewerIndex() {
  const photo = viewerPhoto();
  if (!photo) return -1;
  return viewerSequence().findIndex((item) => item.id === photo.id);
}

function renderCollections() {
  elements.collectionsList.innerHTML = state.collections.map((collection) => `
    <button class="stack-item ${collection.id === state.currentCollectionId ? "is-active" : ""}" type="button" data-collection-id="${collection.id}">
      <strong>${collection.name}</strong><span class="muted">${collection.item_count || 0} panos</span>
    </button>
  `).join("") || `<div class="muted">No collections yet.</div>`;
  const detail = state.collectionDetail;
  if (!detail) {
    elements.collectionPhotosTable.innerHTML = `<tr><td colspan="4">Select or create a collection.</td></tr>`;
    elements.collectionMapSvg.innerHTML = "";
    clearViewerCanvas(elements.collectionViewerCanvas, elements.collectionViewerOverlay, "No collection selected.");
    return;
  }
  elements.collectionPhotosTable.innerHTML = detail.photos.map((photo) => `
    <tr data-photo-id="${photo.id}">
      <td>${photo.thumbnail_url ? `<img class="thumb" src="${photo.thumbnail_url}" alt="">` : "-"}</td>
      <td>${baseName(photo.original_path)}</td>
      <td>${photo.area_name || "-"}</td>
      <td>${(photo.tags || []).map((tag) => `<span class="mini-pill">${tag.name}</span>`).join("") || "-"}</td>
    </tr>
  `).join("") || `<tr><td colspan="4">No panos in this collection.</td></tr>`;
  renderCollectionMap();
  renderCollectionViewer();
}

function renderCollectionMap() {
  const detail = state.collectionDetail;
  if (!detail || !detail.photos.length) {
    elements.collectionMapSvg.innerHTML = "";
    return;
  }
  const points = detail.photos.filter((photo) => photo.projected_x != null && photo.projected_y != null);
  if (!points.length) {
    elements.collectionMapSvg.innerHTML = `<text x="40" y="60" fill="#dfe7eb">No mapped panos.</text>`;
    return;
  }
  const minX = Math.min(...points.map((item) => item.projected_x));
  const maxX = Math.max(...points.map((item) => item.projected_x));
  const minY = Math.min(...points.map((item) => item.projected_y));
  const maxY = Math.max(...points.map((item) => item.projected_y));
  const scaleX = (value) => 80 + (((value - minX) / Math.max(maxX - minX, 1)) * 840);
  const scaleY = (value) => 80 + (((maxY - value) / Math.max(maxY - minY, 1)) * 540);
  elements.collectionMapSvg.innerHTML = detail.photos.map((photo) => {
    if (photo.projected_x == null || photo.projected_y == null) return "";
    return `
      <g data-view-photo-id="${photo.id}" class="collection-point">
        <circle cx="${scaleX(photo.projected_x)}" cy="${scaleY(photo.projected_y)}" r="12" fill="#7a9f84"></circle>
        <text x="${scaleX(photo.projected_x) + 18}" y="${scaleY(photo.projected_y) + 4}" fill="#edf2f4">${baseName(photo.original_path)}</text>
      </g>
    `;
  }).join("");
}

function viewerPhoto() {
  return state.viewerPayload?.photo || null;
}

function currentViewerPose(photo = viewerPhoto()) {
  if (!photo) {
    return { yaw: 0, pitch: 0, fov: 75 };
  }
  if (state.viewerPose && state.viewerPose.photoId === photo.id) {
    return state.viewerPose;
  }
  return {
    photoId: photo.id,
    yaw: Number(photo.viewer_state?.default_yaw || 0),
    pitch: Number(photo.viewer_state?.default_pitch || 0),
    fov: Number(photo.viewer_state?.default_fov || 75),
  };
}

function normalizeYaw(value) {
  let yaw = Number(value || 0);
  while (yaw <= -180) yaw += 360;
  while (yaw > 180) yaw -= 360;
  return yaw;
}

function applyViewerPose(photo, pose) {
  if (!photo) return;
  state.viewerPose = {
    photoId: photo.id,
    yaw: normalizeYaw(pose.yaw ?? 0),
    pitch: clamp(pose.pitch ?? 0, -85, 85),
    fov: clamp(pose.fov ?? 75, 35, 110),
  };
}

function clearViewerCanvas(canvas, overlay, message) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth || 640;
  canvas.height = canvas.clientHeight || 360;
  ctx.fillStyle = "#162025";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#dfe7eb";
  ctx.font = "16px Segoe UI";
  ctx.fillText(message, 24, 32);
  if (overlay) overlay.innerHTML = "";
}

function viewerShell() {
  return elements.viewerCanvas?.closest(".viewer-shell") || null;
}

function archiveRecordForPhoto(photo) {
  if (!photo) return null;
  return state.archivePhotos.find((item) => item.id === photo.id) || null;
}

function gpsTextForPhoto(photo) {
  if (!photo) return "-";
  const gpsLat = photo.gps_lat ?? photo.latitude;
  const gpsLon = photo.gps_lon ?? photo.longitude;
  if (gpsLat != null && gpsLon != null) {
    return `${Number(gpsLat).toFixed(6)}, ${Number(gpsLon).toFixed(6)}`;
  }
  return "GPS unavailable";
}

function projectedTextForPhoto(photo) {
  if (!photo) return "-";
  if (photo.projected_x != null && photo.projected_y != null) {
    return `${Number(photo.projected_x).toFixed(2)}, ${Number(photo.projected_y).toFixed(2)}`;
  }
  return "Projected coordinates unavailable";
}

function viewerStatusLabel(photo) {
  if (!photo) return "No selection";
  if (photo.error) return "Error";
  if (photo.reviewed) return "Reviewed";
  if (photo.applied) return "Processed";
  return "Pending";
}

function setViewerCounts(payload = state.viewerPayload) {
  const photo = payload?.photo || null;
  const tagCount = photo?.tags?.length || 0;
  const issueCount = payload?.issues?.length || 0;
  const noteCount = payload?.notes?.length || 0;
  const annotationCount = payload?.annotations?.length || 0;
  const hotspotCount = payload?.hotspots?.length || 0;
  elements.viewerTagsCount.textContent = String(tagCount);
  elements.viewerIssuesCount.textContent = String(issueCount);
  elements.viewerNotesCount.textContent = String(noteCount);
  elements.viewerTagsBadge.textContent = String(tagCount);
  elements.viewerIssuesBadge.textContent = String(issueCount);
  elements.viewerNotesBadge.textContent = String(noteCount);
  elements.viewerAnnotationsBadge.textContent = String(annotationCount);
  elements.viewerHotspotsBadge.textContent = String(hotspotCount);
}

function renderViewerEmptyState() {
  elements.viewerSelectedName.textContent = "None";
  elements.viewerSelectedState.textContent = "Select a pano to begin";
  elements.viewerAreaName.textContent = "-";
  elements.viewerMatchMode.textContent = "No match loaded";
  elements.viewerCaptureDate.textContent = "-";
  elements.viewerReviewStatus.textContent = "-";
  elements.viewerArchiveStatus.textContent = processedPhotos().length ? "Processed panos available" : "No processed panos available";
  elements.viewerStageTitle.textContent = "No pano selected";
  elements.viewerStageBadge.textContent = "Waiting";
  elements.viewerStageBadge.className = "badge warn";
  elements.viewerDetailStatus.textContent = "No selection";
  elements.viewerDetailStatus.className = "badge warn";
  elements.viewerDetailsBody.innerHTML = `
    <div><span>Next step</span><strong>Select a pano from Processed, Archive, Collections, Review, or Map.</strong></div>
    <div><span>Workspace</span><strong>The viewer keeps orientation, tags, notes, issues, annotations, and hotspots together.</strong></div>
  `;
  elements.viewerEmptyState.hidden = false;
  setViewerCounts(null);
}

function renderViewerDetails(payload) {
  const photo = payload.photo;
  const archiveRecord = archiveRecordForPhoto(photo);
  elements.viewerSelectedName.textContent = baseName(photo.final_filename || photo.proposed_filename || photo.original_path);
  elements.viewerSelectedState.textContent = viewerStatusLabel(photo);
  elements.viewerAreaName.textContent = photo.area_name || "Unassigned";
  elements.viewerMatchMode.textContent = photo.match_mode || "No match mode";
  elements.viewerCaptureDate.textContent = fmtDate(photo.capture_ts);
  elements.viewerReviewStatus.textContent = photo.reviewed ? "Reviewed" : photo.error ? "Error" : "Open";
  elements.viewerArchiveStatus.textContent = archiveRecord?.archive_folder_name || (photo.applied ? "Processed output" : "Pending input");
  elements.viewerStageTitle.textContent = baseName(photo.final_filename || photo.proposed_filename || photo.original_path);
  elements.viewerStageBadge.textContent = viewerStatusLabel(photo);
  elements.viewerStageBadge.className = photo.error ? "badge error" : photo.reviewed ? "badge" : "badge warn";
  elements.viewerDetailStatus.textContent = viewerStatusLabel(photo);
  elements.viewerDetailStatus.className = photo.error ? "badge error" : photo.reviewed ? "badge" : "badge warn";
  elements.viewerDetailsBody.innerHTML = `
    <div><span>Original</span><strong>${shortPath(photo.original_path)}</strong></div>
    <div><span>Proposed / Final</span><strong>${photo.final_filename || photo.proposed_filename || "-"}</strong></div>
    <div><span>Capture Date</span><strong>${fmtDate(photo.capture_ts)}</strong></div>
    <div><span>Matched Area</span><strong>${photo.area_name || "Unassigned"}</strong><small>${photo.match_mode || "No match mode"}</small></div>
    <div><span>Status</span><strong>${photo.error || viewerStatusLabel(photo)}</strong></div>
    <div><span>GPS</span><strong>${gpsTextForPhoto(photo)}</strong><small>${projectedTextForPhoto(photo)}</small></div>
    <div><span>Archive / Review</span><strong>${archiveRecord?.archive_folder_name || "Not archived"}</strong><small>${photo.reviewed ? "Reviewed" : "Not reviewed"}</small></div>
  `;
  elements.viewerEmptyState.hidden = true;
  setViewerCounts(payload);
}

function renderViewerLists(payload) {
  const photo = payload.photo;
  elements.viewerTagsList.innerHTML = (photo.tags || []).map((tag) => `<span class="mini-pill">${tag.name}</span>`).join("") || `<div class="muted">No tags yet.</div>`;
  elements.viewerAnnotationsList.innerHTML = payload.annotations.map((item) => `
    <div class="stack-item compact review-item"><strong>${item.label || "Annotation"}</strong><span>${item.annotation_type || "marker"}</span></div>
  `).join("") || `<div class="muted">No annotations yet. Add a marker to call out a feature.</div>`;
  elements.viewerIssuesList.innerHTML = payload.issues.map((item) => `
    <div class="stack-item compact review-item"><strong>${item.title}</strong><span>${item.status || "open"} · ${item.severity || "medium"}</span></div>
  `).join("") || `<div class="muted">No issues logged for this pano.</div>`;
  elements.viewerNotesList.innerHTML = payload.notes.map((item) => `
    <div class="stack-item compact review-item"><strong>${item.note_text}</strong><span>${fmtDate(item.created_at)}</span></div>
  `).join("") || `<div class="muted">No notes yet. Add observations from the review.</div>`;
  elements.viewerHotspotsList.innerHTML = payload.hotspots.map((item) => `
    <div class="stack-item compact review-item"><strong>${item.label || `Pano ${item.target_photo_id}`}</strong><span>Target pano #${item.target_photo_id}${item.disabled ? " · disabled" : ""}</span></div>
  `).join("") || `<div class="muted">No hotspots yet. Add pano-to-pano navigation links.</div>`;
}

function renderViewer() {
  const payload = state.viewerPayload;
  if (!payload) {
    clearViewerCanvas(elements.viewerCanvas, elements.viewerOverlay, "Select a pano to open the viewer.");
    renderViewerEmptyState();
    elements.viewerTagsList.innerHTML = `<div class="muted">No pano selected.</div>`;
    elements.viewerAnnotationsList.innerHTML = `<div class="muted">No pano selected.</div>`;
    elements.viewerIssuesList.innerHTML = `<div class="muted">No pano selected.</div>`;
    elements.viewerNotesList.innerHTML = `<div class="muted">No pano selected.</div>`;
    elements.viewerHotspotsList.innerHTML = `<div class="muted">No pano selected.</div>`;
    elements.viewerPrevButton.disabled = true;
    elements.viewerNextButton.disabled = true;
    elements.viewerOpenFileButton.disabled = true;
    elements.viewerOpenFolderButton.disabled = true;
    elements.viewerRevealButton.disabled = true;
    elements.viewerOpenMapButton.disabled = true;
    elements.saveViewerStateButton.disabled = true;
    if (elements.viewerFullscreenButton) {
      elements.viewerFullscreenButton.disabled = true;
    }
    return;
  }
  renderPanoCanvas(elements.viewerCanvas, elements.viewerOverlay, payload);
  renderViewerDetails(payload);
  renderViewerLists(payload);
  const pose = currentViewerPose(payload.photo);
  elements.viewerNorthOffset.value = payload.photo.viewer_state?.north_offset ?? 0;
  elements.viewerDefaultYaw.value = Number(pose.yaw).toFixed(1);
  const index = currentViewerIndex();
  const sequence = viewerSequence();
  elements.viewerPrevButton.disabled = index <= 0;
  elements.viewerNextButton.disabled = index < 0 || index >= sequence.length - 1;
  elements.viewerOpenFileButton.disabled = false;
  elements.viewerOpenFolderButton.disabled = false;
  elements.viewerRevealButton.disabled = false;
  elements.viewerOpenMapButton.disabled = false;
  elements.saveViewerStateButton.disabled = false;
  if (elements.viewerFullscreenButton) {
    elements.viewerFullscreenButton.disabled = false;
    elements.viewerFullscreenButton.textContent = document.fullscreenElement === viewerShell() ? "Exit Full Screen" : "Full Screen";
  }
}

function renderCollectionViewer() {
  if (!state.viewerPayload || state.viewerContext.source !== "collection") {
    clearViewerCanvas(elements.collectionViewerCanvas, elements.collectionViewerOverlay, "Open a pano from this collection.");
    return;
  }
  renderPanoCanvas(elements.collectionViewerCanvas, elements.collectionViewerOverlay, state.viewerPayload);
}

function renderAudit() {
  elements.auditTable.innerHTML = state.auditEvents.map((event) => `
    <tr>
      <td>${fmtDate(event.created_at)}</td>
      <td>${event.action_type}</td>
      <td>${event.entity_type}${event.entity_id ? ` #${event.entity_id}` : ""}</td>
      <td>${JSON.stringify(event.payload || {})}</td>
    </tr>
  `).join("") || `<tr><td colspan="4">No audit events yet.</td></tr>`;
}

function renderPanoCanvas(canvas, overlay, payload) {
  if (!canvas) return;
  const photo = payload.photo;
  const cacheKey = photo.image_url;
  if (!state.viewerImageCache[cacheKey]) {
    const image = new Image();
    image.src = cacheKey;
    image.onload = () => {
      const rasterCanvas = document.createElement("canvas");
      rasterCanvas.width = image.naturalWidth;
      rasterCanvas.height = image.naturalHeight;
      const rasterCtx = rasterCanvas.getContext("2d", { willReadFrequently: true });
      rasterCtx.drawImage(image, 0, 0);
      const raster = rasterCtx.getImageData(0, 0, image.naturalWidth, image.naturalHeight);
      state.viewerImageCache[cacheKey] = {
        status: "ready",
        image,
        width: image.naturalWidth,
        height: image.naturalHeight,
        data: raster.data,
      };
      renderAll();
    };
    image.onerror = () => clearViewerCanvas(canvas, overlay, "Unable to load pano image.");
    state.viewerImageCache[cacheKey] = { status: "loading", image };
    clearViewerCanvas(canvas, overlay, "Loading pano...");
    return;
  }
  const resource = state.viewerImageCache[cacheKey];
  if (resource.status !== "ready") {
    clearViewerCanvas(canvas, overlay, "Loading pano...");
    return;
  }
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth || 900;
  const height = canvas.clientHeight || 480;
  canvas.width = width;
  canvas.height = height;
  const pose = currentViewerPose(photo);
  const yaw = Number(pose.yaw || 0);
  const pitch = Number(pose.pitch || 0);
  const fov = Number(pose.fov || 75);
  drawProjectedPanorama(ctx, resource, width, height, yaw, pitch, fov);
  renderViewerOverlay(overlay, payload, width, height, yaw, pitch);
}

function viewFovRadians(width, height, horizontalFovDegrees) {
  const hfov = clamp(horizontalFovDegrees, 35, 110) * DEG2RAD;
  const vfov = 2 * Math.atan(Math.tan(hfov / 2) * (height / width));
  return { hfov, vfov };
}

function projectAngularPoint(itemYaw, itemPitch, cameraYaw, cameraPitch, width, height, fovDegrees) {
  const { hfov, vfov } = viewFovRadians(width, height, fovDegrees);
  const yaw = cameraYaw * DEG2RAD;
  const pitch = cameraPitch * DEG2RAD;
  const lon = itemYaw * DEG2RAD;
  const lat = itemPitch * DEG2RAD;

  const worldX = Math.sin(lon) * Math.cos(lat);
  const worldY = Math.sin(lat);
  const worldZ = Math.cos(lon) * Math.cos(lat);

  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);
  const yawX = worldX * cosYaw - worldZ * sinYaw;
  const yawZ = worldX * sinYaw + worldZ * cosYaw;

  const cosPitch = Math.cos(pitch);
  const sinPitch = Math.sin(pitch);
  const cameraX = yawX;
  const cameraY = worldY * cosPitch - yawZ * sinPitch;
  const cameraZ = worldY * sinPitch + yawZ * cosPitch;

  if (cameraZ <= 0) {
    return null;
  }

  const projectedX = (cameraX / cameraZ) / Math.tan(hfov / 2);
  const projectedY = (cameraY / cameraZ) / Math.tan(vfov / 2);
  const x = ((projectedX + 1) * 0.5) * width;
  const y = ((1 - projectedY) * 0.5) * height;

  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null;
  }
  return { x, y };
}

function drawProjectedPanorama(ctx, resource, width, height, yawDegrees, pitchDegrees, fovDegrees) {
  const qualityScale = clamp(window.devicePixelRatio || 1, 1, 2);
  const renderWidth = clamp(Math.round(width * qualityScale), 960, 2400);
  const renderHeight = Math.max(320, Math.round(renderWidth * (height / width)));
  const scratch = document.createElement("canvas");
  scratch.width = renderWidth;
  scratch.height = renderHeight;
  const scratchCtx = scratch.getContext("2d");
  const imageData = scratchCtx.createImageData(renderWidth, renderHeight);
  const output = imageData.data;

  const { hfov, vfov } = viewFovRadians(renderWidth, renderHeight, fovDegrees);
  const halfTanX = Math.tan(hfov / 2);
  const halfTanY = Math.tan(vfov / 2);

  const yaw = yawDegrees * DEG2RAD;
  const pitch = pitchDegrees * DEG2RAD;
  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);
  const cosPitch = Math.cos(pitch);
  const sinPitch = Math.sin(pitch);

  const sourceWidth = resource.width;
  const sourceHeight = resource.height;
  const source = resource.data;

  let offset = 0;
  for (let py = 0; py < renderHeight; py += 1) {
    const screenY = (1 - (2 * ((py + 0.5) / renderHeight))) * halfTanY;
    for (let px = 0; px < renderWidth; px += 1) {
      const screenX = ((2 * ((px + 0.5) / renderWidth)) - 1) * halfTanX;

      const invLength = 1 / Math.hypot(screenX, screenY, 1);
      const cameraX = screenX * invLength;
      const cameraY = screenY * invLength;
      const cameraZ = invLength;

      const pitchY = cameraY * cosPitch + cameraZ * sinPitch;
      const pitchZ = -cameraY * sinPitch + cameraZ * cosPitch;
      const worldX = cameraX * cosYaw + pitchZ * sinYaw;
      const worldY = pitchY;
      const worldZ = -cameraX * sinYaw + pitchZ * cosYaw;

      const lon = Math.atan2(worldX, worldZ);
      const lat = Math.asin(clamp(worldY, -1, 1));
      let u = Math.floor(((lon / TWO_PI) + 0.5) * sourceWidth);
      let v = Math.floor((0.5 - (lat / Math.PI)) * sourceHeight);

      u %= sourceWidth;
      if (u < 0) u += sourceWidth;
      v = clamp(v, 0, sourceHeight - 1);

      const sourceOffset = ((v * sourceWidth) + u) * 4;
      output[offset] = source[sourceOffset];
      output[offset + 1] = source[sourceOffset + 1];
      output[offset + 2] = source[sourceOffset + 2];
      output[offset + 3] = 255;
      offset += 4;
    }
  }

  scratchCtx.putImageData(imageData, 0, 0);
  ctx.imageSmoothingEnabled = true;
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(scratch, 0, 0, width, height);
  ctx.fillStyle = "rgba(10,14,18,0.15)";
  ctx.fillRect(0, 0, width, height);
}

function renderViewerOverlay(overlay, payload, width, height, yaw, pitch) {
  if (!overlay) return;
  const northOffset = Number(payload.photo.viewer_state?.north_offset || 0);
  const pose = currentViewerPose(payload.photo);
  const items = [];
  const place = (item, className, label, options = {}) => {
    const projected = projectAngularPoint(
      Number(item.yaw || 0),
      Number(item.pitch || 0),
      yaw,
      pitch,
      width,
      height,
      pose.fov,
    );
    if (!projected) return;
    const y = projected.y + Number(options.offsetY || 0);
    if (projected.x < -80 || projected.x > width + 80 || y < -80 || y > height + 80) return;
    const tooltip = String(options.tooltip || label || "").replace(/"/g, "&quot;");
    const content = options.compact ? `<span class="viewer-marker-dot"></span>` : label;
    items.push(`<button class="${className}" type="button" data-view-photo-id="${item.target_photo_id || payload.photo.id}" data-tooltip="${tooltip}" aria-label="${tooltip}" style="left:${projected.x}px; top:${y}px;">${content}</button>`);
  };
  for (const hotspot of payload.hotspots || []) {
    if (hotspot.disabled) continue;
    place(
      hotspot,
      "viewer-marker hotspot is-compact",
      hotspot.label || `Pano ${hotspot.target_photo_id}`,
      {
        compact: true,
        offsetY: -18,
        tooltip: hotspot.label || `Pano ${hotspot.target_photo_id}`,
      },
    );
  }
  for (const annotation of payload.annotations || []) {
    place(annotation, "viewer-marker annotation", annotation.label || "Annotation");
  }
  for (const issue of payload.issues || []) {
    if (issue.yaw == null || issue.pitch == null) continue;
    place(issue, "viewer-marker issue", issue.title);
  }
  const northRotation = ((northOffset - yaw) % 360);
  items.push(`
    <div class="north-arrow" style="transform: rotate(${northRotation}deg);">
      <div class="north-arrow-ring"></div>
      <div class="north-arrow-needle"></div>
      <span>N</span>
    </div>
  `);
  overlay.innerHTML = items.join("");
}

function renderRuns() {
  const latestRun = state.runs[0] || null;
  elements.rollbackButton.disabled =
    !state.currentProjectId || !latestRun || Boolean(latestRun.rollback_completed_at);
  if (!state.runs.length) {
    elements.runsTable.innerHTML = `<tr><td colspan="5">No rename runs yet.</td></tr>`;
    return;
  }
  elements.runsTable.innerHTML = state.runs.map((run, index) => {
    const canRollback = index === 0 && !run.rollback_completed_at;
    const summary = run.summary || {};
    return `
      <tr>
        <td>${fmtDate(run.started_at)}</td>
        <td>${fmtDate(run.completed_at)}</td>
        <td>${run.batch_id}</td>
        <td>${summary.renamed || 0} renamed, ${summary.unchanged || 0} unchanged, ${summary.errors || 0} errors</td>
        <td>${run.rollback_completed_at
          ? badge("Rolled Back", "warn")
          : canRollback
            ? badge("Rollback Ready")
            : badge("Locked")}</td>
      </tr>
    `;
  }).join("");
}

function labelLinesForPhoto(photo) {
  if (!state.mapLabels.enabled) return [];
  const lines = [];
  if (state.mapLabels.showOriginal) {
    lines.push(baseName(photo.original_path));
  }
  if (state.mapLabels.showProposed && photo.proposed_filename) {
    lines.push(photo.proposed_filename);
  }
  return lines.filter(Boolean);
}

function syncMapAreaDraft(selectedPhoto) {
  if (!selectedPhoto) {
    state.mapAreaDraftPhotoId = null;
    state.mapAreaDraftId = null;
    state.mapAreaMenuOpen = false;
    return;
  }
  if (state.mapAreaDraftPhotoId !== selectedPhoto.id) {
    state.mapAreaDraftPhotoId = selectedPhoto.id;
    state.mapAreaDraftId = selectedPhoto.matched_area_id ?? null;
    state.mapAreaMenuOpen = false;
  }
}

function visibleMapPhotos() {
  return (state.mapData?.photos || []).filter((photo) => state.mapVisibility.showProcessed || !photo.applied);
}

function boundsFromMapData() {
  const candidates = [];
  if (state.mapData?.overlay?.bounds) {
    candidates.push(state.mapData.overlay.bounds);
  }
  for (const area of state.mapData?.areas || []) {
    candidates.push(area.bbox);
  }
  for (const photo of visibleMapPhotos()) {
    if (photo.projected_x != null && photo.projected_y != null) {
      candidates.push([photo.projected_x, photo.projected_y, photo.projected_x, photo.projected_y]);
    }
  }
  if (!candidates.length) return null;
  return [
    Math.min(...candidates.map((item) => item[0])),
    Math.min(...candidates.map((item) => item[1])),
    Math.max(...candidates.map((item) => item[2])),
    Math.max(...candidates.map((item) => item[3])),
  ];
}

function selectedMapPhoto() {
  return state.photos.find((photo) => photo.id === state.selectedPhotoId) || null;
}

function mapDataStatusText() {
  if (!state.currentProjectId) return { label: "No Template", detail: "Select or create a template" };
  if (state.mapDataLoading) return { label: "Loading", detail: "Fetching map layers" };
  if (state.mapDataError) return { label: "Error", detail: state.mapDataError };
  if (!state.mapData) return { label: "Waiting", detail: "Map data not loaded" };
  return { label: "Ready", detail: `${visibleMapPhotos().length} visible point${visibleMapPhotos().length === 1 ? "" : "s"}` };
}

function mapOverlayStatusText() {
  if (state.overlay?.error) return "Warning";
  if (state.mapData?.overlay?.image_url || state.overlay?.image_url || state.overlay?.preview_url) return "Loaded";
  return "None";
}

function photoMapStatus(photo) {
  if (!photo) return "No selection";
  if (photo.error) return "Error";
  if (photo.applied) return "Processed";
  if (photo.match_mode === "nearest") return "Nearest match";
  if (photo.match_mode === "manual") return "Manual match";
  if (!photo.matched_area_id) return "Unmatched";
  return "Pending review";
}

function renderMapSummary() {
  const selected = selectedMapPhoto();
  const dataStatus = mapDataStatusText();
  elements.mapAreaCount.textContent = String(state.areas.length);
  elements.mapPendingCount.textContent = String(pendingPhotos().filter((photo) => photo.projected_x != null && photo.projected_y != null).length);
  elements.mapProcessedCount.textContent = String(processedPhotos().filter((photo) => photo.projected_x != null && photo.projected_y != null).length);
  elements.mapSelectedLabel.textContent = selected ? baseName(selected.proposed_filename || selected.final_filename || selected.original_path) : "None";
  elements.mapSelectedStatus.textContent = selected ? photoMapStatus(selected) : "Select a pano point";
  elements.mapOverlayStatus.textContent = mapOverlayStatusText();
  elements.mapDataStatus.textContent = dataStatus.label;
  elements.mapDataDetail.textContent = dataStatus.detail;
}

function setMapStateOverlay(title, detail = "", kind = "") {
  if (!elements.mapStateOverlay) return;
  if (!title) {
    elements.mapStateOverlay.hidden = true;
    elements.mapCanvas.classList.remove("has-map-state", "has-map-error");
    elements.mapStateOverlay.innerHTML = "";
    return;
  }
  elements.mapStateOverlay.hidden = false;
  elements.mapCanvas.classList.add("has-map-state");
  elements.mapCanvas.classList.toggle("has-map-error", kind === "error");
  elements.mapStateOverlay.innerHTML = `
    <div class="map-state-card ${kind === "error" ? "error" : ""}">
      <strong>${title}</strong>
      ${detail ? `<span>${detail}</span>` : ""}
    </div>
  `;
}

function coordinatesForPhoto(photo) {
  const gpsLat = photo.gps_lat ?? photo.latitude;
  const gpsLon = photo.gps_lon ?? photo.longitude;
  const gps = gpsLat != null && gpsLon != null
    ? `${Number(gpsLat).toFixed(6)}, ${Number(gpsLon).toFixed(6)}`
    : "GPS unavailable";
  const projected = photo.projected_x != null && photo.projected_y != null
    ? `${Number(photo.projected_x).toFixed(2)}, ${Number(photo.projected_y).toFixed(2)}`
    : "Projected coordinates unavailable";
  return { gps, projected };
}

function renderMapDrawDetail() {
  const canSave = state.drawArea.points.length >= 3 && state.drawArea.name.trim();
  elements.mapDetail.innerHTML = `
    <div class="map-guidance-card draw-active">
      <strong>Draw Area Mode Active</strong>
      <span>Click the map to place vertices. Drag to pan and use the wheel to zoom while tracing the footprint.</span>
    </div>
    <div class="detail-form map-draw-form">
      <label>
        <span>Area name</span>
        <input id="draw-area-name" type="text" value="${state.drawArea.name.replace(/"/g, "&quot;")}" placeholder="Custom area name">
      </label>
      <label>
        <span>Color</span>
        <input id="draw-area-color" type="color" value="${state.drawArea.color}">
      </label>
      <div class="muted">${state.drawArea.points.length} point${state.drawArea.points.length === 1 ? "" : "s"} placed</div>
      <div class="detail-actions">
        <button id="draw-area-save-button" type="button" ${canSave ? "" : "disabled"}>Save Area</button>
        <button id="draw-area-undo-button" class="secondary" type="button" ${state.drawArea.points.length ? "" : "disabled"}>Undo</button>
        <button id="draw-area-cancel-button" class="secondary" type="button">Cancel</button>
      </div>
    </div>
    ${state.overlay?.error ? `<div class="map-warning">Overlay: ${state.overlay.error}</div>` : ""}
  `;
}

function renderMapSelectedDetail(selectedPhoto) {
  syncMapAreaDraft(selectedPhoto);
  const draftAreaId = state.mapAreaDraftId;
  const draftArea = state.areas.find((area) => area.id === draftAreaId) || null;
  const draftAreaLabel = draftArea ? draftArea.name : "Unassigned";
  const coordinates = coordinatesForPhoto(selectedPhoto);
  const isArchived = state.archivePhotos.some((photo) => photo.id === selectedPhoto.id);
  const areaOptions = [
    `
      <button class="area-option ${draftAreaId == null ? "is-active" : ""}" type="button" data-area-option-id="">
        Unassigned
      </button>
    `,
    ...state.areas.map((area) => `
      <button
        class="area-option ${draftAreaId === area.id ? "is-active" : ""}"
        type="button"
        data-area-option-id="${area.id}"
      >
        ${area.name}
      </button>
    `),
  ].join("");
  const areaEditor = selectedPhoto.applied
    ? `<div class="map-guidance-card"><strong>Area locked</strong><span>Processed photos cannot be reassigned. Remove and re-import if the name needs to change.</span></div>`
    : `
      <div class="detail-form map-area-editor">
        <div>
          <span>Change Area</span>
          <div class="area-picker">
            <button id="map-area-trigger" class="area-picker-trigger secondary" type="button" aria-expanded="${state.mapAreaMenuOpen ? "true" : "false"}">
              <span>${draftAreaLabel}</span>
              <span>${state.mapAreaMenuOpen ? "▴" : "▾"}</span>
            </button>
            <div class="area-option-list ${state.mapAreaMenuOpen ? "is-open" : ""}">
              ${areaOptions}
            </div>
          </div>
        </div>
        <button id="map-save-area-button" type="button">Save Area</button>
      </div>
    `;
  elements.mapDetail.innerHTML = `
    <div class="map-selected-summary">
      <strong>${baseName(selectedPhoto.proposed_filename || selectedPhoto.final_filename || selectedPhoto.original_path)}</strong>
      <span>${photoMapStatus(selectedPhoto)}</span>
    </div>
    <div class="map-detail-stack">
      <div><span>Original</span><strong>${shortPath(selectedPhoto.original_path)}</strong></div>
      <div><span>Proposed / Final</span><strong>${selectedPhoto.proposed_filename || selectedPhoto.final_filename || "-"}</strong></div>
      <div><span>Capture Date</span><strong>${fmtDate(selectedPhoto.capture_ts)}</strong></div>
      <div><span>Matched Area</span><strong>${selectedPhoto.area_name || "Unassigned"}</strong><small>${selectedPhoto.match_mode || "No match mode"}</small></div>
      <div><span>Coordinates</span><strong>${coordinates.gps}</strong><small>${coordinates.projected}</small></div>
      ${selectedPhoto.error ? `<div class="map-detail-error"><span>Error</span><strong>${selectedPhoto.error}</strong></div>` : ""}
    </div>
    <div class="detail-actions map-detail-actions">
      ${selectedPhoto.applied ? `<button data-map-action="open-viewer" type="button">Open Viewer</button>` : ""}
      <button data-map-action="open-source" class="secondary" type="button">Open ${selectedPhoto.applied ? "Processed" : "Pending"}</button>
      ${selectedPhoto.applied ? "" : `<button data-map-action="remove-photo" class="secondary danger" type="button">Remove Photo</button>`}
    </div>
    ${areaEditor}
    ${state.overlay?.error ? `<div class="map-warning">Overlay: ${state.overlay.error}</div>` : ""}
  `;
}

function renderMapEmptyDetail(message = "Select a pano point on the map or a photo row to inspect details.") {
  elements.mapDetail.innerHTML = `
    <div class="map-guidance-card">
      <strong>No pano selected</strong>
      <span>${message}</span>
    </div>
    <div class="map-detail-stack">
      <div><span>Tip</span><strong>Use the Pending queue or Processed list to focus a photo on this map.</strong></div>
      <div><span>Layers</span><strong>Enable processed panos and labels from the command bar when validating renamed outputs.</strong></div>
    </div>
    ${state.overlay?.error ? `<div class="map-warning">Overlay warning: ${state.overlay.error}</div>` : ""}
  `;
}

// ---- Leaflet map engine ----
// The map runs on Leaflet with L.CRS.Simple: latLng pairs are
// [northing, easting] in the project's EPSG:26912 meters, so geometry from
// the backend is used as-is. Layers rebuild only when map data or display
// options change; hover and selection restyle individual markers, which is
// what makes pan/zoom/hover smooth compared to the old full-SVG rebuilds.

function leafletBoundsFrom(bounds) {
  const [minx, miny, maxx, maxy] = bounds;
  return L.latLngBounds([miny, minx], [maxy, maxx]);
}

function photoMarkerStyle(photo) {
  const isSelected = photo.id === state.selectedPhotoId;
  const isHovered = photo.id === state.hoveredPhotoId;
  const fill = photo.error
    ? "#d06a6a"
    : photo.applied
      ? "#4da1dc"
      : photo.match_mode === "nearest" || photo.match_mode === "manual"
        ? "#d88d51"
        : "#7a9f84";
  return {
    radius: isSelected ? 9 : isHovered ? 7.5 : 5.5,
    fillColor: fill,
    fillOpacity: 0.95,
    color: isSelected || isHovered ? "#b8db66" : "rgba(255, 255, 255, 0.86)",
    weight: isSelected || isHovered ? 3 : 1.5,
  };
}

function applyMarkerStyle(entry) {
  const style = photoMarkerStyle(entry.photo);
  entry.marker.setStyle(style);
  entry.marker.setRadius(style.radius);
}

function setMapHover(photoId) {
  const nextHovered = state.suppressHover ? null : photoId;
  if (state.hoveredPhotoId === nextHovered) return;
  const previous = state.hoveredPhotoId;
  state.hoveredPhotoId = nextHovered;
  const leaf = state.leaflet;
  if (!leaf) return;
  for (const id of [previous, nextHovered]) {
    const entry = id != null ? leaf.markers[id] : null;
    if (entry) applyMarkerStyle(entry);
  }
}

function selectMapPhoto(photoId) {
  state.selectedPhotoId = photoId;
  renderPhotos();
  renderProcessed();
  renderMap();
}

function ensureLeafletMap() {
  if (state.leaflet) return state.leaflet;
  const map = L.map(elements.leafletMap, {
    crs: L.CRS.Simple,
    minZoom: -12,
    maxZoom: 12,
    zoomSnap: 0.25,
    zoomDelta: 0.5,
    wheelPxPerZoomLevel: 90,
    attributionControl: false,
    zoomControl: false,
  });
  // Leaflet's invalidateSize/fitBounds are inert until the map has a view,
  // so load it immediately; the real fit happens once data and layout exist.
  map.setView([0, 0], 0);
  map.on("click", (event) => {
    if (!state.drawArea.active) return;
    state.drawArea.points.push({ x: event.latlng.lng, y: event.latlng.lat });
    renderMap();
  });
  state.leaflet = {
    map,
    overlayLayer: null,
    overlayKey: null,
    areaLayer: L.layerGroup().addTo(map),
    photoLayer: L.layerGroup().addTo(map),
    drawLayer: L.layerGroup().addTo(map),
    markers: {},
    dataKey: null,
    fitted: false,
    fitZoom: 0,
  };
  return state.leaflet;
}

function leafletDataKey() {
  return [
    state.mapDataVersion,
    state.mapVisibility.showProcessed,
    state.mapLabels.enabled,
    state.mapLabels.showOriginal,
    state.mapLabels.showProposed,
  ].join("|");
}

function activeMapOverlay() {
  if (state.selectedOverlayId) {
    const chosen = (state.overlays || []).find((item) => item.id === state.selectedOverlayId);
    if (chosen) return chosen;
  }
  return state.mapData?.overlay || null;
}

function renderMapOverlayPicker() {
  const picker = document.getElementById("map-overlay-picker");
  const select = document.getElementById("map-overlay-select");
  if (!picker || !select) return;
  const overlays = state.overlays || [];
  picker.hidden = overlays.length < 2;
  if (overlays.length < 2) return;
  const active = activeMapOverlay();
  select.innerHTML = overlays
    .map((item) => `<option value="${item.id}">${overlayDisplayName(item)}</option>`)
    .join("");
  if (active) {
    select.value = String(active.id);
  }
}

function syncOverlayLayer(leaf) {
  // The overlay layer has its own identity key: rebuilding it is expensive
  // (tile refetches, or a giant PNG re-decode on the imageOverlay fallback)
  // and only necessary when a different overlay/source is shown.
  const overlay = activeMapOverlay();
  const usable = overlay?.bounds && (overlay.tile_url || overlay.image_url);
  const key = usable
    ? `${overlay.id}|${overlay.tile_url || overlay.image_url}|${JSON.stringify(overlay.bounds)}`
    : null;
  if (leaf.overlayKey === key) return;
  leaf.overlayKey = key;

  if (leaf.overlayLayer) {
    leaf.map.removeLayer(leaf.overlayLayer);
    leaf.overlayLayer = null;
  }
  if (!usable) return;
  const [ox1, oy1, ox2, oy2] = overlay.bounds;
  const overlayBounds = L.latLngBounds([oy1, ox1], [oy2, ox2]);
  if (overlay.tile_url) {
    // Tile pyramid (PMTiles-backed): the GPU only holds visible tiles,
    // which avoids the oversized-texture compositor corruption that a
    // single full-resolution imageOverlay causes in the desktop shell.
    leaf.overlayLayer = L.tileLayer(overlay.tile_url, {
      bounds: overlayBounds,
      minNativeZoom: overlay.tile_min_zoom,
      maxNativeZoom: overlay.tile_max_zoom,
      minZoom: -12,
      maxZoom: 12,
      tileSize: 256,
      opacity: 0.72,
      updateWhenZooming: false,
    }).addTo(leaf.map);
  } else {
    leaf.overlayLayer = L.imageOverlay(overlay.image_url, overlayBounds, {
      opacity: 0.72,
    }).addTo(leaf.map);
  }
  leaf.overlayLayer.bringToBack();
}

function syncLeafletLayers(leaf) {
  syncOverlayLayer(leaf);
  const key = leafletDataKey();
  if (leaf.dataKey === key) return;
  leaf.dataKey = key;

  leaf.areaLayer.clearLayers();
  for (const area of state.mapData?.areas || []) {
    const color = area.display_color || "#175c4c";
    for (const part of area.parts || []) {
      L.polygon(part.map(([x, y]) => [y, x]), {
        color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.18,
      }).addTo(leaf.areaLayer);
    }
    if (area.label_anchor?.length === 2) {
      L.tooltip({
        permanent: true,
        direction: "right",
        offset: [8, 0],
        className: "map-area-tooltip",
      })
        .setLatLng([area.label_anchor[1], area.label_anchor[0]])
        .setContent(area.name)
        .addTo(leaf.areaLayer);
    }
  }

  leaf.photoLayer.clearLayers();
  leaf.markers = {};
  for (const photo of visibleMapPhotos()) {
    if (photo.projected_x == null || photo.projected_y == null) continue;
    const marker = L.circleMarker([photo.projected_y, photo.projected_x], photoMarkerStyle(photo));
    const labelLines = labelLinesForPhoto(photo);
    if (labelLines.length) {
      marker.bindTooltip(labelLines.map(escapeHtml).join("<br>"), {
        permanent: true,
        direction: "right",
        offset: [9, 0],
        className: "map-photo-tooltip",
      });
    }
    marker.on("click", (event) => {
      if (state.drawArea.active) {
        state.drawArea.points.push({ x: event.latlng.lng, y: event.latlng.lat });
        renderMap();
        return;
      }
      selectMapPhoto(photo.id);
    });
    marker.on("mouseover", () => setMapHover(photo.id));
    marker.on("mouseout", () => setMapHover(null));
    marker.addTo(leaf.photoLayer);
    leaf.markers[photo.id] = { marker, photo };
  }
}

function syncDrawLayer(leaf) {
  leaf.drawLayer.clearLayers();
  if (!state.drawArea.points.length) return;
  const latlngs = state.drawArea.points.map((point) => [point.y, point.x]);
  const shapeOptions = {
    color: state.drawArea.color,
    weight: 2,
    dashArray: "8 6",
    fillColor: state.drawArea.color,
    fillOpacity: 0.2,
  };
  if (latlngs.length >= 3) {
    L.polygon(latlngs, shapeOptions).addTo(leaf.drawLayer);
  } else if (latlngs.length === 2) {
    L.polyline(latlngs, { ...shapeOptions, fill: false }).addTo(leaf.drawLayer);
  }
  for (const point of state.drawArea.points) {
    L.circleMarker([point.y, point.x], {
      radius: 4,
      color: "#ffffff",
      weight: 1.2,
      fillColor: state.drawArea.color,
      fillOpacity: 1,
    }).addTo(leaf.drawLayer);
  }
}

function refreshMarkerStyles(leaf) {
  for (const entry of Object.values(leaf.markers)) {
    applyMarkerStyle(entry);
  }
}

function fitMapToData(leaf) {
  const bounds = boundsFromMapData();
  if (!bounds) return false;
  if (!elements.leafletMap.clientWidth || !elements.leafletMap.clientHeight) {
    // Container not laid out yet (map mode may have just become visible);
    // do not lock in a fit computed against a zero-sized map.
    return false;
  }
  leaf.map.invalidateSize();
  leaf.map.fitBounds(leafletBoundsFrom(bounds), { padding: [30, 30] });
  leaf.fitZoom = leaf.map.getZoom();
  leaf.fitted = true;
  return true;
}

function resetMapView() {
  if (!state.leaflet) return;
  fitMapToData(state.leaflet);
}

function centerMapOnPhoto(photoId, zoomIn = false) {
  const leaf = state.leaflet;
  const photo = state.photos.find((item) => item.id === photoId);
  if (!leaf || !photo || photo.projected_x == null || photo.projected_y == null) return;
  const zoom = zoomIn
    ? Math.max(leaf.map.getZoom(), leaf.fitZoom + 1.25)
    : leaf.map.getZoom();
  leaf.map.setView([photo.projected_y, photo.projected_x], zoom);
}

function renderMap() {
  elements.mapCanvas.classList.toggle("is-draw-mode", state.drawArea.active);
  elements.drawAreaButton.classList.toggle("is-active", state.drawArea.active);
  renderMapSummary();
  renderMapOverlayPicker();

  if (!state.currentProjectId) {
    setMapStateOverlay("No template selected", "Create or select a template before reviewing site map data.");
    renderMapEmptyDetail("Create or select a template to load areas, overlays, and pano points.");
    return;
  }
  if (state.mapDataLoading) {
    setMapStateOverlay("Loading map data", "Preparing area footprints, overlay context, and pano points.");
    renderMapEmptyDetail("Map data is loading. The selection panel will update after the workspace is ready.");
    return;
  }
  if (!state.mapData) {
    setMapStateOverlay("Map data failed to load", state.mapDataError || "Refresh the project and try again.", "error");
    renderMapEmptyDetail(state.mapDataError || "Map data is not available yet.");
    return;
  }

  const bounds = boundsFromMapData();
  if (!bounds) {
    const message = !state.areas.length
      ? "Add DXF/KML areas or import an overlay to establish site context."
      : "Import DJI pano photos to populate the map review workspace.";
    setMapStateOverlay("No map geometry yet", state.overlay?.error || message);
    renderMapEmptyDetail(message);
    return;
  }

  setMapStateOverlay("", "");
  const leaf = ensureLeafletMap();
  syncLeafletLayers(leaf);
  refreshMarkerStyles(leaf);
  syncDrawLayer(leaf);
  if (!leaf.fitted && !fitMapToData(leaf)) {
    // Deferred fit: the container had no size yet (hidden section). The fit
    // completes from setReviewMode when the map mode becomes visible.
    window.setTimeout(() => {
      if (state.leaflet === leaf && !leaf.fitted) {
        fitMapToData(leaf);
      }
    }, 120);
  }

  const visiblePointCount = Object.keys(leaf.markers).length;
  if (!visiblePointCount && state.photos.length) {
    setMapStateOverlay("No visible pano points", "Enable Show Processed Panos or adjust imported photo data to display points.");
  }

  if (state.drawArea.active) {
    renderMapDrawDetail();
    return;
  }

  const selectedPhoto = selectedMapPhoto();
  if (selectedPhoto) {
    renderMapSelectedDetail(selectedPhoto);
    return;
  }

  renderMapEmptyDetail();
}

function focusPhotoOnMap(photoId) {
  const targetPhoto = state.photos.find((photo) => photo.id === photoId);
  if (!targetPhoto) return;
  state.selectedPhotoId = photoId;
  setTab("map");
  if (!state.mapData && !state.mapDataLoading) {
    refreshMapData().then(() => {
      focusPhotoOnMap(photoId);
    }).catch(() => {
      renderPhotos();
      renderProcessed();
      renderMap();
    });
    renderPhotos();
    renderProcessed();
    return;
  }
  renderPhotos();
  renderProcessed();
  renderMap();
  centerMapOnPhoto(photoId, true);
}

function handleArchiveClick(event) {
  const folderButton = event.target.closest("[data-archive-folder-id]");
  if (folderButton) {
    const raw = folderButton.dataset.archiveFolderId;
    state.currentArchiveFolderId = raw ? Number(raw) : null;
    renderArchive();
    return;
  }
  const viewButton = event.target.closest("[data-view-photo-id]");
  if (viewButton) {
    loadViewer(Number(viewButton.dataset.viewPhotoId), "viewer", state.currentCollectionId).catch((error) => setStatus(error.message, true));
    return;
  }
  const fileButton = event.target.closest("[data-open-file-photo-id]");
  if (fileButton) {
    const photo = state.archivePhotos.find((item) => item.id === Number(fileButton.dataset.openFilePhotoId));
    if (photo) {
      openDesktopPath(photo.original_path, "open").catch((error) => setStatus(error.message, true));
    }
    return;
  }
  const folderOpenButton = event.target.closest("[data-open-folder-photo-id]");
  if (folderOpenButton) {
    const photo = state.archivePhotos.find((item) => item.id === Number(folderOpenButton.dataset.openFolderPhotoId));
    if (photo) {
      openDesktopPath(photo.original_path, "folder").catch((error) => setStatus(error.message, true));
    }
  }
}

function handleCollectionsClick(event) {
  const collectionButton = event.target.closest("[data-collection-id]");
  if (collectionButton) {
    loadCollection(Number(collectionButton.dataset.collectionId)).catch((error) => setStatus(error.message, true));
    return;
  }
  const viewButton = event.target.closest("[data-view-photo-id]");
  if (viewButton && state.currentCollectionId) {
    loadViewer(Number(viewButton.dataset.viewPhotoId), "collection", state.currentCollectionId).catch((error) => setStatus(error.message, true));
    return;
  }
  const row = event.target.closest("#collection-photos-table tr[data-photo-id]");
  if (row && state.currentCollectionId) {
    loadViewer(Number(row.dataset.photoId), "collection", state.currentCollectionId).catch((error) => setStatus(error.message, true));
  }
}

function handleViewerOverlayClick(event) {
  const target = event.target.closest("[data-view-photo-id]");
  if (!target) return;
  const photoId = Number(target.dataset.viewPhotoId);
  if (!Number.isFinite(photoId)) return;
  const context = state.viewerContext.source === "collection" ? "collection" : "viewer";
  const collectionId = state.viewerContext.collectionId;
  loadViewer(photoId, context, collectionId).catch((error) => setStatus(error.message, true));
}

async function createProject(event) {
  event.preventDefault();
  const name = elements.projectName.value.trim();
  if (!name) return;
  await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  elements.projectName.value = "";
  await loadProjects();
  setStatus(`Created template "${name}".`);
}

async function deleteCurrentProject() {
  if (!state.currentProjectId) return;
  const current = state.projects.find((project) => project.id === state.currentProjectId);
  if (!current) return;
  const accepted = await showDecisionModal({
    title: "Delete Template",
    description: `Delete template "${current.name}"? This removes it from the app.`,
    primaryLabel: "Delete Template",
    danger: true,
  });
  if (!accepted) return;
  await api(`/api/projects/${state.currentProjectId}`, {
    method: "DELETE",
  });
  state.currentProjectId = null;
  await loadProjects();
  setStatus(`Deleted template "${current.name}".`);
}

async function addArea() {
  if (!state.currentProjectId) return;
  let name = "";
  if (usingDesktopBridge()) {
    const [path] = await pickPaths("dxf");
    if (!path) return;
    name = stemName(path) || "Imported Area";
    await api(`/api/projects/${state.currentProjectId}/areas`, {
      method: "POST",
      body: JSON.stringify({ name, source_path: path }),
    });
  } else {
    const [file] = await chooseBrowserFiles(elements.areaFileInput);
    if (!file) return;
    name = stemName(file.name) || "Imported Area";
    const formData = new FormData();
    formData.append("name", name);
    formData.append("file", file, file.webkitRelativePath || file.name);
    await api(`/api/projects/${state.currentProjectId}/areas/upload`, {
      method: "POST",
      body: formData,
      timeoutMs: 0,
    });
  }
  await refreshProjectData();
  setStatus(`Imported area "${name}".`);
}

async function addBlankArea() {
  if (!requireCurrentProject("add a blank area")) return;
  const result = await showAreaModal({
    title: "Add Blank Area",
    description: "Create a manual area record without importing a DXF/KML file.",
    primaryLabel: "Create Area",
    textLabel: "Area name",
    textPlaceholder: "Area name",
    colorValue: "#175c4c",
  });
  const name = result?.text?.trim();
  if (!name) return;
  await api(`/api/projects/${state.currentProjectId}/areas`, {
    method: "POST",
    body: JSON.stringify({ name, display_color: result.color }),
  });
  await refreshProjectData();
  setStatus(`Created blank area "${name}".`);
}

function startDrawArea() {
  if (!state.currentProjectId) {
    setStatus("Create or select a template first.", true);
    return;
  }
  if (!boundsFromMapData()) {
    setStatus("Load an overlay, area file, or photos before drawing.", true);
    return;
  }
  resetDrawArea();
  state.selectedPhotoId = null;
  state.drawArea.active = true;
  renderPhotos();
  renderProcessed();
  renderMap();
}

async function saveDrawArea() {
  if (!state.currentProjectId) return;
  const name = state.drawArea.name.trim();
  if (!name) {
    setStatus("Drawn area needs a name before saving.", true);
    return;
  }
  if (state.drawArea.points.length < 3) {
    setStatus("Drawn area needs at least 3 points.", true);
    return;
  }
  await api(`/api/projects/${state.currentProjectId}/areas`, {
    method: "POST",
    body: JSON.stringify({
      name,
      display_color: state.drawArea.color,
      coordinates: state.drawArea.points.map((point) => [point.x, point.y]),
    }),
  });
  resetDrawArea();
  await refreshProjectData();
  setStatus(`Saved area "${name}".`);
}

async function importOverlay() {
  if (!state.currentProjectId) {
    setStatus("Create or select a template before importing an overlay.", true);
    return;
  }
  let sourceLabels = [];
  if (usingDesktopBridge()) {
    const paths = await pickPaths("overlay");
    if (!paths.length) return;
    sourceLabels = paths.map(shortPath);
    for (const path of paths) {
      await api(`/api/projects/${state.currentProjectId}/overlay`, {
        method: "POST",
        body: JSON.stringify({ source_path: path }),
      });
    }
  } else {
    const files = await chooseBrowserFiles(elements.overlayFileInput);
    if (!files.length) return;
    sourceLabels = files.map((file) => file.name);
    for (const file of files) {
      const formData = new FormData();
      formData.append("file", file, file.webkitRelativePath || file.name);
      await api(`/api/projects/${state.currentProjectId}/overlay/upload`, {
        method: "POST",
        body: formData,
        timeoutMs: 0,
      });
    }
  }
  await refreshProjectData();
  setStatus(sourceLabels.length === 1
    ? `Imported overlay from ${sourceLabels[0]}.`
    : `Imported ${sourceLabels.length} overlays.`);
  setTab("overlay");
}

async function renameOverlay(overlayId) {
  const overlay = (state.overlays || []).find((item) => item.id === overlayId);
  if (!state.currentProjectId || !overlay) return;
  const currentName = overlayDisplayName(overlay);
  const name = await showTextModal({
    title: "Rename Overlay",
    description: "Update the overlay name shown in the setup library.",
    primaryLabel: "Rename Overlay",
    textLabel: "Overlay name",
    textValue: currentName,
    textPlaceholder: "Overlay name",
  });
  if (!name.trim() || name.trim() === currentName) return;
  await api(`/api/projects/${state.currentProjectId}/overlays/${overlayId}`, {
    method: "PATCH",
    body: JSON.stringify({ display_name: name.trim() }),
  });
  await refreshProjectData();
  setStatus(`Renamed overlay to "${name.trim()}".`);
}

async function deleteOverlay(overlayId) {
  const overlay = (state.overlays || []).find((item) => item.id === overlayId);
  if (!state.currentProjectId || !overlay) return;
  const name = overlayDisplayName(overlay);
  const accepted = await showDecisionModal({
    title: "Delete Overlay",
    description: `Remove "${name}" from this template? The source file will stay on disk.`,
    primaryLabel: "Delete Overlay",
    danger: true,
  });
  if (!accepted) return;
  await api(`/api/projects/${state.currentProjectId}/overlays/${overlayId}`, {
    method: "DELETE",
  });
  await refreshProjectData();
  setStatus(`Deleted overlay "${name}".`);
}

async function importPhotos(paths) {
  if (!requireCurrentProject("import photos") || !paths.length) return;
  const payload = await withBusy(
    "Importing photos…",
    "Scanning the selected files and folders, reading metadata, and matching areas.",
    async () => {
      const response = await api(`/api/projects/${state.currentProjectId}/photos/import`, {
        method: "POST",
        body: JSON.stringify({ paths }),
        timeoutMs: 0,
      });
      await refreshProjectData();
      return response;
    },
  );
  const summary = payload?.summary || {};
  setStatus(`Import complete. ${summary.imported || 0} imported, ${summary.duplicates || 0} duplicates skipped, ${summary.errors || 0} errors.`);
  setTab("photos");
}

async function importPhotoFiles(files) {
  const uploadableFiles = [...files].filter((file) => /\.(jpe?g|png)$/i.test(file.name));
  if (!state.currentProjectId || !uploadableFiles.length) return;
  const payload = await withBusy(
    "Uploading photos…",
    "Uploading the selected files to the server, reading metadata, and matching areas.",
    async () => {
      const response = await api(`/api/projects/${state.currentProjectId}/photos/upload`, {
        method: "POST",
        body: buildUploadFormData(uploadableFiles),
        timeoutMs: 0,
      });
      await refreshProjectData();
      return response;
    },
  );
  const summary = payload?.summary || {};
  setStatus(`Import complete. ${summary.imported || 0} imported, ${summary.duplicates || 0} duplicates skipped, ${summary.errors || 0} errors.`);
  setTab("photos");
}

function sharedNamingStatusText(settings) {
  if (!settings.enabled) return "Shared naming is off.";
  if (!settings.supabase_url || !settings.supabase_anon_key) {
    return "Shared naming is on, but the Supabase URL or anon key is missing.";
  }
  return "Shared naming is on.";
}

async function loadSharedNamingSettings() {
  const settings = await api("/api/settings/shared-naming");
  state.sharedNamingSettings = settings;
  elements.sharedNamingEnabled.checked = Boolean(settings.enabled);
  elements.sharedNamingUrl.value = settings.supabase_url || "";
  elements.sharedNamingKey.value = settings.supabase_anon_key || "";
  elements.sharedNamingComputer.value = settings.computer_name || "";
  elements.sharedNamingComputer.placeholder = settings.default_computer_name || "This computer";
  elements.sharedNamingSyncAreas.checked = Boolean(settings.sync_areas);
  elements.sharedNamingStatus.textContent = sharedNamingStatusText(settings);
}

async function saveSharedNamingSettings() {
  const settings = await api("/api/settings/shared-naming", {
    method: "PUT",
    body: JSON.stringify({
      enabled: elements.sharedNamingEnabled.checked,
      supabase_url: elements.sharedNamingUrl.value.trim(),
      supabase_anon_key: elements.sharedNamingKey.value.trim(),
      computer_name: elements.sharedNamingComputer.value.trim(),
      sync_areas: elements.sharedNamingSyncAreas.checked,
    }),
  });
  state.sharedNamingSettings = settings;
  elements.sharedNamingStatus.textContent = sharedNamingStatusText(settings);
  setStatus("Shared naming settings saved.");
}

async function runAreaSyncNow() {
  await saveSharedNamingSettings();
  elements.areaSyncResult.textContent = "Syncing areas...";
  const summary = await api("/api/area-sync/run", {
    method: "POST",
    body: JSON.stringify({ project_id: state.currentProjectId }),
    timeoutMs: 120000,
  });
  reportAreaSync(summary);
  const pulledChanges = summary.pulled_new + summary.pulled_updated + summary.deactivated > 0;
  if (summary.ok && (summary.templates_created > 0 || pulledChanges)) {
    await loadProjects();
    await refreshProjectData();
  }
}

async function testSharedNamingConnection() {
  await saveSharedNamingSettings();
  elements.sharedNamingStatus.textContent = "Testing Supabase connection...";
  const result = await api("/api/settings/shared-naming/test", {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (result.ok) {
    elements.sharedNamingStatus.textContent = "Connected. Shared naming is ready.";
    setStatus("Supabase connection succeeded.");
  } else {
    elements.sharedNamingStatus.textContent = result.error || "Connection failed.";
    setStatus(result.error || "Supabase connection failed.", true);
  }
}

async function runSharedNamingBackfill() {
  if (!state.currentProjectId) {
    setStatus("Select a template before scanning for existing names.", true);
    return;
  }
  elements.sharedNamingBackfillResult.textContent = "Scanning photos...";
  try {
    const result = await api(`/api/projects/${state.currentProjectId}/shared-naming/backfill`, {
      method: "POST",
      body: JSON.stringify({}),
      timeoutMs: 60000,
    });
    elements.sharedNamingBackfillResult.textContent =
      `Scanned ${result.scanned} photo${result.scanned === 1 ? "" : "s"}, recognized ${result.matched} name${result.matched === 1 ? "" : "s"}, added ${result.added} to the shared registry.`;
    setStatus(`Shared registry scan complete. ${result.added} name${result.added === 1 ? "" : "s"} added.`);
  } catch (error) {
    elements.sharedNamingBackfillResult.textContent = error.message;
    setStatus(error.message, true);
    return;
  }
}

function maybeLoadSettingsForTab(tabName) {
  if (tabName !== "settings") return;
  loadSharedNamingSettings().catch((error) => {
    elements.sharedNamingStatus.textContent = error.message;
  });
  loadSmartSettings().catch((error) => {
    elements.smartSettingsStatus.textContent = error.message;
  });
}

function smartSettingsStatusText(settings) {
  const missing = [];
  if (!settings.import_base_path) missing.push("import folder");
  if (!settings.archive_base_path) missing.push("archive folder");
  if (settings.ftp_enabled && (!settings.ftp_host || !settings.ftp_username)) {
    missing.push("FTP server (or turn upload off)");
  }
  if (missing.length) return `Smart Mode needs: ${missing.join(", ")}.`;
  return settings.ftp_enabled
    ? "Smart Mode is fully configured."
    : "Smart Mode is configured. Server upload is off — exports stay local.";
}

function applyUiMode(mode) {
  const smart = mode === "smart";
  document.body.classList.toggle("smart-mode", smart);
  const reviewTab = elements.tabs.find((tab) => tab.dataset.tab === "review");
  if (reviewTab) reviewTab.textContent = smart ? "Smart View" : "Review";
  elements.reviewEyebrow.textContent = smart ? "Smart Mode" : "Review Workspace";
  elements.reviewTitle.textContent = smart ? "Smart View" : "Review";
  elements.reviewDescription.textContent = smart
    ? "Insert the SD card and press Smart Import. Smart Export renames, uploads, and archives."
    : "One workspace for spatial review and 360 inspection.";
  elements.modeToggleButton.textContent = smart ? "Switch to Advanced" : "Switch to Smart Mode";
  if (smart) {
    setTab("map");
    maybeRefreshMapForTab("map");
  }
}

async function loadSmartSettings() {
  const settings = await api("/api/smart/settings");
  state.smartSettings = settings;
  elements.smartImportBase.value = settings.import_base_path || "";
  elements.smartArchiveBase.value = settings.archive_base_path || "";
  elements.smartFtpHost.value = settings.ftp_host || "";
  elements.smartFtpPort.value = settings.ftp_port > 0 ? settings.ftp_port : "";
  elements.smartFtpUsername.value = settings.ftp_username || "";
  elements.smartFtpPassword.value = settings.ftp_password || "";
  elements.smartFtpRemotePath.value = settings.ftp_remote_path || "";
  elements.smartFtpProtocol.value = settings.ftp_protocol || "ftp";
  elements.smartFtpEnabled.checked = Boolean(settings.ftp_enabled);
  elements.smartSettingsStatus.textContent = smartSettingsStatusText(settings);
  applyUiMode(settings.ui_mode);
}

async function saveSmartSettings() {
  const settings = await api("/api/smart/settings", {
    method: "PUT",
    body: JSON.stringify({
      import_base_path: elements.smartImportBase.value.trim(),
      archive_base_path: elements.smartArchiveBase.value.trim(),
      ftp_host: elements.smartFtpHost.value.trim(),
      ftp_port: Number(elements.smartFtpPort.value) || 0,
      ftp_username: elements.smartFtpUsername.value.trim(),
      ftp_password: elements.smartFtpPassword.value,
      ftp_remote_path: elements.smartFtpRemotePath.value.trim(),
      ftp_protocol: elements.smartFtpProtocol.value,
      ftp_enabled: elements.smartFtpEnabled.checked,
    }),
  });
  state.smartSettings = settings;
  elements.smartSettingsStatus.textContent = smartSettingsStatusText(settings);
  setStatus("Smart Mode settings saved.");
}

async function toggleUiMode() {
  const current = state.smartSettings?.ui_mode || "advanced";
  const next = current === "smart" ? "advanced" : "smart";
  const settings = await api("/api/smart/settings", {
    method: "PUT",
    body: JSON.stringify({ ui_mode: next }),
  });
  state.smartSettings = settings;
  applyUiMode(settings.ui_mode);
}

async function testSmartFtp() {
  await saveSmartSettings();
  elements.smartSettingsStatus.textContent = "Testing FTP connection...";
  const result = await api("/api/smart/ftp-test", {
    method: "POST",
    body: JSON.stringify({}),
    timeoutMs: 60000,
  });
  if (result.ok) {
    elements.smartSettingsStatus.textContent = "FTP connection succeeded.";
    setStatus("FTP connection succeeded.");
  } else {
    elements.smartSettingsStatus.textContent = result.error || "FTP connection failed.";
    setStatus(result.error || "FTP connection failed.", true);
  }
}

function openSmartProgress(title, steps) {
  elements.smartProgressTitle.textContent = title;
  elements.smartProgressSummary.textContent = "Working…";
  elements.smartProgressSteps.innerHTML = "";
  steps.forEach((label, index) => {
    const item = document.createElement("li");
    item.textContent = label;
    if (index === 0) item.classList.add("active");
    elements.smartProgressSteps.appendChild(item);
  });
  elements.smartProgressLive.hidden = false;
  elements.smartProgressLiveText.textContent = "Starting…";
  elements.smartProgressCloseButton.disabled = true;
  elements.smartProgressModal.hidden = false;
}

function setSmartProgressStep(activeIndex, liveText) {
  [...elements.smartProgressSteps.children].forEach((item, index) => {
    item.classList.toggle("done", index < activeIndex);
    item.classList.toggle("active", index === activeIndex);
    item.classList.remove("error");
  });
  if (liveText) {
    elements.smartProgressLiveText.textContent = liveText;
  }
}

function finishSmartProgress(summaryText, failed) {
  [...elements.smartProgressSteps.children].forEach((item) => {
    item.classList.remove("active");
    item.classList.add(failed ? "error" : "done");
  });
  elements.smartProgressLive.hidden = true;
  elements.smartProgressSummary.textContent = summaryText;
  elements.smartProgressCloseButton.disabled = false;
}

function smartGuardFail(title, message) {
  openSmartProgress(title, []);
  finishSmartProgress(message, true);
  setStatus(message, true);
}

async function runSmartImport() {
  if (!state.currentProjectId) {
    smartGuardFail("Smart Import", "No template selected. Switch to Advanced mode and pick one under System → Settings.");
    return;
  }
  if (state.smartBusy) return;
  state.smartBusy = true;
  openSmartProgress("Smart Import", [
    "Find SD card",
    "Scan for 360 panos",
    "Check shared registry for duplicates",
    "Copy new panos to dated folder",
    "Stage panos on the map",
  ]);
  try {
    const response = await fetch("/api/smart/import/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.currentProjectId }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `Smart Import failed (HTTP ${response.status}).`);
    }
    let result = null;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const handleEvent = (event) => {
      if (event.stage === "detect") {
        setSmartProgressStep(1, `Card found: ${event.source_path}`);
      } else if (event.stage === "scan") {
        setSmartProgressStep(1, `Scanned ${event.scanned} of ${event.total} files — ${event.panos} pano${event.panos === 1 ? "" : "s"} found`);
      } else if (event.stage === "dedupe") {
        setSmartProgressStep(2, `Checking ${event.checking} pano${event.checking === 1 ? "" : "s"} against the shared registry…`);
      } else if (event.stage === "copy") {
        setSmartProgressStep(3, `Accepted ${event.copied} of ${event.processed} checked (${event.duplicates} duplicate${event.duplicates === 1 ? "" : "s"} skipped)`);
      } else if (event.stage === "stage") {
        setSmartProgressStep(4, `Staging ${event.total} pano${event.total === 1 ? "" : "s"} on the map…`);
      } else if (event.stage === "error") {
        throw new Error(event.detail || "Smart Import failed.");
      } else if (event.stage === "done") {
        result = event.result;
      }
    };
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) handleEvent(JSON.parse(line));
      }
    }
    if (!result) {
      throw new Error("Smart Import ended without a result — check the server log.");
    }
    const parts = [
      `Found ${result.panos_found} pano${result.panos_found === 1 ? "" : "s"} (${result.normal_skipped} other photos ignored).`,
      `${result.duplicates_skipped} duplicate${result.duplicates_skipped === 1 ? "" : "s"} skipped.`,
      `${result.copied} copied, ${result.staged} staged on the map.`,
    ];
    if (!result.registry_checked) {
      parts.push("Shared registry was not checked (Supabase not configured).");
    }
    finishSmartProgress(parts.join(" "), false);
    setStatus(`Smart Import complete. ${result.staged} pano${result.staged === 1 ? "" : "s"} staged.`);
    await refreshProjectData();
    setTab("map");
  } catch (error) {
    finishSmartProgress(error.message, true);
    setStatus(error.message, true);
  } finally {
    state.smartBusy = false;
  }
}

async function runSmartExport() {
  if (!state.currentProjectId) {
    smartGuardFail("Smart Export", "No template selected. Switch to Advanced mode and pick one under System → Settings.");
    return;
  }
  if (state.smartBusy) return;
  state.smartBusy = true;
  openSmartProgress("Smart Export", [
    "Rename staged panos",
    "Register in shared registry",
    "Upload to FTP",
    "Archive locally",
  ]);
  elements.smartProgressLiveText.textContent = "Renaming, registering, uploading…";
  try {
    const result = await api("/api/smart/export", {
      method: "POST",
      body: JSON.stringify({ project_id: state.currentProjectId }),
      timeoutMs: 600000,
    });
    const parts = [
      `${result.renamed} renamed, ${result.registered} registered, ${result.uploaded} uploaded, ${result.archived} archived.`,
    ];
    if (result.failed) {
      parts.push(`${result.failed} failed.`);
    }
    if (result.errors.length) {
      parts.push(result.errors.slice(0, 5).join(" "));
    }
    finishSmartProgress(parts.join(" "), Boolean(result.failed || result.errors.length));
    setStatus(
      `Smart Export complete. ${result.uploaded} uploaded, ${result.archived} archived${result.failed ? `, ${result.failed} failed` : ""}.`,
      Boolean(result.failed),
    );
    await refreshProjectData();
  } catch (error) {
    finishSmartProgress(error.message, true);
    setStatus(error.message, true);
  } finally {
    state.smartBusy = false;
  }
}

async function runRename() {
  if (!state.currentProjectId) return;
  const readyCount = pendingPhotos().filter(photoReadyToRename).length;
  const attentionCount = pendingPhotos().filter(photoNeedsAttention).length;
  if (!readyCount) {
    setStatus("No eligible pending photos are ready to rename.", true);
    setTab("photos");
    return;
  }
  let description = `Rename ${readyCount} eligible photo${readyCount === 1 ? "" : "s"}${attentionCount ? ` and leave ${attentionCount} needing attention in Pending` : ""}?`;
  let primaryLabel = "Rename Eligible Photos";
  const preview = await api(`/api/projects/${state.currentProjectId}/shared-naming/preview`, { timeoutMs: 30000 });
  if (preview.enabled) {
    if (!preview.connected) {
      setStatus(preview.error || "Cannot create shared pano names while offline. Reconnect to Supabase or disable Shared Pano Naming for this export.", true);
      return;
    }
    const groupLines = (preview.groups || []).map(
      (group) => `${group.prefix}: ${group.photos} photo${group.photos === 1 ? "" : "s"}, names begin at ${String(group.starts_at).padStart(3, "0")}.`,
    );
    description = `Shared naming: Connected. ${groupLines.join(" ")} ${description}`;
    primaryLabel = "Reserve Names and Export";
  }
  const accepted = await showDecisionModal({
    title: "Rename Eligible Photos",
    description,
    primaryLabel,
  });
  if (!accepted) return;
  const run = await api(`/api/projects/${state.currentProjectId}/rename-runs`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  await refreshProjectData();
  const summary = run?.summary || {};
  setStatus(
    `Rename complete. ${summary.renamed || 0} renamed, ${summary.unchanged || 0} unchanged, ${summary.errors || 0} errors.`,
    false,
  );
  setTab("processed");
}

async function rollbackLastRun() {
  if (!state.currentProjectId || !state.runs.length) return;
  const latestRun = state.runs[0];
  if (!latestRun || latestRun.rollback_completed_at) return;
  const accepted = await showDecisionModal({
    title: "Rollback Last Run",
    description: "Rollback the most recent rename run for this template?",
    primaryLabel: "Rollback Run",
    danger: true,
  });
  if (!accepted) return;
  const run = await api(`/api/projects/${state.currentProjectId}/rename-runs/${latestRun.id}/rollback`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  await refreshProjectData();
  const rollbackResults = run?.rollback_results || [];
  const restored = rollbackResults.filter((result) => ["rolled_back", "restored_pending"].includes(result.status)).length;
  const errors = rollbackResults.length - restored;
  setStatus(`Rollback complete. ${restored} restored, ${errors} errors.`);
  setTab("photos");
}

async function createArchiveFolder() {
  const name = elements.archiveFolderName.value.trim();
  if (!name) return;
  const folder = await api("/api/archive-folders", {
    method: "POST",
    body: JSON.stringify({ name, parent_id: null }),
  });
  elements.archiveFolderName.value = "";
  state.currentArchiveFolderId = folder.id;
  await refreshProjectData();
  setStatus(`Created archive folder "${name}".`);
}

async function archiveSelected() {
  await archiveSelectedPhotos();
  await refreshProjectData();
  setStatus("Archived selected panos.");
}

async function createCollection() {
  const name = elements.collectionName.value.trim();
  if (!name) return;
  const collection = await api("/api/collections", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  elements.collectionName.value = "";
  state.currentCollectionId = collection.id;
  await refreshProjectData();
  setStatus(`Created collection "${name}".`);
}

async function addSelectedToCollection() {
  if (!state.currentCollectionId) {
    throw new Error("Create or select a collection first.");
  }
  const photoIds = [...state.selectedPhotoIds];
  if (!photoIds.length) {
    throw new Error("Select one or more photos first.");
  }
  await api(`/api/collections/${state.currentCollectionId}/items`, {
    method: "POST",
    body: JSON.stringify({ photo_ids: photoIds }),
  });
  await refreshProjectData();
  setStatus("Added selected panos to the collection.");
}

async function loadCollection(collectionId) {
  state.currentCollectionId = Number(collectionId) || null;
  state.collectionDetail = state.currentCollectionId ? await api(`/api/collections/${state.currentCollectionId}/detail`) : null;
  if (state.viewerContext.source === "collection" && state.viewerPayload) {
    const suffix = state.currentCollectionId ? `?collection_id=${state.currentCollectionId}` : "";
    state.viewerPayload = state.currentCollectionId
      ? await api(`/api/photos/${state.viewerPayload.photo.id}/viewer${suffix}`, { timeoutMs: 30000 })
      : null;
  }
  renderCollections();
}

async function loadViewer(photoId, source = "viewer", collectionId = null) {
  state.selectedPhotoId = Number(photoId);
  state.viewerContext = { source, collectionId };
  const suffix = collectionId ? `?collection_id=${collectionId}` : "";
  state.viewerPayload = await api(`/api/photos/${photoId}/viewer${suffix}`, { timeoutMs: 30000 });
  applyViewerPose(state.viewerPayload.photo, currentViewerPose(state.viewerPayload.photo));
  renderViewer();
  renderCollections();
  if (source === "viewer" || source === "archive") {
    setTab("viewer");
  }
}

async function stepViewer(delta, source = state.viewerContext.source) {
  const sequence = viewerSequence();
  const index = currentViewerIndex();
  if (index < 0) return;
  const next = sequence[index + delta];
  if (!next) return;
  await loadViewer(next.id, source, state.viewerContext.collectionId);
}

async function saveViewerState() {
  const photo = viewerPhoto();
  if (!photo) return;
  const pose = currentViewerPose(photo);
  await api(`/api/photos/${photo.id}/viewer-state`, {
    method: "PUT",
    body: JSON.stringify({
      north_offset: Number(elements.viewerNorthOffset.value || 0),
      default_yaw: Number(elements.viewerDefaultYaw.value || pose.yaw || 0),
      default_pitch: pose.pitch || 0,
      default_fov: pose.fov || 75,
    }),
  });
  await loadViewer(photo.id, state.viewerContext.source, state.viewerContext.collectionId);
  setStatus("Saved pano orientation.");
}

function findOrCreateTagIdByName(name) {
  const normalized = name.trim();
  const existing = state.tags.find((tag) => tag.name.toLowerCase() === normalized.toLowerCase());
  if (existing) return Promise.resolve(existing.id);
  return api("/api/tags", {
    method: "POST",
    body: JSON.stringify({ name: normalized }),
  }).then((tag) => {
    state.tags.push(tag);
    return tag.id;
  });
}

async function addViewerTag() {
  const photo = viewerPhoto();
  const name = elements.viewerTagName.value.trim();
  if (!photo || !name) return;
  const tagId = await findOrCreateTagIdByName(name);
  await api(`/api/photos/${photo.id}/tags`, {
    method: "POST",
    body: JSON.stringify({ tag_ids: [tagId] }),
  });
  elements.viewerTagName.value = "";
  await loadViewer(photo.id, state.viewerContext.source, state.viewerContext.collectionId);
  await refreshProjectData();
  setStatus(`Added tag "${name}".`);
}

async function addAnnotation() {
  const photo = viewerPhoto();
  const label = elements.annotationLabel.value.trim();
  if (!photo || !label) return;
  await api(`/api/photos/${photo.id}/annotations`, {
    method: "POST",
    body: JSON.stringify({ annotation_type: "marker", label, yaw: 0, pitch: 0, style: { color: "#b8db66" } }),
  });
  elements.annotationLabel.value = "";
  await loadViewer(photo.id, state.viewerContext.source, state.viewerContext.collectionId);
  await refreshProjectData();
  setStatus("Added annotation.");
}

async function addIssue() {
  const photo = viewerPhoto();
  const title = elements.issueTitle.value.trim();
  if (!photo || !title) return;
  await api(`/api/photos/${photo.id}/issues`, {
    method: "POST",
    body: JSON.stringify({ title, severity: "medium", status: "open", yaw: 0, pitch: 0 }),
  });
  elements.issueTitle.value = "";
  await loadViewer(photo.id, state.viewerContext.source, state.viewerContext.collectionId);
  await refreshProjectData();
  setStatus("Added issue.");
}

async function addNote() {
  const photo = viewerPhoto();
  const noteText = elements.viewerNoteText.value.trim();
  if (!photo || !noteText) return;
  await api(`/api/photos/${photo.id}/notes`, {
    method: "POST",
    body: JSON.stringify({ note_text: noteText }),
  });
  elements.viewerNoteText.value = "";
  await loadViewer(photo.id, state.viewerContext.source, state.viewerContext.collectionId);
  await refreshProjectData();
  setStatus("Added note.");
}

async function addHotspot() {
  const photo = viewerPhoto();
  if (!photo) return;
  const targetRaw = await showTextModal({
    title: "Add Hotspot",
    description: "Enter the target pano/photo ID for this navigation hotspot.",
    primaryLabel: "Add Hotspot",
    textLabel: "Target photo ID",
    textPlaceholder: "Photo ID",
  });
  if (!targetRaw) return;
  const targetPhotoId = Number(targetRaw);
  if (!Number.isFinite(targetPhotoId)) return;
  await api(`/api/photos/${photo.id}/hotspots`, {
    method: "POST",
    body: JSON.stringify({ target_photo_id: targetPhotoId, yaw: 25, pitch: -5, label: `Pano ${targetPhotoId}` }),
  });
  await loadViewer(photo.id, state.viewerContext.source, state.viewerContext.collectionId);
  setStatus("Added hotspot.");
}

async function openDesktopPath(pathValue, mode = "open") {
  ensureBridge();
  if (state.bridge?.openPath) {
    state.bridge.openPath(pathValue, mode);
    return;
  }
  if (mode === "folder") {
    window.open(`file:///${pathValue.replace(/\\/g, "/")}`);
    return;
  }
  window.open(`file:///${pathValue.replace(/\\/g, "/")}`);
}

function openViewerPhotoOnMap() {
  const photo = viewerPhoto();
  if (!photo) return;
  focusPhotoOnMap(photo.id);
}

async function openSelectedViewerPath(mode) {
  const photo = viewerPhoto();
  if (!photo) return;
  if (mode === "folder") {
    await openDesktopPath(photo.original_path, "folder");
    return;
  }
  if (mode === "reveal") {
    await openDesktopPath(photo.original_path, "reveal");
    return;
  }
  await openDesktopPath(photo.original_path, "open");
}

async function exportCollection(kind) {
  if (!state.currentCollectionId) return;
  window.open(`/api/collections/${state.currentCollectionId}/report.${kind}`, "_blank");
}

async function updatePhotoArea(photoId, areaId) {
  if (!state.currentProjectId || !photoId) return;
  await api(`/api/projects/${state.currentProjectId}/photos/${photoId}`, {
    method: "PUT",
    body: JSON.stringify({ matched_area_id: areaId ? Number(areaId) : null }),
  });
  await refreshProjectData();
  setStatus("Updated manual area assignment.");
}

async function updateSelectedPhotoArea(areaId) {
  await updatePhotoArea(state.selectedPhotoId, areaId);
}

function selectedIdsFor(rows) {
  const ids = new Set(rows.map((photo) => photo.id));
  return [...state.selectedPhotoIds].filter((photoId) => ids.has(photoId));
}

function togglePhotoSelection(photoId, checked) {
  if (checked) {
    state.selectedPhotoIds.add(photoId);
  } else {
    state.selectedPhotoIds.delete(photoId);
  }
}

function selectAllRows(rows) {
  for (const photo of rows) {
    state.selectedPhotoIds.add(photo.id);
  }
  renderPhotos();
  renderProcessed();
}

async function removeSelected(rows) {
  const photoIds = selectedIdsFor(rows);
  if (!state.currentProjectId || !photoIds.length) {
    return;
  }
  const removed = await api(`/api/projects/${state.currentProjectId}/photos/remove`, {
    method: "POST",
    body: JSON.stringify({ photo_ids: photoIds }),
  });
  for (const photoId of photoIds) {
    state.selectedPhotoIds.delete(photoId);
  }
  if (state.selectedPhotoId && photoIds.includes(state.selectedPhotoId)) {
    state.selectedPhotoId = null;
  }
  await refreshProjectData();
  setStatus(`Removed ${removed.removed || 0} photo record${removed.removed === 1 ? "" : "s"} from the app.`);
}

async function removePhoto(photoId) {
  if (!state.currentProjectId || !photoId) return;
  const removed = await api(`/api/projects/${state.currentProjectId}/photos/remove`, {
    method: "POST",
    body: JSON.stringify({ photo_ids: [photoId] }),
  });
  state.selectedPhotoIds.delete(photoId);
  if (state.selectedPhotoId === photoId) {
    state.selectedPhotoId = null;
  }
  await refreshProjectData();
  setStatus(`Removed ${removed.removed || 0} photo record${removed.removed === 1 ? "" : "s"} from the app.`);
}

function extractDroppedPaths(event) {
  const files = [...event.dataTransfer.files];
  const paths = files.map((file) => file.path || "").filter(Boolean);
  if (paths.length) return paths;
  const uriList = event.dataTransfer.getData("text/uri-list");
  if (!uriList) return [];
  return uriList
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("file:///"))
    .map((line) => decodeURIComponent(line.replace("file:///", "").replaceAll("/", "\\")));
}

async function uploadAreaReplacement(areaId, file) {
  const formData = new FormData();
  formData.append("file", file, file.webkitRelativePath || file.name);
  await api(`/api/projects/${state.currentProjectId}/areas/${areaId}/upload`, {
    method: "PUT",
    body: formData,
    timeoutMs: 0,
  });
}

async function handleAreaAction(event) {
  const actionTarget = event.target.closest("[data-action]");
  if (!actionTarget) return;
  const areaId = actionTarget.dataset.id;
  const action = actionTarget.dataset.action;
  if (action === "color-area" && event.type !== "change") return;
  if (action === "delete-area") {
    await api(`/api/projects/${state.currentProjectId}/areas/${areaId}`, { method: "DELETE" });
    await refreshProjectData();
  } else if (action === "rename-area") {
    const current = state.areas.find((area) => String(area.id) === areaId);
    const name = await showTextModal({
      title: "Rename Area",
      description: "Update the display name for this area.",
      primaryLabel: "Rename Area",
      textLabel: "Area name",
      textValue: current?.name || "",
    });
    if (!name) return;
    await api(`/api/projects/${state.currentProjectId}/areas/${areaId}`, {
      method: "PUT",
      body: JSON.stringify({ name }),
    });
    await refreshProjectData();
  } else if (action === "replace-area") {
    if (usingDesktopBridge()) {
      const [path] = await pickPaths("dxf");
      if (!path) return;
      await api(`/api/projects/${state.currentProjectId}/areas/${areaId}`, {
        method: "PUT",
        body: JSON.stringify({ source_path: path }),
      });
    } else {
      const [file] = await chooseBrowserFiles(elements.areaFileInput);
      if (!file) return;
      await uploadAreaReplacement(areaId, file);
    }
    await refreshProjectData();
    setStatus("Replaced area file.");
  } else if (action === "color-area") {
    await api(`/api/projects/${state.currentProjectId}/areas/${areaId}`, {
      method: "PUT",
      body: JSON.stringify({ display_color: actionTarget.value }),
    });
    await refreshProjectData();
  }
}

function handlePhotoSelection(event) {
  const areaTrigger = event.target.closest("[data-area-menu-photo-id]");
  if (areaTrigger) {
    const photoId = Number(areaTrigger.dataset.areaMenuPhotoId);
    const scope = areaTrigger.dataset.areaMenuScope;
    const alreadyOpen =
      state.pendingAreaMenuPhotoId === photoId && state.pendingAreaMenuScope === scope;
    closePendingAreaMenu();
    if (!alreadyOpen) {
      state.pendingAreaMenuPhotoId = photoId;
      state.pendingAreaMenuScope = scope;
    }
    renderPhotos();
    return;
  }
  const areaOption = event.target.closest("[data-assign-area-photo-id]");
  if (areaOption) {
    closePendingAreaMenu();
    updatePhotoArea(
      Number(areaOption.dataset.assignAreaPhotoId),
      areaOption.dataset.assignAreaId || null,
    ).catch((error) => setStatus(error.message, true));
    return;
  }
  if (closePendingAreaMenu()) {
    renderPhotos();
  }
  const actionButton = event.target.closest("[data-action]");
  if (actionButton?.dataset.action === "view-map") {
    focusPhotoOnMap(Number(actionButton.dataset.photoId));
    return;
  }
  if (actionButton?.dataset.action === "remove-photo") {
    removePhoto(Number(actionButton.dataset.photoId)).catch((error) => setStatus(error.message, true));
    return;
  }
  const groupToggle = event.target.closest("[data-group-key]");
  if (groupToggle) {
    const key = groupToggle.dataset.groupKey;
    if (state.collapsedProcessedGroups.has(key)) {
      state.collapsedProcessedGroups.delete(key);
    } else {
      state.collapsedProcessedGroups.add(key);
    }
    renderProcessed();
    return;
  }
  const checkbox = event.target.closest("input[data-select-photo-id]");
  if (checkbox) {
    togglePhotoSelection(Number(checkbox.dataset.selectPhotoId), checkbox.checked);
    return;
  }
  const row = event.target.closest("tr[data-photo-id]");
  if (!row) return;
  state.selectedPhotoId = Number(row.dataset.photoId);
  renderPhotos();
  renderProcessed();
  renderMap();
  centerMapOnPhoto(state.selectedPhotoId);
}

function setHoverSuppressed(active) {
  state.suppressHover = active;
  document.body.classList.toggle("is-suspending-hover", active);
  if (active) {
    setMapHover(null);
  }
}

function handleMapLabelToggleChange() {
  state.mapLabels.enabled = elements.mapLabelsToggle.checked;
  state.mapLabels.showOriginal = elements.mapOriginalLabelToggle.checked;
  state.mapLabels.showProposed = elements.mapProposedLabelToggle.checked;
  elements.mapOriginalLabelToggle.disabled = !state.mapLabels.enabled;
  elements.mapProposedLabelToggle.disabled = !state.mapLabels.enabled;
  renderMap();
}

function handleMapDetailFocusIn(event) {
  if (event.target.closest(".area-picker")) {
    setHoverSuppressed(true);
  }
}

function handleMapDetailFocusOut(event) {
  if (!event.target.closest(".area-picker")) return;
  window.setTimeout(() => {
    if (!state.mapAreaMenuOpen && !document.activeElement?.closest?.(".area-picker")) {
      setHoverSuppressed(false);
    }
  }, 0);
}

function handlePendingViewChange() {
  state.pendingView.search = elements.pendingSearch.value;
  state.pendingView.showOriginal = elements.pendingShowOriginalToggle.checked;
  state.pendingView.showDate = elements.pendingShowDateToggle.checked;
  state.pendingView.showProposed = elements.pendingShowProposedToggle.checked;
  syncCustomSelect(elements.photoFilter);
  renderPhotos();
}

function handleMapVisibilityChange() {
  state.mapVisibility.showProcessed = elements.mapShowProcessedToggle.checked;
  renderMap();
}

function handleMapDetailClick(event) {
  const mapAction = event.target.closest("[data-map-action]");
  if (mapAction) {
    const selectedPhoto = selectedMapPhoto();
    if (!selectedPhoto) return;
    const action = mapAction.dataset.mapAction;
    if (action === "open-viewer") {
      loadViewer(selectedPhoto.id, "viewer", null).catch((error) => setStatus(error.message, true));
      return;
    }
    if (action === "open-source") {
      setTab(selectedPhoto.applied ? "processed" : "photos");
      renderPhotos();
      renderProcessed();
      return;
    }
    if (action === "remove-photo" && !selectedPhoto.applied) {
      removePhoto(selectedPhoto.id).catch((error) => setStatus(error.message, true));
      return;
    }
  }

  const drawSave = event.target.closest("#draw-area-save-button");
  if (drawSave) {
    saveDrawArea().catch((error) => setStatus(error.message, true));
    return;
  }
  const drawUndo = event.target.closest("#draw-area-undo-button");
  if (drawUndo) {
    state.drawArea.points.pop();
    renderMap();
    return;
  }
  const drawCancel = event.target.closest("#draw-area-cancel-button");
  if (drawCancel) {
    resetDrawArea();
    renderMap();
    return;
  }
  const areaTrigger = event.target.closest("#map-area-trigger");
  if (areaTrigger) {
    state.mapAreaMenuOpen = !state.mapAreaMenuOpen;
    setHoverSuppressed(state.mapAreaMenuOpen);
    renderMap();
    return;
  }
  const areaOption = event.target.closest("[data-area-option-id]");
  if (areaOption) {
    const raw = areaOption.dataset.areaOptionId;
    state.mapAreaDraftId = raw ? Number(raw) : null;
    state.mapAreaMenuOpen = false;
    setHoverSuppressed(false);
    renderMap();
    return;
  }
  const button = event.target.closest("#map-save-area-button");
  if (!button) return;
  state.mapAreaMenuOpen = false;
  setHoverSuppressed(false);
  updateSelectedPhotoArea(state.mapAreaDraftId).catch((error) => setStatus(error.message, true));
}

function handleMapDetailInput(event) {
  const nameInput = event.target.closest("#draw-area-name");
  if (nameInput) {
    state.drawArea.name = nameInput.value;
    const saveButton = document.getElementById("draw-area-save-button");
    if (saveButton) {
      saveButton.disabled = !(state.drawArea.points.length >= 3 && state.drawArea.name.trim());
    }
    return;
  }
  const colorInput = event.target.closest("#draw-area-color");
  if (colorInput) {
    state.drawArea.color = colorInput.value;
    renderMap();
  }
}

function handleArchiveClick(event) {
  const folderButton = event.target.closest("[data-archive-folder-id]");
  if (folderButton) {
    const raw = folderButton.dataset.archiveFolderId;
    state.currentArchiveFolderId = raw ? Number(raw) : null;
    renderArchive();
    return;
  }
  const viewButton = event.target.closest("[data-view-photo-id]");
  if (viewButton) {
    loadViewer(Number(viewButton.dataset.viewPhotoId), "archive", null).catch((error) => setStatus(error.message, true));
    return;
  }
  const openFileButton = event.target.closest("[data-open-file-photo-id]");
  if (openFileButton) {
    const photo = state.archivePhotos.find((item) => item.id === Number(openFileButton.dataset.openFilePhotoId));
    if (photo) {
      openDesktopPath(photo.original_path, "open").catch((error) => setStatus(error.message, true));
    }
    return;
  }
  const openFolderButton = event.target.closest("[data-open-folder-photo-id]");
  if (openFolderButton) {
    const photo = state.archivePhotos.find((item) => item.id === Number(openFolderButton.dataset.openFolderPhotoId));
    if (photo) {
      openDesktopPath(photo.original_path, "folder").catch((error) => setStatus(error.message, true));
    }
    return;
  }
  const row = event.target.closest("tr[data-photo-id]");
  if (!row) return;
  state.selectedPhotoId = Number(row.dataset.photoId);
  renderArchive();
}

function handleCollectionsClick(event) {
  const collectionButton = event.target.closest("[data-collection-id]");
  if (collectionButton) {
    loadCollection(Number(collectionButton.dataset.collectionId)).catch((error) => setStatus(error.message, true));
    return;
  }
  const photoTarget = event.target.closest("[data-view-photo-id], tr[data-photo-id]");
  if (!photoTarget) return;
  const photoId = Number(photoTarget.dataset.viewPhotoId || photoTarget.dataset.photoId);
  if (!photoId) return;
  loadViewer(photoId, "collection", state.currentCollectionId).catch((error) => setStatus(error.message, true));
}

function handleViewerOverlayClick(event) {
  const button = event.target.closest("[data-view-photo-id]");
  if (!button) return;
  const targetId = Number(button.dataset.viewPhotoId);
  if (!targetId) return;
  loadViewer(targetId, state.viewerContext.source, state.viewerContext.collectionId).catch((error) => setStatus(error.message, true));
}

async function toggleViewerFullscreen() {
  const shell = viewerShell();
  if (!shell) return;
  if (document.fullscreenElement === shell) {
    await document.exitFullscreen();
    return;
  }
  await shell.requestFullscreen();
}

function activeViewerPayloadForCanvas(canvas) {
  if (canvas === elements.viewerCanvas) {
    return state.viewerPayload;
  }
  if (canvas === elements.collectionViewerCanvas && state.viewerContext.source === "collection") {
    return state.viewerPayload;
  }
  return null;
}

function handleViewerPointerDown(event) {
  if (event.button !== 0) return;
  const canvas = event.currentTarget;
  const payload = activeViewerPayloadForCanvas(canvas);
  if (!payload) return;
  event.preventDefault();
  const pose = currentViewerPose(payload.photo);
  state.viewerDrag = {
    canvas,
    pointerId: event.pointerId,
    photoId: payload.photo.id,
    startClientX: event.clientX,
    startClientY: event.clientY,
    startYaw: pose.yaw,
    startPitch: pose.pitch,
  };
  canvas.classList.add("is-dragging");
  if (canvas.setPointerCapture) {
    canvas.setPointerCapture(event.pointerId);
  }
}

function handleViewerPointerMove(event) {
  if (!state.viewerDrag) return;
  const { canvas, photoId, startClientX, startClientY, startYaw, startPitch } = state.viewerDrag;
  const payload = activeViewerPayloadForCanvas(canvas);
  if (!payload || payload.photo.id !== photoId) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const pose = currentViewerPose(payload.photo);
  const deltaX = event.clientX - startClientX;
  const deltaY = event.clientY - startClientY;
  applyViewerPose(payload.photo, {
    yaw: startYaw - ((deltaX / rect.width) * Math.max(pose.fov, 45)),
    pitch: startPitch + ((deltaY / rect.height) * 70),
    fov: pose.fov,
  });
  renderViewer();
  renderCollectionViewer();
}

function stopViewerDrag(event) {
  if (!state.viewerDrag) return;
  const { canvas, pointerId } = state.viewerDrag;
  if (!event || event.pointerId === pointerId) {
    canvas.classList.remove("is-dragging");
    if (canvas.releasePointerCapture && pointerId != null) {
      try {
        canvas.releasePointerCapture(pointerId);
      } catch (_error) {
        // Ignore release errors from detached pointers.
      }
    }
    state.viewerDrag = null;
  }
}

function handleViewerWheel(event) {
  const canvas = event.currentTarget;
  const payload = activeViewerPayloadForCanvas(canvas);
  if (!payload) return;
  event.preventDefault();
  const pose = currentViewerPose(payload.photo);
  const scale = event.deltaY < 0 ? 0.9 : 1.1;
  applyViewerPose(payload.photo, {
    yaw: pose.yaw,
    pitch: pose.pitch,
    fov: pose.fov * scale,
  });
  renderViewer();
  renderCollectionViewer();
}

function handleDocumentClick(event) {
  if (!event.target.closest(".app-select")) {
    closeCustomSelect();
  }
  if (
    state.pendingAreaMenuPhotoId != null &&
    !event.target.closest(".queue-area-picker")
  ) {
    closePendingAreaMenu();
    renderPhotos();
  }
  if (!state.mapAreaMenuOpen) return;
  if (event.target.closest(".area-picker")) return;
  state.mapAreaMenuOpen = false;
  setHoverSuppressed(false);
  renderMap();
}

function handleCustomSelectClick(event) {
  const trigger = event.target.closest(".app-select-trigger");
  if (trigger) {
    const shell = trigger.closest(".app-select");
    if (!shell) return;
    const selectId = shell.dataset.customSelectId;
    const nextOpen = state.openCustomSelectId !== selectId;
    closeCustomSelect();
    if (nextOpen) {
      shell.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      state.openCustomSelectId = selectId;
    }
    return;
  }

  const option = event.target.closest(".app-select-option");
  if (!option) return;
  const shell = option.closest(".app-select");
  const select = [...document.querySelectorAll("select.native-select-hidden")].find(
    (item) => item.dataset.customSelectId === shell?.dataset.customSelectId,
  );
  if (!select) return;
  const nextValue = option.dataset.selectOptionValue || "";
  if (select.value !== nextValue) {
    select.value = nextValue;
    syncCustomSelect(select);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  } else {
    syncCustomSelect(select);
  }
  closeCustomSelect(select.dataset.customSelectId);
}

async function bootstrap() {
  try {
    elements.busyOverlay.hidden = true;
    document.body.classList.remove("is-busy");
    state.busyDepth = 0;
    setHoverSuppressed(false);
    ensureCustomSelect(elements.projectSelect);
    ensureCustomSelect(elements.photoFilter);
    renderPendingHeader();
    handlePendingViewChange();
    handleMapVisibilityChange();
    handleMapLabelToggleChange();
    ensureBridge();
    try {
      await loadAppInfo();
    } catch (_error) {
      state.appInfo = null;
    }
    try {
      await loadSmartSettings();
    } catch (_error) {
      state.smartSettings = null;
    }
    await loadProjects();
    await maybeBootstrapFromNetwork();
  } catch (error) {
    setStatus(error.message, true);
  }
}


elements.appModalForm.addEventListener("submit", (event) => {
  event.preventDefault();
  closeAppModal({
    accepted: true,
    text: elements.appModalTextInput.value.trim(),
    color: elements.appModalColorInput.value,
  });
});
elements.appModal.querySelectorAll("[data-modal-cancel]").forEach((item) => {
  item.addEventListener("click", () => closeAppModal(null));
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.appModal.hidden) {
    closeAppModal(null);
  }
});

elements.projectForm.addEventListener("submit", (event) => {
  createProject(event).catch((error) => setStatus(error.message, true));
});
elements.projectSelect.addEventListener("change", () => {
  syncCustomSelect(elements.projectSelect);
  state.currentProjectId = Number(elements.projectSelect.value) || null;
  state.selectedOverlayId = null;
  queueMapRefit();
  resetDrawArea();
  state.collapsedProcessedGroups = new Set();
  state.seenProcessedGroups = new Set();
  refreshProjectData().catch((error) => setStatus(error.message, true));
});
elements.refreshButton.addEventListener("click", () => {
  refreshProjectData().catch((error) => setStatus(error.message, true));
});
elements.deleteProjectButton.addEventListener("click", () => {
  deleteCurrentProject().catch((error) => setStatus(error.message, true));
});
elements.overlayImportButton.addEventListener("click", () => {
  importOverlay().catch((error) => setStatus(error.message, true));
});
document.getElementById("map-overlay-select").addEventListener("change", (event) => {
  state.selectedOverlayId = Number(event.target.value) || null;
  renderMap();
});
elements.overlayWorkspace.addEventListener("click", (event) => {
  const button = event.target.closest("[data-overlay-action]");
  const action = button?.dataset.overlayAction;
  if (!action) return;
  if (action === "replace" || action === "reimport") {
    importOverlay().catch((error) => setStatus(error.message, true));
    return;
  }
  const overlayId = Number(button.dataset.overlayId) || null;
  if (action === "rename" && overlayId) {
    renameOverlay(overlayId).catch((error) => setStatus(error.message, true));
    return;
  }
  if (action === "delete" && overlayId) {
    deleteOverlay(overlayId).catch((error) => setStatus(error.message, true));
    return;
  }
  if (action === "open-map") {
    setTab("map");
    maybeRefreshMapForTab("map");
  }
});
elements.renameButton.addEventListener("click", () => {
  runRename().catch((error) => setStatus(error.message, true));
});
elements.rollbackButton.addEventListener("click", () => {
  rollbackLastRun().catch((error) => setStatus(error.message, true));
});
elements.sharedNamingSaveButton.addEventListener("click", () => {
  saveSharedNamingSettings().catch((error) => setStatus(error.message, true));
});
elements.sharedNamingTestButton.addEventListener("click", () => {
  testSharedNamingConnection().catch((error) => setStatus(error.message, true));
});
elements.sharedNamingBackfillButton.addEventListener("click", () => {
  runSharedNamingBackfill().catch((error) => setStatus(error.message, true));
});
elements.areaSyncNowButton.addEventListener("click", () => {
  runAreaSyncNow().catch((error) => setStatus(error.message, true));
});
elements.modeToggleButton.addEventListener("click", () => {
  toggleUiMode().catch((error) => setStatus(error.message, true));
});
elements.smartImportButton.addEventListener("click", () => {
  runSmartImport().catch((error) => setStatus(error.message, true));
});
elements.smartExportButton.addEventListener("click", () => {
  runSmartExport().catch((error) => setStatus(error.message, true));
});
elements.smartSettingsSaveButton.addEventListener("click", () => {
  saveSmartSettings().catch((error) => setStatus(error.message, true));
});
elements.smartFtpTestButton.addEventListener("click", () => {
  testSmartFtp().catch((error) => setStatus(error.message, true));
});
elements.smartProgressCloseButton.addEventListener("click", () => {
  elements.smartProgressModal.hidden = true;
});
elements.drawAreaButton.addEventListener("click", startDrawArea);
elements.addAreaButton.addEventListener("click", () => {
  addArea().catch((error) => setStatus(error.message, true));
});
elements.addBlankAreaButton.addEventListener("click", () => {
  addBlankArea().catch((error) => setStatus(error.message, true));
});
elements.importPhotosButton.addEventListener("click", async () => {
  try {
    if (usingDesktopBridge()) {
      const paths = await pickPaths("photos");
      await importPhotos(paths);
    } else {
      const files = await chooseBrowserFiles(elements.photoFileInput);
      await importPhotoFiles(files);
    }
  } catch (error) {
    setStatus(error.message, true);
  }
});
elements.importFolderButton.addEventListener("click", async () => {
  try {
    if (usingDesktopBridge()) {
      const paths = await pickPaths("photo-folder");
      await importPhotos(paths);
    } else {
      const files = await chooseBrowserFiles(elements.photoFolderInput);
      await importPhotoFiles(files);
    }
  } catch (error) {
    setStatus(error.message, true);
  }
});
elements.createArchiveFolderButton.addEventListener("click", () => {
  createArchiveFolder().catch((error) => setStatus(error.message, true));
});
elements.archiveSelectedButton.addEventListener("click", () => {
  archiveSelected().catch((error) => setStatus(error.message, true));
});
elements.createCollectionButton.addEventListener("click", () => {
  createCollection().catch((error) => setStatus(error.message, true));
});
elements.addSelectedToCollectionButton.addEventListener("click", () => {
  addSelectedToCollection().catch((error) => setStatus(error.message, true));
});
elements.exportCollectionCsvButton.addEventListener("click", () => {
  exportCollection("csv").catch((error) => setStatus(error.message, true));
});
elements.exportCollectionPdfButton.addEventListener("click", () => {
  exportCollection("pdf").catch((error) => setStatus(error.message, true));
});
elements.saveViewerStateButton.addEventListener("click", () => {
  saveViewerState().catch((error) => setStatus(error.message, true));
});
elements.addViewerTagButton.addEventListener("click", () => {
  addViewerTag().catch((error) => setStatus(error.message, true));
});
elements.addAnnotationButton.addEventListener("click", () => {
  addAnnotation().catch((error) => setStatus(error.message, true));
});
elements.addIssueButton.addEventListener("click", () => {
  addIssue().catch((error) => setStatus(error.message, true));
});
elements.addNoteButton.addEventListener("click", () => {
  addNote().catch((error) => setStatus(error.message, true));
});
elements.addHotspotButton.addEventListener("click", () => {
  addHotspot().catch((error) => setStatus(error.message, true));
});
elements.viewerFullscreenButton.addEventListener("click", () => {
  toggleViewerFullscreen().catch((error) => setStatus(error.message, true));
});
elements.viewerOpenFileButton.addEventListener("click", () => {
  openSelectedViewerPath("open").catch((error) => setStatus(error.message, true));
});
elements.viewerOpenFolderButton.addEventListener("click", () => {
  openSelectedViewerPath("folder").catch((error) => setStatus(error.message, true));
});
elements.viewerRevealButton.addEventListener("click", () => {
  openSelectedViewerPath("reveal").catch((error) => setStatus(error.message, true));
});
elements.viewerOpenMapButton.addEventListener("click", openViewerPhotoOnMap);
elements.viewerPrevButton.addEventListener("click", () => {
  stepViewer(-1).catch((error) => setStatus(error.message, true));
});
elements.viewerNextButton.addEventListener("click", () => {
  stepViewer(1).catch((error) => setStatus(error.message, true));
});
elements.selectAllPendingButton.addEventListener("click", () => {
  selectAllRows(filteredPhotos());
});
elements.removeSelectedPendingButton.addEventListener("click", () => {
  removeSelected(pendingPhotos()).catch((error) => setStatus(error.message, true));
});
elements.selectAllProcessedButton.addEventListener("click", () => {
  selectAllRows(processedPhotos());
});
elements.removeSelectedProcessedButton.addEventListener("click", () => {
  removeSelected(processedPhotos()).catch((error) => setStatus(error.message, true));
});
elements.photoFilter.addEventListener("change", () => {
  syncCustomSelect(elements.photoFilter);
  renderPhotos();
});
elements.pendingSearch.addEventListener("input", handlePendingViewChange);
elements.pendingShowOriginalToggle.addEventListener("change", handlePendingViewChange);
elements.pendingShowDateToggle.addEventListener("change", handlePendingViewChange);
elements.pendingShowProposedToggle.addEventListener("change", handlePendingViewChange);
elements.areasTable.addEventListener("click", (event) => {
  handleAreaAction(event).catch((error) => setStatus(error.message, true));
});
elements.areasTable.addEventListener("change", (event) => {
  handleAreaAction(event).catch((error) => setStatus(error.message, true));
});
elements.photosTable.addEventListener("click", handlePhotoSelection);
elements.processedTable.addEventListener("click", handlePhotoSelection);
elements.archiveFoldersList.addEventListener("click", handleArchiveClick);
elements.archivePhotosTable.addEventListener("click", handleArchiveClick);
elements.collectionsList.addEventListener("click", handleCollectionsClick);
elements.collectionPhotosTable.addEventListener("click", handleCollectionsClick);
elements.collectionMapSvg.addEventListener("click", handleCollectionsClick);
elements.viewerOverlay.addEventListener("click", handleViewerOverlayClick);
elements.collectionViewerOverlay.addEventListener("click", handleViewerOverlayClick);
[
  elements.viewerCanvas,
  elements.collectionViewerCanvas,
].forEach((canvas) => {
  canvas.addEventListener("pointerdown", handleViewerPointerDown);
  canvas.addEventListener("wheel", handleViewerWheel, { passive: false });
});
elements.mapDetail.addEventListener("click", handleMapDetailClick);
elements.mapDetail.addEventListener("input", handleMapDetailInput);
elements.mapDetail.addEventListener("change", handleMapDetailInput);
elements.mapDetail.addEventListener("focusin", handleMapDetailFocusIn);
elements.mapDetail.addEventListener("focusout", handleMapDetailFocusOut);
document.addEventListener("click", handleDocumentClick);
document.addEventListener("click", handleCustomSelectClick);
document.addEventListener("fullscreenchange", renderViewer);
elements.mapLabelsToggle.addEventListener("change", handleMapLabelToggleChange);
elements.mapOriginalLabelToggle.addEventListener("change", handleMapLabelToggleChange);
elements.mapProposedLabelToggle.addEventListener("change", handleMapLabelToggleChange);
elements.mapShowProcessedToggle.addEventListener("change", handleMapVisibilityChange);
elements.zoomResetButton.addEventListener("click", () => {
  resetMapView();
});
window.addEventListener("pointermove", handleViewerPointerMove);
window.addEventListener("pointerup", stopViewerDrag);
window.addEventListener("pointercancel", stopViewerDrag);

elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    setTab(tab.dataset.tab);
  });
});

document.querySelectorAll("[data-review-mode]").forEach((button) => {
  button.addEventListener("click", () => setReviewMode(button.dataset.reviewMode));
});
document.querySelectorAll("[data-library-mode]").forEach((button) => {
  button.addEventListener("click", () => setLibraryMode(button.dataset.libraryMode));
});
document.querySelectorAll("[data-system-mode]").forEach((button) => {
  button.addEventListener("click", () => setSystemMode(button.dataset.systemMode));
});
["runs"].forEach((name) => {
  const toggle = document.getElementById(`process-${name}-toggle`);
  if (toggle) {
    toggle.addEventListener("click", () => {
      const section = document.querySelector(`[data-process-section="${name}"]`);
      setProcessSection(name, section ? section.hidden : true);
    });
  }
});

if (elements.dropzone) {
  ["dragenter", "dragover"].forEach((eventName) => {
    elements.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      elements.dropzone.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    elements.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      elements.dropzone.classList.remove("is-over");
    });
  });
  elements.dropzone.addEventListener("drop", (event) => {
    if (usingDesktopBridge()) {
      const paths = extractDroppedPaths(event);
      importPhotos(paths).catch((error) => setStatus(error.message, true));
      return;
    }
    importPhotoFiles([...event.dataTransfer.files]).catch((error) => setStatus(error.message, true));
  });
}

bootstrap();
