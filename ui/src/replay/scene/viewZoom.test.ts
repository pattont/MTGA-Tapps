import { describe, expect, it, vi } from 'vitest';
import { MAX_ZOOM, ViewZoom } from './viewZoom';

const W = 1000;
const H = 600;

describe('ViewZoom', () => {
  it('starts on the whole view', () => {
    const zoom = new ViewZoom();
    expect(zoom.zoomed).toBe(false);
    expect(zoom.window(W, H)).toEqual({ x: 0, y: 0, width: W, height: H });
  });

  it('keeps the point under the pointer in place', () => {
    const zoom = new ViewZoom();
    zoom.zoomAt(2, 250, 150, W, H);
    const win = zoom.window(W, H);
    expect(win.width).toBe(500);
    expect(win.x + 250 / 2).toBeCloseTo(250);
    expect(win.y + 150 / 2).toBeCloseTo(150);
    zoom.zoomAt(1.5, 400, 300, W, H);
    const before = { x: win.x + 400 / 2, y: win.y + 300 / 2 };
    const after = zoom.window(W, H);
    expect(after.x + 400 / 3).toBeCloseTo(before.x);
    expect(after.y + 300 / 3).toBeCloseTo(before.y);
  });

  it('stays inside the view at the edges', () => {
    const zoom = new ViewZoom();
    zoom.zoomAt(2, 0, 0, W, H);
    expect(zoom.window(W, H)).toMatchObject({ x: 0, y: 0 });
    zoom.panBy(-5000, -5000, W, H);
    const win = zoom.window(W, H);
    expect(win.x + win.width).toBeCloseTo(W);
    expect(win.y + win.height).toBeCloseTo(H);
  });

  it('pans opposite to the drag, scaled by the zoom', () => {
    const zoom = new ViewZoom();
    zoom.zoomAt(2, 500, 300, W, H);
    const before = zoom.window(W, H);
    zoom.panBy(100, 40, W, H);
    const after = zoom.window(W, H);
    expect(after.x).toBeCloseTo(before.x - 50);
    expect(after.y).toBeCloseTo(before.y - 20);
  });

  it('clamps to the maximum and snaps back to the whole view', () => {
    const zoom = new ViewZoom();
    zoom.zoomAt(100, 500, 300, W, H);
    expect(zoom.zoom).toBe(MAX_ZOOM);
    zoom.zoomAt(1 / 3.95, 500, 300, W, H);
    expect(zoom.zoom).toBe(1);
    expect([zoom.cx, zoom.cy]).toEqual([0.5, 0.5]);
  });

  it('zooms about the window centre from the keyboard and stays inside the view', () => {
    const zoom = new ViewZoom();
    zoom.zoomAt(2, 0, 0, W, H);
    zoom.zoomBy(1.5);
    expect(zoom.zoom).toBe(3);
    expect([zoom.cx, zoom.cy]).toEqual([0.25, 0.25]);
    zoom.zoomBy(1 / 3);
    expect(zoom.zoomed).toBe(false);
    // Zooming out from a corner pulls the window back inside the view.
    zoom.zoomAt(4, 0, 0, W, H);
    expect(zoom.window(W, H)).toMatchObject({ x: 0, y: 0, width: W / 4 });
    zoom.zoomBy(0.5);
    expect(zoom.window(W, H)).toMatchObject({ x: 0, y: 0, width: W / 2 });
    zoom.zoomBy(0.5);
    expect(zoom.zoomed).toBe(false);
    expect([zoom.cx, zoom.cy]).toEqual([0.5, 0.5]);
  });

  it('ignores panning at 1x and notifies on changes only', () => {
    const zoom = new ViewZoom();
    const listener = vi.fn();
    zoom.subscribe(listener);
    zoom.panBy(50, 50, W, H);
    zoom.reset();
    zoom.zoomAt(0.5, 10, 10, W, H);
    expect(listener).not.toHaveBeenCalled();
    zoom.zoomAt(2, 10, 10, W, H);
    zoom.reset();
    expect(listener).toHaveBeenCalledTimes(2);
    expect(zoom.zoomed).toBe(false);
  });
});
