/** World -> canvas pixel projection for DOM labels (pure, allocation-free). */
import { Vector3 } from 'three';
import type { Camera } from 'three';
import { sceneArrowShape } from './arrows';
import type { ArrowEnd, SceneArrow } from './arrows';
import type { SceneLabel } from './labels';

const scratch = new Vector3();

export interface ScreenPoint {
  x: number;
  y: number;
  /** False when the point is behind the camera or outside the clip volume in depth. */
  visible: boolean;
}

export function projectToScreen(
  camera: Camera,
  x: number,
  y: number,
  z: number,
  width: number,
  height: number,
  out: ScreenPoint,
): ScreenPoint {
  scratch.set(x, y, z).project(camera);
  out.x = ((scratch.x + 1) / 2) * width;
  out.y = ((1 - scratch.y) / 2) * height;
  out.visible = scratch.z > -1 && scratch.z < 1;
  return out;
}

/** Last values written to a label node, so unchanged frames build no strings. */
interface Written {
  x: number;
  y: number;
  align: string;
  opacity: string;
}

const written = new WeakMap<HTMLElement, Written>();

function writtenFor(node: HTMLElement): Written {
  let entry = written.get(node);
  if (!entry) {
    entry = { x: NaN, y: NaN, align: '', opacity: '' };
    written.set(node, entry);
  }
  return entry;
}

function setOpacity(node: HTMLElement, entry: Written, opacity: '0' | '1'): void {
  if (entry.opacity === opacity) return;
  entry.opacity = opacity;
  node.style.opacity = opacity;
}

/**
 * Moves each label element (children of `container`, in label order) to its
 * projected anchor. Runs every rendered frame, so it only builds a transform
 * string and touches the DOM when a label's rounded pixel position changes.
 */
export function positionLabels(
  container: HTMLElement,
  labels: readonly SceneLabel[],
  camera: Camera,
  size: { width: number; height: number },
  poseOf: (obj: string) => { x: number; y: number; z: number } | null,
  scratchPoint: ScreenPoint,
  /** Depth stretch of that mesh (motion.depthStretch): the label's y offset follows the card's edge. */
  stretchOf: (obj: string) => number = () => 1,
): void {
  const nodes = container.children;
  for (let i = 0; i < labels.length && i < nodes.length; i += 1) {
    const label = labels[i];
    const node = nodes[i] as HTMLElement;
    const entry = writtenFor(node);
    let { x, y, z } = label;
    if (label.obj) {
      const pose = poseOf(label.obj);
      if (!pose) {
        setOpacity(node, entry, '0');
        continue;
      }
      x += pose.x;
      y = y * stretchOf(label.obj) + pose.y;
      z += pose.z;
    }
    const p = projectToScreen(camera, x, y, z, size.width, size.height, scratchPoint);
    const px = Math.round(p.x);
    const py = Math.round(p.y);
    if (px !== entry.x || py !== entry.y || label.align !== entry.align) {
      entry.x = px;
      entry.y = py;
      entry.align = label.align;
      const shift = label.align === 'center' ? ' translateX(-50%)' : ' translateY(-50%)';
      node.style.transform = `translate(${px}px, ${py}px)${shift}`;
    }
    setOpacity(node, entry, p.visible ? '1' : '0');
  }
}

/** World point of a 3D arrow end, or null when that end is not on the table. */
export type WorldPointOf = (end: ArrowEnd) => { x: number; y: number; z: number } | null;
/** Canvas-pixel point of a DOM arrow end (stack preview card); false when absent. */
export type DomPointOf = (stackId: string, out: ScreenPoint) => boolean;

interface WrittenArrow {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
  visible: boolean;
}

const writtenArrows = new WeakMap<Element, WrittenArrow>();
const fromPoint: ScreenPoint = { x: 0, y: 0, visible: false };
const toPoint: ScreenPoint = { x: 0, y: 0, visible: false };

function endPoint(
  end: ArrowEnd,
  camera: Camera,
  size: { width: number; height: number },
  worldOf: WorldPointOf,
  domOf: DomPointOf,
  out: ScreenPoint,
): boolean {
  if (end.kind === 'stack') return domOf(end.stackId, out);
  const world = worldOf(end);
  if (!world) return false;
  projectToScreen(camera, world.x, world.y, world.z, size.width, size.height, out);
  return out.visible;
}

/**
 * Moves each arrow group (children of `container`, in arrow order) to its
 * projected endpoints. Like positionLabels it runs on rendered frames only and
 * rebuilds path strings only when a rounded endpoint actually moved.
 */
export function positionArrows(
  container: Element,
  arrows: readonly SceneArrow[],
  camera: Camera,
  size: { width: number; height: number },
  worldOf: WorldPointOf,
  domOf: DomPointOf,
): void {
  const nodes = container.children;
  for (let i = 0; i < arrows.length && i < nodes.length; i += 1) {
    const arrow = arrows[i];
    const node = nodes[i];
    let entry = writtenArrows.get(node);
    if (!entry) {
      // Arrow groups mount hidden (visibility="hidden") until first placed.
      entry = { sx: NaN, sy: NaN, tx: NaN, ty: NaN, visible: false };
      writtenArrows.set(node, entry);
    }
    const ok =
      endPoint(arrow.from, camera, size, worldOf, domOf, fromPoint) &&
      endPoint(arrow.to, camera, size, worldOf, domOf, toPoint);
    if (!ok) {
      if (entry.visible) {
        entry.visible = false;
        node.setAttribute('visibility', 'hidden');
      }
      continue;
    }
    if (!entry.visible) {
      entry.visible = true;
      node.removeAttribute('visibility');
    }
    const sx = Math.round(fromPoint.x);
    const sy = Math.round(fromPoint.y);
    const tx = Math.round(toPoint.x);
    const ty = Math.round(toPoint.y);
    if (sx === entry.sx && sy === entry.sy && tx === entry.tx && ty === entry.ty) continue;
    entry.sx = sx;
    entry.sy = sy;
    entry.tx = tx;
    entry.ty = ty;
    const shape = sceneArrowShape(sx, sy, tx, ty, { paired: arrow.paired, atCard: arrow.to.kind === 'obj' });
    const parts = node.children;
    for (let k = 0; k < parts.length; k += 1) {
      const part = parts[k];
      const role = part.getAttribute('data-part');
      if (role === 'head') part.setAttribute('points', shape.head);
      else if (role === 'reticle') {
        part.setAttribute('cx', String(tx));
        part.setAttribute('cy', String(ty));
      } else part.setAttribute('d', shape.d);
    }
  }
}
