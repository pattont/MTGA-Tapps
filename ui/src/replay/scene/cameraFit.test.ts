import { describe, expect, it } from 'vitest';
import { OrthographicCamera, PerspectiveCamera, Vector3 } from 'three';
import {
  CARD_WIDTH,
  DEFAULT_TABLE_WIDTH,
  HAND_SCALE_MAX,
  HAND_SCALE_MIN,
  HAND_Z,
  MAX_TABLE_WIDTH,
  MIN_TABLE_WIDTH,
  FAR_ROW_STRETCH,
  OPPONENT_HAND_SCALE,
  OPPONENT_HAND_SCALE_LARGE,
  OPPONENT_HAND_STRETCH,
  ROW_Y,
  TABLE_DEPTH,
} from '../layout';
import {
  DEFAULT_MARGINS,
  HAND_SCALE_STEP,
  OPPONENT_HAND_LARGE_STAGE_PX,
  OPPONENT_HAND_SMALL_STAGE_PX,
  RAIL_WIDTH,
  TABLE_FOV_DEG,
  TABLE_TILT_DEG,
  TABLE_WIDTH_STEP,
  TOPDOWN_FOV_DEG,
  applyOrthographic,
  applyPerspective,
  blendPose,
  easeInOutCubic,
  fitOrthographic,
  fitPerspective,
  fitTableForView,
  FAR_STRETCH,
  framedExtent,
  framedFarDepth,
  framedHalfDepth,
  opponentHandBase,
  tableWidthForView,
} from './cameraFit';
import type { TableSize } from './cameraFit';

const margins = { top: 14, right: 14, bottom: 14, left: 14 };
const TABLE: TableSize = { width: DEFAULT_TABLE_WIDTH, depth: TABLE_DEPTH };

/** Corners of the framed region: rails and the hand aprons, at the felt and at the floating hands' height. */
function corners(table: TableSize) {
  const { halfWidth: w, near, far } = framedExtent(table);
  expect(near).toBeCloseTo(framedHalfDepth(table.depth, table.handScale), 9);
  return [0, HAND_Z].flatMap((z) => [
    [-w, -near, z],
    [w, -near, z],
    [-w, far, z],
    [w, far, z],
  ]);
}

function ndcExtent(camera: PerspectiveCamera | OrthographicCamera, table: TableSize) {
  const ys: number[] = [];
  const xs: number[] = [];
  for (const [x, y, z] of corners(table)) {
    const p = new Vector3(x, y, z).project(camera);
    xs.push(p.x);
    ys.push(p.y);
  }
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

function stageCamera(width: number, height: number) {
  const view = { width, height };
  const table = { width: tableWidthForView(view, DEFAULT_MARGINS), depth: TABLE_DEPTH };
  const camera = new PerspectiveCamera();
  applyPerspective(camera, fitPerspective(0, view, DEFAULT_MARGINS, table), view);
  return { view, table, camera };
}

/** On-screen width (CSS px) of an untapped full-size card centered at (0, y). */
function cardPixels(camera: PerspectiveCamera, viewWidth: number, y: number): number {
  const a = new Vector3(-CARD_WIDTH / 2, y, 0).project(camera);
  const b = new Vector3(CARD_WIDTH / 2, y, 0).project(camera);
  return ((b.x - a.x) / 2) * viewWidth;
}

describe('camera fit', () => {
  it('blends from the tilted table preset to a narrow top-down view', () => {
    expect(blendPose(0).fov).toBeCloseTo(TABLE_FOV_DEG);
    expect(TABLE_TILT_DEG).toBe(30);
    expect(blendPose(0).tilt).toBeCloseTo((TABLE_TILT_DEG * Math.PI) / 180);
    expect(blendPose(1).fov).toBeCloseTo(TOPDOWN_FOV_DEG);
    expect(blendPose(1).tilt).toBe(0);
    expect(easeInOutCubic(0)).toBe(0);
    expect(easeInOutCubic(0.5)).toBeCloseTo(0.5);
    expect(easeInOutCubic(1)).toBe(1);
  });

  it.each([
    [830, 630],
    [1200, 500],
    [600, 800],
  ])('fits a given table tightly and centered at %ix%i', (width, height) => {
    const view = { width, height };
    const camera = new PerspectiveCamera();
    applyPerspective(camera, fitPerspective(0, view, margins, TABLE), view);
    const e = ndcExtent(camera, TABLE);
    const limitX = 1 - (2 * 14) / width;
    const limitY = 1 - (2 * 14) / height;
    expect(e.minX).toBeGreaterThanOrEqual(-limitX - 1e-3);
    expect(e.maxX).toBeLessThanOrEqual(limitX + 1e-3);
    expect(e.minY).toBeGreaterThanOrEqual(-limitY - 1e-3);
    expect(e.maxY).toBeLessThanOrEqual(limitY + 1e-3);
    // Tight on at least one axis, centered vertically.
    expect(Math.min(limitX - e.maxX, limitY - e.maxY)).toBeLessThan(0.02);
    expect((e.minY + e.maxY) / 2).toBeCloseTo(0, 2);
    // The near edge looks wider than the far edge (perspective tilt toward the player).
    const w = TABLE.width / 2 + RAIL_WIDTH;
    const d = TABLE.depth / 2 + RAIL_WIDTH;
    expect(new Vector3(w, -d, 0).project(camera).x).toBeGreaterThan(new Vector3(w, d, 0).project(camera).x);
  });

  // The felt's width follows the stage: wide stages bind on the depth (the
  // table fills the height and also reaches the sides); stages too narrow for
  // the minimum table bind on the width.
  it.each([
    ['actions collapsed', 1160, 660, 'both'],
    ['wide monitor', 1620, 840, 'both'],
    ['actions open', 830, 660, 'both'],
    ['tall', 600, 900, 'x'],
    ['ultra-wide', 3400, 700, 'y'],
  ] as const)('fills the %s stage (%ix%i), binding on %s', (_name, width, height, binding) => {
    const { table, camera } = stageCamera(width, height);
    const e = ndcExtent(camera, table);
    const b = { x: 1 - (2 * DEFAULT_MARGINS.right) / width, y: 1 - (2 * DEFAULT_MARGINS.top) / height };
    expect(e.maxX).toBeLessThanOrEqual(b.x + 1e-6);
    expect(e.maxY).toBeLessThanOrEqual(b.y + 1e-6);
    expect((e.minX + e.maxX) / 2).toBeCloseTo(0, 2);
    expect((e.minY + e.maxY) / 2).toBeCloseTo(0, 2);
    const slackX = (b.x - e.maxX) / 2;
    const slackY = (b.y - e.maxY) / 2;
    if (binding === 'both') {
      expect(slackY).toBeLessThan(0.003);
      // Snapping the width down to TABLE_WIDTH_STEP leaves a sliver at the sides.
      expect(slackX).toBeLessThan(0.02);
    } else if (binding === 'x') {
      expect(table.width).toBe(MIN_TABLE_WIDTH);
      expect(slackX).toBeLessThan(0.003);
    } else {
      expect(table.width).toBe(MAX_TABLE_WIDTH);
      expect(slackY).toBeLessThan(0.003);
    }
    expect(Math.round(table.width / TABLE_WIDTH_STEP) * TABLE_WIDTH_STEP).toBeCloseTo(table.width, 6);
  });

  it('makes cards readable at 1440×900, larger with the Actions panel or sidebar collapsed', () => {
    // Stage sizes measured in the built page at 1440×900 (panel open / sidebar collapsed / panel collapsed).
    const open = stageCamera(840, 659);
    const sidebar = stageCamera(1002, 659);
    const collapsed = stageCamera(1132, 659);
    const you = (s: ReturnType<typeof stageCamera>) => cardPixels(s.camera, s.view.width, ROW_Y.creatures);
    const opp = (s: ReturnType<typeof stageCamera>) => cardPixels(s.camera, s.view.width, -ROW_Y.creatures);
    // Arena-style framing (both hands reach onto their felt strips) makes them
    // about a fifth larger than when the hands sat wholly past the rails
    // (66 px), less a little for framing the hands at the height they float
    // (layout HAND_Z, above the tallest pile). The depth binds on all three
    // stages, so the extra width is felt.
    expect(you(open)).toBeGreaterThan(76);
    expect(opp(open)).toBeGreaterThan(72);
    expect(you(sidebar)).toBeCloseTo(you(open), 0);
    expect(you(collapsed)).toBeCloseTo(you(sidebar), 6);
    expect(opp(collapsed)).toBeCloseTo(opp(sidebar), 6);
    // A collapsed panel turns into more felt once the depth binds.
    expect(collapsed.table.width).toBeGreaterThan(sidebar.table.width);
  });

  it('grows the hands into the height a narrow stage leaves over, and not otherwise', () => {
    // Wide stages: the felt fills the height with the smallest hands.
    for (const view of [{ width: 1620, height: 840 }, { width: 1132, height: 659 }]) {
      const fit = fitTableForView(view, DEFAULT_MARGINS);
      expect(fit.width).toBeGreaterThan(MIN_TABLE_WIDTH);
      expect(fit.handScale).toBe(HAND_SCALE_MIN);
    }
    // A tall stage (a large window with the Actions panel open) binds on the width: big hands.
    const tall = fitTableForView({ width: 1340, height: 1370 }, DEFAULT_MARGINS);
    expect(tall.width).toBe(MIN_TABLE_WIDTH);
    expect(tall.handScale).toBeGreaterThan(1.3);
    expect(tall.handScale).toBeLessThanOrEqual(HAND_SCALE_MAX);
    expect(fitTableForView({ width: 600, height: 1400 }, DEFAULT_MARGINS).handScale).toBe(HAND_SCALE_MAX);
    // A laptop stage with the panel open still binds on the height; a taller one grows the hands step by step.
    const laptop = fitTableForView({ width: 840, height: 659 }, DEFAULT_MARGINS);
    expect(laptop.width).toBeGreaterThanOrEqual(MIN_TABLE_WIDTH);
    expect(laptop.handScale).toBe(HAND_SCALE_MIN);
    const taller = fitTableForView({ width: 840, height: 900 }, DEFAULT_MARGINS);
    expect(taller.width).toBe(MIN_TABLE_WIDTH);
    expect(taller.handScale).toBeGreaterThan(HAND_SCALE_MIN);
    expect(taller.handScale).toBeLessThanOrEqual(fitTableForView({ width: 840, height: 1100 }, DEFAULT_MARGINS).handScale);
    expect(Math.round((taller.handScale - HAND_SCALE_MIN) / HAND_SCALE_STEP) * HAND_SCALE_STEP + HAND_SCALE_MIN).toBeCloseTo(taller.handScale, 9);
    // Whatever the hand scale, the framed region (aprons included) still fits inside the margins.
    for (const [view, fit] of [
      [{ width: 1340, height: 1370 }, tall],
      [{ width: 840, height: 900 }, taller],
      [{ width: 840, height: 659 }, laptop],
    ] as const) {
      const table = { width: fit.width, depth: TABLE_DEPTH, handScale: fit.handScale };
      const camera = new PerspectiveCamera();
      applyPerspective(camera, fitPerspective(0, view, DEFAULT_MARGINS, table), view);
      const e = ndcExtent(camera, table);
      expect(e.maxY).toBeLessThanOrEqual(1 - (2 * DEFAULT_MARGINS.top) / view.height + 1e-6);
      expect(e.maxX).toBeLessThanOrEqual(1 - (2 * DEFAULT_MARGINS.right) / view.width + 1e-6);
    }
    // Top-down framing makes the same call (without the tilt's foreshortening it takes a narrower stage).
    expect(fitTableForView({ width: 600, height: 900 }, DEFAULT_MARGINS, 'topdown').handScale).toBe(HAND_SCALE_MAX);
    expect(fitTableForView({ width: 1620, height: 840 }, DEFAULT_MARGINS, 'topdown').handScale).toBe(HAND_SCALE_MIN);
  });

  it('frames the far side the same in both presets, sized for the stretched opponent hand', () => {
    // The far framing already sizes the opponent's hand for the tilt's stretch, in both presets.
    const table = { width: DEFAULT_TABLE_WIDTH, depth: TABLE_DEPTH, handScale: 1 };
    const tilted = framedExtent(table);
    const flat = framedExtent(table);
    expect(tilted.far).toBeCloseTo(framedFarDepth(TABLE_DEPTH), 9);
    expect(flat.far).toBeCloseTo(framedFarDepth(TABLE_DEPTH), 9);
    expect(flat.near).toBeCloseTo(framedHalfDepth(TABLE_DEPTH, 1), 9);
    // Their hand clears the land names: the layout's estimate of the back row's stretch is
    // close to what the camera puts there (between none and the far edge's).
    expect(FAR_ROW_STRETCH).toBeGreaterThan(1);
    expect(FAR_ROW_STRETCH).toBeLessThan(FAR_STRETCH);
    expect(OPPONENT_HAND_STRETCH).toBeGreaterThanOrEqual(FAR_STRETCH);
    expect(OPPONENT_HAND_SCALE).toBeLessThan(1);
    // The framed region (far allowance included) is what the fit centers and keeps inside the margins.
    const view = { width: 1200, height: 700 };
    const camera = new PerspectiveCamera();
    applyPerspective(camera, fitPerspective(0, view, margins, table), view);
    const e = ndcExtent(camera, table);
    expect(e.maxY).toBeLessThanOrEqual(1 - 28 / view.height + 1e-6);
    expect((e.minY + e.maxY) / 2).toBeCloseTo(0, 2);
  });

  it('draws the opponent hand larger on a tall high-resolution stage, and keeps it framed', () => {
    expect(opponentHandBase(OPPONENT_HAND_SMALL_STAGE_PX)).toBe(OPPONENT_HAND_SCALE);
    expect(opponentHandBase(OPPONENT_HAND_LARGE_STAGE_PX)).toBeCloseTo(OPPONENT_HAND_SCALE_LARGE, 9);
    expect(opponentHandBase(5000)).toBeCloseTo(OPPONENT_HAND_SCALE_LARGE, 9);
    expect(opponentHandBase(Number.NaN)).toBe(OPPONENT_HAND_SCALE);
    const middle = opponentHandBase((OPPONENT_HAND_SMALL_STAGE_PX + OPPONENT_HAND_LARGE_STAGE_PX) / 2);
    expect(middle).toBeGreaterThan(OPPONENT_HAND_SCALE);
    expect(middle).toBeLessThan(OPPONENT_HAND_SCALE_LARGE);
    // The same 1440p-tall CSS stage: small at 1x (a 1440p monitor), large at 2x (a 5K display).
    const view = { width: 1900, height: 1000 };
    const monitor = fitTableForView(view, DEFAULT_MARGINS, 'table', TABLE_DEPTH, 1);
    const retina = fitTableForView(view, DEFAULT_MARGINS, 'table', TABLE_DEPTH, 2);
    expect(monitor.opponentHandScale).toBe(OPPONENT_HAND_SCALE);
    expect(retina.opponentHandScale).toBeCloseTo(OPPONENT_HAND_SCALE_LARGE, 9);
    // The larger far apron frames more depth into the same height (the felt widens with the
    // stage aspect, everything a little smaller on screen), and the framed region still fits.
    expect(retina.width).toBeGreaterThan(monitor.width);
    const table = { width: retina.width, depth: TABLE_DEPTH, handScale: retina.handScale, opponentHandScale: retina.opponentHandScale };
    expect(framedExtent(table).far).toBeCloseTo(framedFarDepth(TABLE_DEPTH, OPPONENT_HAND_SCALE_LARGE), 9);
    const camera = new PerspectiveCamera();
    applyPerspective(camera, fitPerspective(0, view, DEFAULT_MARGINS, table), view);
    const e = ndcExtent(camera, table);
    expect(e.maxY).toBeLessThanOrEqual(1 - (2 * DEFAULT_MARGINS.top) / view.height + 1e-6);
    expect(e.minY).toBeGreaterThanOrEqual(-1 + (2 * DEFAULT_MARGINS.bottom) / view.height - 1e-6);
    // A narrow stage grows the opponent's hand with the player's.
    const narrow = fitTableForView({ width: 840, height: 1100 }, DEFAULT_MARGINS, 'table', TABLE_DEPTH, 1);
    expect(narrow.handScale).toBeGreaterThan(HAND_SCALE_MIN);
    expect(narrow.opponentHandScale).toBeCloseTo((OPPONENT_HAND_SCALE * narrow.handScale) / HAND_SCALE_MIN, 9);
  });

  it('keeps near/far planes around the table for depth precision', () => {
    const pose = fitPerspective(0, { width: 800, height: 600 }, margins, TABLE);
    const distance = Math.hypot(...pose.position.map((v, i) => v - pose.target[i]));
    const d = TABLE.depth / 2 + RAIL_WIDTH;
    expect(pose.near).toBeLessThan(distance - d);
    expect(pose.far).toBeGreaterThan(distance + d);
    expect(pose.near).toBeGreaterThan(0.4);
  });

  it('fits the orthographic top-down camera on both axes, and its own table width fills the height', () => {
    for (const view of [{ width: 900, height: 500 }, { width: 500, height: 900 }]) {
      const camera = new OrthographicCamera();
      applyOrthographic(camera, fitOrthographic(view, margins, TABLE));
      const e = ndcExtent(camera, TABLE);
      expect(e.maxX).toBeLessThanOrEqual(1 - 28 / view.width + 1e-6);
      expect(e.maxY).toBeLessThanOrEqual(1 - 28 / view.height + 1e-6);
      expect(Math.min(1 - 28 / view.width - e.maxX, 1 - 28 / view.height - e.maxY)).toBeLessThan(1e-6);
    }
    const view = { width: 1200, height: 660 };
    const table = { width: tableWidthForView(view, margins, 'topdown'), depth: TABLE_DEPTH };
    const camera = new OrthographicCamera();
    applyOrthographic(camera, fitOrthographic(view, margins, table));
    const e = ndcExtent(camera, table);
    expect(1 - 28 / view.height - e.maxY).toBeLessThan(1e-6);
    expect(1 - 28 / view.width - e.maxX).toBeLessThan(0.02);
  });
});
