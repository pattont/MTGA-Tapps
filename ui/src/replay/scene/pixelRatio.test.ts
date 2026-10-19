import { describe, expect, it } from 'vitest';
import { PIXEL_BUDGET, isSupersampled, scenePixelRatio } from './pixelRatio';

describe('scenePixelRatio', () => {
  it('renders a 1x 1440p table at 2x', () => {
    expect(scenePixelRatio(1, 2560, 1300)).toBe(2);
    expect(isSupersampled(1, 2560, 1300)).toBe(true);
  });

  it('leaves a Retina screen at its own 2x, with MSAA', () => {
    expect(scenePixelRatio(2, 2560, 1300)).toBe(2);
    expect(isSupersampled(2, 2560, 1300)).toBe(false);
  });

  it('never drops a high-density screen below its own ratio', () => {
    // A 6K display at 2x is over the budget, but keeps today's 2x.
    expect(scenePixelRatio(2, 3008, 1692)).toBe(2);
    expect(scenePixelRatio(3, 1200, 800)).toBe(2);
  });

  it('raises Windows 125% scaling to 2x', () => {
    expect(scenePixelRatio(1.25, 2048, 1100)).toBe(2);
    expect(isSupersampled(1.25, 2048, 1100)).toBe(true);
  });

  it('caps a very large 1x window at the pixel budget', () => {
    const ratio = scenePixelRatio(1, 3840, 2160);
    expect(ratio).toBeGreaterThan(1);
    expect(ratio).toBeLessThan(2);
    expect(3840 * ratio * 2160 * ratio).toBeLessThanOrEqual(PIXEL_BUDGET);
  });

  it('falls back to the screen ratio when nothing fits the budget', () => {
    expect(scenePixelRatio(1, 7680, 4320)).toBe(1);
    expect(isSupersampled(1, 7680, 4320)).toBe(false);
  });

  it('handles an unmeasured canvas and a missing ratio', () => {
    expect(scenePixelRatio(1, 0, 0)).toBe(2);
    expect(scenePixelRatio(Number.NaN, 800, 600)).toBe(2);
  });
});
