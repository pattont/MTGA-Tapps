/**
 * Pixel ratio for the 3D table. A 1x screen (a 1440p monitor at 100% scaling)
 * draws a card about 90 pixels wide, so its texture lands on a small, blurry
 * mipmap. The table therefore renders at least 2x and lets the browser scale
 * the finished frame down, which keeps card names and art sharp. A pixel
 * budget (about one 5K frame) keeps very large 1x windows affordable, and the
 * ratio never drops below the screen's own (up to 2), so Retina screens are
 * unchanged.
 */

/** Ratio the table aims for on any screen. */
export const SUPERSAMPLE_RATIO = 2;
/** Most drawing-buffer pixels supersampling may use: one 5120×2880 frame. */
export const PIXEL_BUDGET = 5120 * 2880;

/** The screen's own ratio as the canvas uses it: 1 to 2. */
export function nativePixelRatio(deviceRatio: number): number {
  return Math.min(SUPERSAMPLE_RATIO, Math.max(1, Number.isFinite(deviceRatio) ? deviceRatio : 1));
}

/** The ratio the table renders at, for a screen ratio and the canvas's CSS size. */
export function scenePixelRatio(deviceRatio: number, cssWidth: number, cssHeight: number): number {
  const native = nativePixelRatio(deviceRatio);
  const area = cssWidth * cssHeight;
  const affordable = area > 0 ? Math.sqrt(PIXEL_BUDGET / area) : SUPERSAMPLE_RATIO;
  // Round down to 0.05 steps so a window resize does not reallocate the buffer every pixel.
  const target = Math.floor(Math.min(SUPERSAMPLE_RATIO, affordable) * 20) / 20;
  return Math.max(native, target);
}

/**
 * True when the table renders above the screen's own ratio. The downscale then
 * smooths edges (including the cutout card corners MSAA misses), so the canvas
 * skips MSAA and its multisampled buffers.
 */
export function isSupersampled(deviceRatio: number, cssWidth: number, cssHeight: number): boolean {
  return scenePixelRatio(deviceRatio, cssWidth, cssHeight) > nativePixelRatio(deviceRatio);
}
