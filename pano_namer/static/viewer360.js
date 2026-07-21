// WebGL 360 viewer bridge built on Photo Sphere Viewer v5.
//
// This ES module wraps PSV (which is ESM-only) and exposes a small classic
// global, window.PanoViewer360, so the non-module app.js can drive it. All
// angles crossing this boundary are in DEGREES to match how the backend
// stores yaw/pitch/north_offset and how the old canvas viewer worked; PSV
// works in radians / a 0-100 zoom scale internally, converted here.

import { Viewer, utils } from "@photo-sphere-viewer/core";
import { MarkersPlugin } from "@photo-sphere-viewer/markers-plugin";
import { CompassPlugin } from "@photo-sphere-viewer/compass-plugin";

const MIN_FOV = 35;
const MAX_FOV = 110;

const deg = (value) => `${Number(value) || 0}deg`;
const radToDeg = (rad) => (rad * 180) / Math.PI;

// PSV zoom is 0 (=maxFov, widest) .. 100 (=minFov, tightest).
function fovToZoom(fov) {
  const clamped = Math.min(MAX_FOV, Math.max(MIN_FOV, Number(fov) || 75));
  return ((MAX_FOV - clamped) / (MAX_FOV - MIN_FOV)) * 100;
}
function zoomToFov(zoom) {
  return MAX_FOV - (Number(zoom) || 0) / 100 * (MAX_FOV - MIN_FOV);
}

function mount(container, options = {}) {
  let viewer;
  try {
    viewer = new Viewer({
      container,
      navbar: false,
      minFov: MIN_FOV,
      maxFov: MAX_FOV,
      defaultZoomLvl: fovToZoom(options.fov || 75),
      loadingtxt: "Loading 360…",
      mousewheelCtrlKey: false,
      plugins: [
        [MarkersPlugin, {}],
        [
          CompassPlugin,
          {
            size: "90px",
            hotspots: [],
          },
        ],
      ],
    });
  } catch (err) {
    // WebGL unavailable (rare VM/driver case): fail soft with a message
    // instead of throwing across the bridge and breaking the app.
    container.innerHTML =
      '<div class="viewer-360-fallback">3D viewer unavailable on this device (no WebGL).</div>';
    return null;
  }

  const markers = viewer.getPlugin(MarkersPlugin);
  const compass = viewer.getPlugin(CompassPlugin);
  let northOffset = 0;

  function markerToConfig(item) {
    const kind = item.kind || "annotation";
    const palette = {
      annotation: "#f4c542",
      issue: "#cf4f4f",
      hotspot: "#17b0c4",
    };
    const color = item.color || palette[kind] || "#f4c542";
    const config = {
      id: item.id,
      position: { yaw: deg(item.yaw), pitch: deg(item.pitch) },
      data: { kind, refId: item.refId, targetPhotoId: item.targetPhotoId },
      tooltip: item.tooltip ? { content: item.tooltip } : undefined,
    };
    if (kind === "hotspot") {
      config.html = `<div class="psv-hotspot" style="--dot:${color}"></div>`;
      config.size = { width: 34, height: 34 };
      config.anchor = "center center";
    } else {
      config.circle = 12;
      config.style = { color, cursor: "pointer" };
    }
    return config;
  }

  const handle = {
    setPanorama(url, pose = {}) {
      northOffset = Number(pose.northOffset) || 0;
      return viewer
        .setPanorama(url, {
          position: { yaw: deg(pose.yaw), pitch: deg(pose.pitch) },
          zoom: fovToZoom(pose.fov || 75),
          transition: false,
          showLoader: true,
        })
        .then(() => {
          compass.setHotspots([{ yaw: deg(northOffset), color: "#ff5252" }]);
        })
        .catch(() => {});
    },
    setMarkers(list) {
      markers.setMarkers((list || []).map(markerToConfig));
    },
    clearMarkers() {
      markers.clearMarkers();
    },
    getPosition() {
      const pos = viewer.getPosition();
      return {
        yaw: radToDeg(pos.yaw),
        pitch: radToDeg(pos.pitch),
        fov: zoomToFov(viewer.getZoomLevel()),
      };
    },
    enterFullscreen() {
      viewer.enterFullscreen();
    },
    toggleFullscreen() {
      viewer.toggleFullscreen();
    },
    isFullscreen() {
      return viewer.isFullscreenEnabled();
    },
    resize() {
      viewer.autoSize();
    },
    destroy() {
      viewer.destroy();
    },
    on(eventName, callback) {
      if (eventName === "click") {
        viewer.addEventListener("click", ({ data }) => {
          if (data.rightclick) return;
          callback({
            yaw: radToDeg(data.yaw),
            pitch: radToDeg(data.pitch),
          });
        });
      } else if (eventName === "select-marker") {
        markers.addEventListener("select-marker", ({ marker }) => {
          callback({ id: marker.id, data: marker.config.data || {} });
        });
      }
    },
  };
  return handle;
}

window.PanoViewer360 = { mount, MIN_FOV, MAX_FOV };
// Late-loading signal: app.js (a classic script that runs before deferred
// modules) awaits this event before first mounting a viewer.
window.dispatchEvent(new Event("panoviewer360ready"));
