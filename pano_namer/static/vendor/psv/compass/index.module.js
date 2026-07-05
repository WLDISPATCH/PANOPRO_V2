/*!
 * Photo Sphere Viewer / Compass Plugin 5.14.3
 * @copyright 2015-2026 Damien "Mistic" Sorel
 * @licence MIT (https://opensource.org/licenses/MIT)
 */

// src/CompassPlugin.ts
import { AbstractConfigurablePlugin, events, utils } from "@photo-sphere-viewer/core";

// src/compass.svg
var compass_default = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="50" fill="rgba(61, 61, 61, .5)"/><path fill="rgba(255, 255, 255, .7)" d="M50 97.1A47 47 0 0 1 32.5 6.5l.8 1.8a45 45 0 1 0 33.4 0l.8-1.8A47 47 0 0 1 50 97Zm0-42a5 5 0 1 1 5-5 5 5 0 0 1-5 5Zm4-41.7h-1.6a.4.4 0 0 1-.4-.2l-4.6-7.7V13a.3.3 0 0 1-.3.3h-1.6a.3.3 0 0 1-.3-.3V1.8a.3.3 0 0 1 .3-.3h1.6a.3.3 0 0 1 .4.2L52 9.4V1.8a.3.3 0 0 1 .3-.3H54c.2 0 .3 0 .3.3V13c0 .2-.1.3-.3.3Z"/></svg>\n';

// src/components/CompassComponent.ts
import { AbstractComponent, SYSTEM } from "@photo-sphere-viewer/core";
import { MathUtils } from "three";
var HOTSPOT_SIZE_RATIO = 1 / 40;
var CompassComponent = class extends AbstractComponent {
  constructor(viewer, plugin) {
    super(viewer, {});
    this.plugin = plugin;
    this.state = {
      visible: true,
      mouse: null,
      mousedown: false,
      markers: []
    };
    this.background = document.createElement("div");
    this.canvas = document.createElement("canvas");
    this.container.appendChild(this.background);
    this.container.appendChild(this.canvas);
    this.container.addEventListener("mouseenter", this);
    this.container.addEventListener("mouseleave", this);
    this.container.addEventListener("mousemove", this);
    this.container.addEventListener("mousedown", this);
    this.container.addEventListener("mouseup", this);
    this.container.addEventListener("touchstart", this);
    this.container.addEventListener("touchmove", this);
    this.container.addEventListener("touchend", this);
    this.applyConfig();
    this.hide();
  }
  get config() {
    return this.plugin.config;
  }
  handleEvent(e) {
    if (!this.config.navigation) {
      return;
    }
    switch (e.type) {
      case "mouseenter":
      case "mousemove":
      case "touchmove":
        this.state.mouse = e.changedTouches?.[0] || e;
        if (this.state.mousedown) {
          this.click();
        } else {
          this.update();
        }
        e.stopPropagation();
        e.preventDefault();
        break;
      case "mousedown":
      case "touchstart":
        this.state.mousedown = true;
        e.stopPropagation();
        e.preventDefault();
        break;
      case "mouseup":
      case "touchend":
        this.state.mouse = e.changedTouches?.[0] || e;
        this.state.mousedown = false;
        this.click();
        if (e.changedTouches) {
          this.state.mouse = null;
          this.update();
        }
        e.stopPropagation();
        e.preventDefault();
        break;
      case "mouseleave":
        this.state.mouse = null;
        this.state.mousedown = false;
        this.update();
        break;
      default:
        break;
    }
  }
  destroy() {
    this.canvas.width = 0;
    this.canvas.height = 0;
    super.destroy();
  }
  applyConfig() {
    this.container.className = `psv-compass psv-compass--${this.config.position.join("-")}`;
    if (this.config.className) {
      this.container.classList.add(this.config.className);
    }
    this.background.innerHTML = this.config.backgroundSvg;
    this.container.style.width = this.config.size;
    this.container.style.marginTop = this.config.position[0] === "center" ? `calc(-${this.config.size} / 2)` : "";
    this.container.style.marginLeft = this.config.position[1] === "center" ? `calc(-${this.config.size} / 2)` : "";
  }
  show() {
    super.show();
    this.update();
  }
  setMarkers(markers) {
    this.state.markers = markers;
    this.update();
  }
  /**
   * Updates the compass for current zoom and position
   */
  update() {
    if (!this.isVisible()) {
      return;
    }
    this.canvas.width = this.container.clientWidth * SYSTEM.pixelRatio;
    this.canvas.height = this.container.clientWidth * SYSTEM.pixelRatio;
    const context = this.canvas.getContext("2d");
    context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    const yaw = this.viewer.getPosition().yaw;
    const fov = MathUtils.degToRad(this.viewer.state.hFov);
    this.__drawCone(context, this.config.coneColor, yaw, fov);
    const mouseAngle = this.__getMouseAngle();
    if (mouseAngle !== null) {
      this.__drawCone(context, this.config.navigationColor, mouseAngle, fov);
    }
    this.state.markers.forEach((marker) => {
      this.__drawMarker(context, marker);
    });
    this.config.hotspots?.forEach((spot) => {
      if ("yaw" in spot && !("pitch" in spot)) {
        spot.pitch = 0;
      }
      const pos = this.viewer.dataHelper.cleanPosition(spot);
      this.__drawPoint(context, spot.color || this.config.hotspotColor, pos.yaw, pos.pitch);
    });
  }
  /**
   * Rotates the viewer depending on the position of the mouse on the compass
   */
  click() {
    const mouseAngle = this.__getMouseAngle();
    if (mouseAngle !== null) {
      this.viewer.rotate({
        yaw: mouseAngle,
        pitch: this.config.resetPitch ? this.viewer.config.defaultPitch : this.viewer.getPosition().pitch
      });
    }
  }
  /**
   * Draw a cone
   */
  __drawCone(context, color, yaw, fov) {
    const a1 = yaw - Math.PI / 2 - fov / 2;
    const a2 = a1 + fov;
    const c = this.canvas.width / 2;
    context.beginPath();
    context.moveTo(c, c);
    context.lineTo(c + Math.cos(a1) * c, c + Math.sin(a1) * c);
    context.arc(c, c, c, a1, a2, false);
    context.lineTo(c, c);
    context.fillStyle = color;
    context.fill();
  }
  /**
   * Draw a Marker
   */
  __drawMarker(context, marker) {
    let color = this.config.hotspotColor;
    if (typeof marker.data["compass"] === "string") {
      color = marker.data["compass"];
    }
    if (marker.isPoly()) {
      context.beginPath();
      marker.definition[0].forEach(([yaw, pitch], i) => {
        const a = yaw - Math.PI / 2;
        const d = (pitch + Math.PI / 2) / Math.PI;
        const c = this.canvas.width / 2;
        context[i === 0 ? "moveTo" : "lineTo"](c + Math.cos(a) * c * d, c + Math.sin(a) * c * d);
      });
      if (marker.type.startsWith("polygon")) {
        context.fillStyle = color;
        context.fill();
      } else {
        context.strokeStyle = color;
        context.lineWidth = Math.max(1, this.canvas.width * HOTSPOT_SIZE_RATIO / 2);
        context.stroke();
      }
    } else {
      const pos = marker.state.position;
      this.__drawPoint(context, color, pos.yaw, pos.pitch);
    }
  }
  /**
   * Draw a point
   */
  __drawPoint(context, color, yaw, pitch) {
    const a = yaw - Math.PI / 2;
    const d = (pitch + Math.PI / 2) / Math.PI;
    const c = this.canvas.width / 2;
    const r = Math.max(2, this.canvas.width * HOTSPOT_SIZE_RATIO);
    context.beginPath();
    context.ellipse(
      c + Math.cos(a) * c * d,
      c + Math.sin(a) * c * d,
      r,
      r,
      0,
      0,
      Math.PI * 2
    );
    context.fillStyle = color;
    context.fill();
  }
  /**
   * Gets the horizontal angle corresponding to the mouse position on the compass
   */
  __getMouseAngle() {
    if (!this.state.mouse) {
      return null;
    }
    const boundingRect = this.container.getBoundingClientRect();
    const mouseX = this.state.mouse.clientX - boundingRect.left - boundingRect.width / 2;
    const mouseY = this.state.mouse.clientY - boundingRect.top - boundingRect.width / 2;
    if (Math.sqrt(mouseX * mouseX + mouseY * mouseY) > boundingRect.width / 2) {
      return null;
    }
    return Math.atan2(mouseY, mouseX) + Math.PI / 2;
  }
};

// src/CompassPlugin.ts
var getConfig = utils.getConfigParser(
  {
    size: "120px",
    position: ["top", "left"],
    backgroundSvg: compass_default,
    coneColor: "rgba(255, 255, 255, 0.5)",
    navigation: true,
    resetPitch: false,
    navigationColor: "rgba(255, 0, 0, 0.2)",
    hotspots: [],
    hotspotColor: "rgba(0, 0, 0, 0.5)",
    className: null
  },
  {
    position: (position, { defValue }) => {
      return utils.cleanCssPosition(position, { allowCenter: true, cssOrder: true }) || defValue;
    }
  }
);
var _CompassPlugin = class _CompassPlugin extends AbstractConfigurablePlugin {
  static withConfig(config) {
    return [_CompassPlugin, config];
  }
  constructor(viewer, config) {
    super(viewer, config);
    this.component = new CompassComponent(this.viewer, this);
  }
  /**
   * @internal
   */
  init() {
    super.init();
    utils.checkStylesheet(this.viewer.container, "compass-plugin");
    this.markers = this.viewer.getPlugin("markers");
    this.viewer.addEventListener(events.RenderEvent.type, this);
    this.viewer.addEventListener(events.ReadyEvent.type, this, { once: true });
    if (this.markers) {
      this.markers.addEventListener("set-markers", this);
    }
  }
  /**
   * @internal
   */
  destroy() {
    this.viewer.removeEventListener(events.RenderEvent.type, this);
    this.viewer.removeEventListener(events.ReadyEvent.type, this);
    if (this.markers) {
      this.markers.removeEventListener("set-markers", this);
    }
    this.component.destroy();
    delete this.markers;
    super.destroy();
  }
  setOptions(options) {
    super.setOptions(options);
    this.component.applyConfig();
    this.component.update();
  }
  /**
   * @internal
   */
  handleEvent(e) {
    switch (e.type) {
      case events.ReadyEvent.type:
        this.component.show();
        break;
      case events.RenderEvent.type:
        this.component.update();
        break;
      case "set-markers":
        this.component.setMarkers(
          e.markers.filter((m) => m.data?.["compass"])
        );
        break;
    }
  }
  /**
   * Hides the compass
   */
  hide() {
    this.component.hide();
  }
  /**
   * Shows the compass
   */
  show() {
    this.component.show();
  }
  /**
   * Changes the hotspots on the compass
   */
  setHotspots(hotspots) {
    this.config.hotspots = hotspots;
    this.component.update();
  }
  /**
   * Removes all hotspots
   */
  clearHotspots() {
    this.setHotspots(null);
  }
};
_CompassPlugin.id = "compass";
_CompassPlugin.VERSION = "5.14.3";
_CompassPlugin.configParser = getConfig;
var CompassPlugin = _CompassPlugin;
export {
  CompassPlugin
};
//# sourceMappingURL=index.module.js.map