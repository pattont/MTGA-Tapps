/**
 * Zoom and pan for the 3D table, as a window into the fitted view. The camera
 * rig applies it with `camera.setViewOffset`, which renders that window at the
 * canvas's full resolution: zoomed cards get real extra pixels, the only way
 * to read them on a 1x screen. Raycasting, labels and arrows all go through
 * the camera's projection, so they follow without any change.
 *
 * The window is kept as a zoom factor and a centre (fractions of the view), so
 * it survives a canvas resize; it never leaves the fitted view.
 */

export const MAX_ZOOM = 4;
/** Wheel zoom per pixel of scroll (exponential, so each notch scales alike). */
export const WHEEL_ZOOM_RATE = 0.0015;
/** Keyboard +/- zoom step. */
export const KEY_ZOOM_STEP = 1.25;
/** Below this the view snaps back to the whole table. */
const SNAP_ZOOM = 1.02;

export interface ViewWindow {
  x: number;
  y: number;
  width: number;
  height: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export class ViewZoom {
  zoom = 1;
  /** Centre of the visible window as fractions of the full view. */
  cx = 0.5;
  cy = 0.5;
  private readonly listeners = new Set<() => void>();

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  get zoomed(): boolean {
    return this.zoom > 1;
  }

  /** The visible window, in the CSS pixels of a width × height view. */
  window(width: number, height: number): ViewWindow {
    const w = width / this.zoom;
    const h = height / this.zoom;
    return { x: this.cx * width - w / 2, y: this.cy * height - h / 2, width: w, height: h };
  }

  /** Scales the zoom by `factor`, keeping the view point under (px, py) in place. */
  zoomAt(factor: number, px: number, py: number, width: number, height: number): void {
    if (!(width > 0 && height > 0) || !Number.isFinite(factor)) return;
    let next = clamp(this.zoom * factor, 1, MAX_ZOOM);
    if (next < SNAP_ZOOM) next = 1;
    if (next === this.zoom) return;
    const before = this.window(width, height);
    const fx = before.x + px / this.zoom;
    const fy = before.y + py / this.zoom;
    this.zoom = next;
    this.place(fx - px / next, fy - py / next, width, height);
  }

  /** Scales the zoom by `factor` about the centre of the visible window (keyboard +/-). */
  zoomBy(factor: number): void {
    if (!Number.isFinite(factor)) return;
    let next = clamp(this.zoom * factor, 1, MAX_ZOOM);
    if (next < SNAP_ZOOM) next = 1;
    if (next === this.zoom) return;
    this.zoom = next;
    const edge = 0.5 / next;
    this.cx = next > 1 ? clamp(this.cx, edge, 1 - edge) : 0.5;
    this.cy = next > 1 ? clamp(this.cy, edge, 1 - edge) : 0.5;
    this.notify();
  }

  /** Moves the view with a drag of (dx, dy) screen pixels. */
  panBy(dx: number, dy: number, width: number, height: number): void {
    if (!this.zoomed || !(width > 0 && height > 0)) return;
    const win = this.window(width, height);
    this.place(win.x - dx / this.zoom, win.y - dy / this.zoom, width, height);
  }

  reset(): void {
    if (!this.zoomed && this.cx === 0.5 && this.cy === 0.5) return;
    this.zoom = 1;
    this.cx = 0.5;
    this.cy = 0.5;
    this.notify();
  }

  private place(x: number, y: number, width: number, height: number): void {
    const w = width / this.zoom;
    const h = height / this.zoom;
    this.cx = this.zoomed ? (clamp(x, 0, width - w) + w / 2) / width : 0.5;
    this.cy = this.zoomed ? (clamp(y, 0, height - h) + h / 2) / height : 0.5;
    this.notify();
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}
