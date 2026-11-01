/**
 * Animation targets for every card mesh. React sets targets when the layout
 * changes; one useFrame callback steps all unsettled cards toward their
 * targets and reports whether another frame is needed, so the demand-driven
 * canvas only renders while something is actually moving.
 */
import type { Object3D } from 'three';
import { copyPose, dampFactor, depthStretch, planarDistance, stepPose, stretchedScale } from './motion';
import type { Pose, Viewer } from './motion';
import { ARC_MAX, ARC_PER_UNIT } from './motion';

interface Entry {
  group: Object3D;
  shadow: Object3D | null;
  pose: Pose;
  target: Pose;
  /** Planar distance when the current flight began (for the arc). */
  flight: number;
  settled: boolean;
  /** Depth stretch applied at the last apply (see motion.depthStretch). */
  stretch: number;
  /** Hovering (a flying creature): its shadow falls further away. */
  hover: boolean;
}

const scales = { x: 1, y: 1 };

/** Shadow offset per unit of card height (light comes from the upper left). */
const SHADOW_DX = 0.05;
const SHADOW_DY = -0.08;
const SHADOW_Z = 0.004;
/** A hovering card's shadow falls this many times further, so the gap under it reads. */
const HOVER_SHADOW_REACH = 7;

export class MotionRegistry {
  private readonly entries = new Map<string, Entry>();
  private moving = 0;
  /** When true (a seek jump, reduced motion), new targets apply instantly. */
  snap = false;
  /** The perspective camera's position; null under the straight-down camera. */
  private viewer: Viewer | null = null;
  /** Seconds per frame while a video export drives the frames; null follows wall time. */
  fixedStep: number | null = null;
  private fixedPending = false;

  /** Lets exactly one fixed step through on the next frame (the export calls it per frame). */
  tick(): void {
    this.fixedPending = true;
  }

  setSnap(snap: boolean): void {
    this.snap = snap;
  }

  /**
   * Tells the registry where the camera is, so each card can be stretched
   * along the table's depth by exactly the camera's foreshortening there.
   * Re-applies every card when the viewer moved; returns whether it did.
   */
  setViewer(viewer: Viewer | null): boolean {
    const v = this.viewer;
    if (viewer === null ? v === null : v !== null && v.x === viewer.x && v.y === viewer.y && v.z === viewer.z) return false;
    this.viewer = viewer ? { x: viewer.x, y: viewer.y, z: viewer.z } : null;
    for (const entry of this.entries.values()) this.apply(entry);
    return true;
  }

  /** Depth stretch currently applied to a mesh (1 when unknown). */
  stretchOf(obj: string): number {
    return this.entries.get(obj)?.stretch ?? 1;
  }

  get size(): number {
    return this.entries.size;
  }

  get busy(): boolean {
    return this.moving > 0;
  }

  /** Current (displayed) pose of a mesh, without the arc lift. */
  pose(obj: string): Pose | null {
    return this.entries.get(obj)?.pose ?? null;
  }

  /** The mesh group drawn for an object, or null when it has none. */
  object(obj: string): Object3D | null {
    return this.entries.get(obj)?.group ?? null;
  }

  /** First registration places the mesh at `spawn` (or the target when snapping); `hover` marks a flying creature. */
  set(obj: string, group: Object3D, shadow: Object3D | null, target: Pose, spawn: Pose | null, hover = false): void {
    let entry = this.entries.get(obj);
    if (!entry || entry.group !== group) {
      const start = this.snap || !spawn ? target : spawn;
      entry = { group, shadow, pose: copyPose(start, {} as Pose), target: copyPose(target, {} as Pose), flight: 0, settled: true, stretch: 1, hover };
      this.entries.set(obj, entry);
    } else {
      entry.shadow = shadow;
      entry.hover = hover;
      copyPose(target, entry.target);
    }
    if (this.snap) copyPose(entry.target, entry.pose);
    entry.flight = planarDistance(entry.pose, entry.target);
    const settled = this.isAt(entry);
    if (entry.settled && !settled) this.moving += 1;
    if (!entry.settled && settled) this.moving -= 1;
    entry.settled = settled;
    this.apply(entry);
  }

  remove(obj: string, group: Object3D): void {
    const entry = this.entries.get(obj);
    if (!entry || entry.group !== group) return;
    if (!entry.settled) this.moving -= 1;
    this.entries.delete(obj);
  }

  /** Advances every moving card; returns true while any card is still moving. */
  step(deltaSeconds: number): boolean {
    let delta = deltaSeconds;
    if (this.fixedStep !== null) {
      // Exporting: stray frames (R3F's own invalidations) must not advance time.
      if (!this.fixedPending) return this.moving > 0;
      this.fixedPending = false;
      delta = this.fixedStep;
    }
    if (!this.moving) return false;
    const alpha = dampFactor(delta);
    for (const entry of this.entries.values()) {
      if (entry.settled) continue;
      if (stepPose(entry.pose, entry.target, alpha)) {
        entry.settled = true;
        this.moving -= 1;
      }
      this.apply(entry);
    }
    return this.moving > 0;
  }

  private isAt(entry: Entry): boolean {
    const a = entry.pose;
    const b = entry.target;
    return a.x === b.x && a.y === b.y && a.z === b.z && a.rotZ === b.rotZ && a.rotY === b.rotY && a.scale === b.scale;
  }

  private apply(entry: Entry): void {
    const { pose, group, shadow } = entry;
    let lift = 0;
    if (!entry.settled && entry.flight > 0.05) {
      const s = 1 - Math.min(1, planarDistance(pose, entry.target) / entry.flight);
      lift = 4 * Math.min(ARC_MAX, entry.flight * ARC_PER_UNIT) * s * (1 - s);
    }
    const z = pose.z + lift;
    // Counter the camera's foreshortening so the card projects at its true proportions.
    const k = depthStretch(this.viewer, pose.x, pose.y, z);
    entry.stretch = k;
    stretchedScale(pose.scale, k, pose.rotZ, scales);
    group.position.set(pose.x, pose.y, z);
    group.rotation.set(0, pose.rotY, pose.rotZ, 'ZYX');
    group.scale.set(scales.x, scales.y, 1);
    if (shadow) {
      const grow = 1 + z * 0.35;
      const reach = entry.hover ? z * HOVER_SHADOW_REACH : z;
      shadow.position.set(pose.x + SHADOW_DX * reach, pose.y + SHADOW_DY * reach, SHADOW_Z);
      shadow.rotation.set(0, 0, pose.rotZ);
      shadow.scale.set(scales.x * grow, scales.y * grow, 1);
    }
  }
}
