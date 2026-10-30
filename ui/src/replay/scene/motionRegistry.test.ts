import { Object3D } from 'three';
import { describe, expect, it } from 'vitest';
import { MotionRegistry } from './motionRegistry';

describe('MotionRegistry shadows', () => {
  it('casts a hovering card’s shadow further from it than a card at the same height', () => {
    const shadowAt = (hover: boolean) => {
      const registry = new MotionRegistry();
      const shadow = new Object3D();
      const pose = { x: 0, y: 0, z: 0.32, rotZ: 0, rotY: 0, scale: 1 };
      registry.set('card', new Object3D(), shadow, pose, null, hover);
      return shadow.position;
    };
    const resting = shadowAt(false);
    const hovering = shadowAt(true);
    expect(hovering.x).toBeGreaterThan(resting.x * 3);
    expect(hovering.y).toBeLessThan(resting.y * 3);
    expect(hovering.z).toBe(resting.z);
  });
});
