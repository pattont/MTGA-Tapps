/**
 * Card motion (pure, allocation-free): exponential smoothing toward the
 * layout target, a small arc while a card travels, and where a newly
 * appearing card should fly in from.
 */
import type { BoardState } from '../reducer';
import { STACK_SCALE, STACK_ANCHOR_Y, handY, seatHandScale } from '../layout';
import type { CardPlacement, Layout, PilePlacement, PileZone } from '../layout';

export interface Pose {
  x: number;
  y: number;
  z: number;
  rotZ: number;
  rotY: number;
  scale: number;
}

/** Settling speed (1/s): ~95% of the way in 0.25 s. */
export const MOTION_RATE = 12;
export const POSITION_EPSILON = 0.002;
export const ANGLE_EPSILON = 0.002;
/** Extra height while traveling, per unit of remaining distance (capped). */
export const ARC_PER_UNIT = 0.12;
export const ARC_MAX = 0.6;

/** Fraction of the remaining distance to cover this frame (frame-rate independent). */
export function dampFactor(deltaSeconds: number, rate = MOTION_RATE): number {
  const dt = Math.min(Math.max(deltaSeconds, 0), 0.1);
  return 1 - Math.exp(-rate * dt);
}

export function copyPose(from: Pose, to: Pose): Pose {
  to.x = from.x;
  to.y = from.y;
  to.z = from.z;
  to.rotZ = from.rotZ;
  to.rotY = from.rotY;
  to.scale = from.scale;
  return to;
}

export function poseOf(p: CardPlacement): Pose {
  return { x: p.x, y: p.y, z: p.z, rotZ: p.rotZ, rotY: p.rotY, scale: p.scale };
}

/**
 * Moves `current` toward `target` in place. Returns true once every channel
 * is within epsilon (and snaps it exactly onto the target).
 */
export function stepPose(current: Pose, target: Pose, alpha: number): boolean {
  current.x += (target.x - current.x) * alpha;
  current.y += (target.y - current.y) * alpha;
  current.z += (target.z - current.z) * alpha;
  current.rotZ += (target.rotZ - current.rotZ) * alpha;
  current.rotY += (target.rotY - current.rotY) * alpha;
  current.scale += (target.scale - current.scale) * alpha;
  const settled =
    Math.abs(target.x - current.x) < POSITION_EPSILON &&
    Math.abs(target.y - current.y) < POSITION_EPSILON &&
    Math.abs(target.z - current.z) < POSITION_EPSILON &&
    Math.abs(target.rotZ - current.rotZ) < ANGLE_EPSILON &&
    Math.abs(target.rotY - current.rotY) < ANGLE_EPSILON &&
    Math.abs(target.scale - current.scale) < POSITION_EPSILON;
  if (settled) copyPose(target, current);
  return settled;
}

/** A viewer position (the perspective camera), or null for a straight-down orthographic view. */
export interface Viewer {
  x: number;
  y: number;
  z: number;
}

/** Cards are never stretched beyond this, however shallow the view. */
export const MAX_STRETCH = 2.5;

/**
 * How much the tilted camera foreshortens the table plane at a point: the
 * ratio of the view ray's length to its drop, 1 straight down and larger at a
 * shallower angle (the far edge of a filled frame at the table tilt sits near
 * 1.5). A flat card scaled by this along the table's depth projects at its
 * true proportions, which is what the meshes do.
 */
export function depthStretch(viewer: Viewer | null, x: number, y: number, z: number): number {
  if (!viewer) return 1;
  const drop = viewer.z - z;
  if (drop <= 1e-6) return 1;
  const length = Math.hypot(viewer.x - x, viewer.y - y, drop);
  return Math.min(MAX_STRETCH, Math.max(1, length / drop));
}

/**
 * Local x/y scales that stretch a card `k` times along world y once it has
 * turned by `rotZ` (exact at right angles: an untapped card stretches along
 * its own height, a tapped one along its width).
 */
export function stretchedScale(scale: number, k: number, rotZ: number, out: { x: number; y: number }): { x: number; y: number } {
  const s = Math.sin(rotZ);
  const c = Math.cos(rotZ);
  out.x = scale * (1 + (k - 1) * s * s);
  out.y = scale * (1 + (k - 1) * c * c);
  return out;
}

/** Arc height for a card still `distance` units from its destination. */
export function arcLift(distance: number): number {
  return Math.min(ARC_MAX, distance * ARC_PER_UNIT);
}

export function planarDistance(a: Pose, b: Pose): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function pilePoint(piles: readonly PilePlacement[], seat: number, zone: PileZone): Pose | null {
  const pile = piles.find((p) => p.seat === seat && p.zone === zone);
  return pile ? { x: pile.x, y: pile.y, z: 0.3, rotZ: pile.rotZ, rotY: Math.PI, scale: pile.scale } : null;
}

/**
 * Where a card that just appeared should start. `known` returns the current
 * pose of another mesh (for abilities rising from their source permanent).
 */
export function spawnPose(
  placement: CardPlacement,
  state: BoardState,
  layout: Pick<Layout, 'piles' | 'table'>,
  known: (obj: string) => Pose | null,
): Pose {
  const { piles, table } = layout;
  const target = poseOf(placement);
  const drop: Pose = { ...target, z: target.z + 0.5 };
  const event = state.lastEvent;
  if (!event) return drop;
  if (event.kind === 'move' && event.obj === placement.obj) {
    const owner = event.owner;
    const playerSide = owner === state.playerSeat ? -1 : 1;
    switch (event.from) {
      case 'library':
        return pilePoint(piles, owner, 'library') ?? drop;
      case 'graveyard':
      case 'exile':
      case 'command': {
        const pose = pilePoint(piles, owner, event.from);
        return pose ? { ...pose, rotY: target.rotY } : drop;
      }
      case 'hand': {
        const scale = seatHandScale(table, playerSide > 0);
        return { x: 0, y: -playerSide * handY(scale, playerSide > 0), z: 0.4, rotZ: target.rotZ, rotY: target.rotY, scale };
      }
      case 'stack':
        return { x: table.stackX, y: STACK_ANCHOR_Y, z: 0.9, rotZ: target.rotZ, rotY: target.rotY, scale: STACK_SCALE };
      default:
        return { ...target, z: target.z + 0.8, scale: target.scale * 0.6 };
    }
  }
  if (event.kind === 'stack_push' && placement.obj === `stack:${event.stack_id}` && event.obj) {
    const source = known(event.obj);
    if (source) return { ...source, z: source.z + 0.2, rotY: target.rotY, scale: source.scale };
  }
  return drop;
}
