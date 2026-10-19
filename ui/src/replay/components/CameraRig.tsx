/**
 * Owns the perspective (`table`) and orthographic (`topdown`) cameras, fits
 * them to the canvas on resize, and eases between presets: the tilt flattens
 * while the field of view narrows, then the orthographic camera takes over.
 * A zoomed view (ViewZoom) renders a window of the fitted view at full
 * resolution through the camera's view offset.
 */
import { useFrame, useThree } from '@react-three/fiber';
import { useLayoutEffect, useMemo, useRef } from 'react';
import { OrthographicCamera, PerspectiveCamera } from 'three';
import type { ViewZoom } from '../scene/viewZoom';
import type { TableGeometry } from '../layout';
import type { CameraPreset } from '../prefs';
import {
  DEFAULT_MARGINS,
  applyOrthographic,
  applyPerspective,
  easeInOutCubic,
  fitOrthographic,
  fitPerspective,
} from '../scene/cameraFit';
import type { TableSize } from '../scene/cameraFit';

const MARGINS = DEFAULT_MARGINS;
export const CAMERA_TRANSITION_MS = 450;

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  } catch {
    return false;
  }
}

export function CameraRig({ preset, table, zoom }: { preset: CameraPreset; table: TableGeometry; zoom: ViewZoom }) {
  const set = useThree((s) => s.set);
  const get = useThree((s) => s.get);
  const invalidate = useThree((s) => s.invalidate);
  const width = useThree((s) => s.size.width);
  const height = useThree((s) => s.size.height);
  const cameras = useMemo(() => {
    const perspective = new PerspectiveCamera(40, 1, 1, 100);
    const orthographic = new OrthographicCamera(-1, 1, 1, -1, 1, 100);
    // R3F must not resize these: the rig fits them itself.
    Object.assign(perspective, { manual: true });
    Object.assign(orthographic, { manual: true });
    return { perspective, orthographic };
  }, []);
  const blend = preset === 'topdown' ? 1 : 0;
  const anim = useRef({ u: blend, from: blend, to: blend, start: 0 });
  // Reused every transition frame (useFrame paths do not allocate).
  const scratch = useRef({
    view: { width: 1, height: 1 },
    table: {
      width: table.width,
      depth: table.depth,
      handScale: table.handScale,
      opponentHandScale: table.opponentHandScale,
    } as TableSize,
    pose: fitPerspective(0, { width: 1, height: 1 }, MARGINS, table),
    frustum: fitOrthographic({ width: 1, height: 1 }, MARGINS, table),
  });

  const zoomRef = useRef(zoom);
  const apply = useRef((u: number) => {
    const { perspective, orthographic } = cameras;
    const { view, table: size, pose, frustum } = scratch.current;
    const camera = u >= 1 ? orthographic : perspective;
    if (u >= 1) applyOrthographic(orthographic, fitOrthographic(view, MARGINS, size, frustum));
    else applyPerspective(perspective, fitPerspective(u, view, MARGINS, size, pose), view);
    const z = zoomRef.current;
    if (z.zoomed) {
      const win = z.window(view.width, view.height);
      camera.setViewOffset(view.width, view.height, win.x, win.y, win.width, win.height);
    } else if (camera.view?.enabled) {
      camera.clearViewOffset();
    }
    if (get().camera !== camera) set({ camera });
  });

  useLayoutEffect(() => {
    zoomRef.current = zoom;
    return zoom.subscribe(() => {
      apply.current(anim.current.u);
      invalidate();
    });
  }, [zoom, invalidate]);

  useLayoutEffect(() => {
    const a = anim.current;
    a.from = a.u;
    a.to = blend;
    a.start = performance.now();
    if (prefersReducedMotion()) a.u = blend;
    scratch.current.view.width = width;
    scratch.current.view.height = height;
    scratch.current.table.width = table.width;
    scratch.current.table.depth = table.depth;
    scratch.current.table.handScale = table.handScale;
    scratch.current.table.opponentHandScale = table.opponentHandScale;
    apply.current(a.u);
    invalidate();
  }, [blend, width, height, table.width, table.depth, table.handScale, table.opponentHandScale, invalidate]);

  useFrame(() => {
    const a = anim.current;
    if (a.u === a.to) return;
    const p = (performance.now() - a.start) / CAMERA_TRANSITION_MS;
    a.u = p >= 1 ? a.to : a.from + (a.to - a.from) * easeInOutCubic(p);
    apply.current(a.u);
    invalidate();
  });

  return null;
}
