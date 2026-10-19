/**
 * Camera framing for the replay table (pure math, unit-tested). The `table`
 * preset is a perspective camera tilted from straight down; the `topdown`
 * preset is orthographic. A blend value `u` (0 = table, 1 = topdown) drives
 * an eased transition: tilt goes to 0 while the field of view narrows (a
 * dolly zoom), so the final swap to the orthographic camera is seamless.
 *
 * The framed region is the felt plus its rails plus the visible part of each
 * hand past them, Arena style: the player's hand partly runs off the bottom
 * (layout.apronDepth, sized by the hand scale) and the opponent's smaller hand
 * half off the top (layout.opponentApronDepth, sized by its own scale, larger
 * on a tall high-resolution stage, see `opponentHandBase`). The
 * felt's depth is fixed (layout.TABLE_DEPTH); `fitTableForView` picks its
 * width and the hand scale for a stage: the widest felt that still lets the
 * framed depth bind (with the smallest hands), so the table fills the stage
 * height and the cards are as large as the stage allows, extra width (a
 * collapsed panel) becoming free felt; a stage too narrow for the minimum
 * felt has height to spare, and the hands grow into it.
 */
import { MathUtils, PerspectiveCamera, Vector3 } from 'three';
import type { OrthographicCamera } from 'three';
import {
  HAND_SCALE_MAX,
  HAND_SCALE_MIN,
  HAND_Z,
  MIN_TABLE_WIDTH,
  OPPONENT_HAND_SCALE,
  OPPONENT_HAND_SCALE_LARGE,
  RAIL_WIDTH,
  TABLE_DEPTH,
  apronDepth,
  opponentApronDepth,
  clampHandScale,
  clampOpponentHandScale,
  clampTableWidth,
} from '../layout';

export { RAIL_WIDTH };

/** Near (player) half depth of the framed region: felt, rail and the visible part of the hand. */
export function framedHalfDepth(depth: number, handScale: number = HAND_SCALE_MIN): number {
  return depth / 2 + RAIL_WIDTH + apronDepth(handScale);
}

/** Far (opponent) half depth of the framed region, before the tilt's stretch allowance. */
export function framedFarDepth(depth: number, opponentHandScale: number = OPPONENT_HAND_SCALE): number {
  return depth / 2 + RAIL_WIDTH + opponentApronDepth(opponentHandScale);
}

/** Hand scale steps, so a 1 px resize does not relayout the hands. */
export const HAND_SCALE_STEP = 0.05;

/**
 * Stage heights in device pixels between which the opponent's hand grows from
 * OPPONENT_HAND_SCALE to OPPONENT_HAND_SCALE_LARGE. A 1080p or 1440p monitor
 * at 100% stays at the small hand, which keeps the battlefield large; a tall
 * Retina/5K stage has the pixels to show the opponent's cards larger.
 */
export const OPPONENT_HAND_SMALL_STAGE_PX = 1200;
export const OPPONENT_HAND_LARGE_STAGE_PX = 1800;

/** The opponent's hand scale for a stage `stagePx` device pixels tall (snapped to HAND_SCALE_STEP). */
export function opponentHandBase(stagePx: number): number {
  const span = OPPONENT_HAND_LARGE_STAGE_PX - OPPONENT_HAND_SMALL_STAGE_PX;
  const t = Number.isFinite(stagePx) ? Math.min(1, Math.max(0, (stagePx - OPPONENT_HAND_SMALL_STAGE_PX) / span)) : 0;
  const scale = OPPONENT_HAND_SCALE + (OPPONENT_HAND_SCALE_LARGE - OPPONENT_HAND_SCALE) * t;
  return OPPONENT_HAND_SCALE + Math.floor((scale - OPPONENT_HAND_SCALE) / HAND_SCALE_STEP + 1e-6) * HAND_SCALE_STEP;
}

/** The opponent's hand scale when the player's is `handScale`: it grows with the player's on a narrow stage. */
export function opponentHandScaleFor(base: number, handScale: number): number {
  return clampOpponentHandScale((base * handScale) / HAND_SCALE_MIN);
}
/*
 * A steeper tilt foreshortens the depth, so more of the table fits the
 * stage height and the cards get wider on screen. The meshes undo the
 * foreshortening card by card (motion.depthStretch), and 30° keeps that
 * stretch small enough that the far rows and the far hand still clear each
 * other. The narrow field of view keeps near and far rows close in size.
 */
export const TABLE_TILT_DEG = 30;
export const TABLE_FOV_DEG = 24;
/** Default CSS-pixel margin around the framed table. */
export const FIT_MARGIN_PX = 8;
/** Narrowest field of view reached just before swapping to orthographic. */
export const TOPDOWN_FOV_DEG = 6;
/**
 * Foreshortening at the far edge of a table that fills the frame at the table
 * tilt (the view ray there is tilt + half the field of view from vertical).
 * The meshes stretch along the depth by the local amount (motion.depthStretch);
 * the far framing (layout `opponentApronDepth`) sizes the opponent's hand for
 * up to this much (layout `OPPONENT_HAND_STRETCH`).
 */
export const FAR_STRETCH = 1 / Math.cos(MathUtils.degToRad(TABLE_TILT_DEG + TABLE_FOV_DEG / 2));

export interface TableSize {
  /** Felt width and depth (the rail is added around them, and the hand aprons past the near and far rails). */
  width: number;
  depth: number;
  /** Hand card scale the aprons are sized for; HAND_SCALE_MIN when omitted. */
  handScale?: number;
  /** Opponent hand card scale the far apron is sized for; OPPONENT_HAND_SCALE when omitted. */
  opponentHandScale?: number;
}

export interface FitMargins {
  /** Margins in CSS pixels around the framed table. */
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/** Margins the camera rig and the stage measurement share. */
export const DEFAULT_MARGINS: Readonly<FitMargins> = Object.freeze({
  top: FIT_MARGIN_PX,
  right: FIT_MARGIN_PX,
  bottom: FIT_MARGIN_PX,
  left: FIT_MARGIN_PX,
});

export interface Viewport {
  width: number;
  height: number;
}

export interface PerspectivePose {
  fov: number;
  position: [number, number, number];
  target: [number, number, number];
  near: number;
  far: number;
}

export interface OrthoFrustum {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

/**
 * Extents of the framed region: rail on every side, hand aprons along y
 * (the same for every blend; set per fit, no allocation).
 */
const half = { w: 1, d: 1, far: 1 };

function setTable(table: TableSize): void {
  half.w = table.width / 2 + RAIL_WIDTH;
  half.d = framedHalfDepth(table.depth, table.handScale);
  half.far = framedFarDepth(table.depth, table.opponentHandScale);
}

/** The framed region for `table`: half width, near (player) and far (opponent) depth. */
export function framedExtent(table: TableSize): { halfWidth: number; near: number; far: number } {
  setTable(table);
  return { halfWidth: half.w, near: half.d, far: half.far };
}

export function easeInOutCubic(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
}

/** Tilt (radians from straight down) and vertical fov (degrees) for blend `u`. */
export function blendPose(u: number): { tilt: number; fov: number } {
  const t = Math.min(1, Math.max(0, u));
  const tilt = MathUtils.degToRad(TABLE_TILT_DEG) * (1 - t);
  // Interpolate in tan space so the zoom looks linear.
  const a = Math.tan(MathUtils.degToRad(TABLE_FOV_DEG) / 2);
  const b = Math.tan(MathUtils.degToRad(TOPDOWN_FOV_DEG) / 2);
  const fov = MathUtils.radToDeg(2 * Math.atan(a + (b - a) * t));
  return { tilt, fov };
}

interface Rect {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/*
 * Scratch rectangles: the camera rig refits on every frame of a preset
 * transition, and the distance search projects the corners a few hundred
 * times per fit, so nothing in that path allocates.
 */
const bounds: Rect = { minX: 0, maxX: 0, minY: 0, maxY: 0 };
const ext: Rect = { minX: 0, maxX: 0, minY: 0, maxY: 0 };

/** NDC rectangle the table must stay inside, from pixel margins (written into `bounds`). */
function ndcBounds(view: Viewport, margins: FitMargins): Rect {
  const w = Math.max(1, view.width);
  const h = Math.max(1, view.height);
  bounds.minX = -1 + (2 * margins.left) / w;
  bounds.maxX = 1 - (2 * margins.right) / w;
  bounds.minY = -1 + (2 * margins.bottom) / h;
  bounds.maxY = 1 - (2 * margins.top) / h;
  return bounds;
}

const probe = new PerspectiveCamera();
const point = new Vector3();

function placeProbe(tilt: number, distance: number, targetY: number): void {
  probe.position.set(0, targetY - Math.sin(tilt) * distance, Math.cos(tilt) * distance);
  probe.up.set(0, 1, 0);
  probe.lookAt(0, targetY, 0);
  probe.updateMatrixWorld(true);
}

/**
 * Projected NDC extent of the framed region's corners (written into the shared
 * `ext`): at the felt and, since the hands float at layout HAND_Z (a raised
 * card projects further up the screen), at the hands' height.
 */
function extent(): Rect {
  ext.minX = Infinity;
  ext.maxX = -Infinity;
  ext.minY = Infinity;
  ext.maxY = -Infinity;
  for (let i = 0; i < 8; i += 1) {
    point.set(i & 1 ? half.w : -half.w, i & 2 ? half.far : -half.d, i & 4 ? HAND_Z : 0).project(probe);
    if (point.x < ext.minX) ext.minX = point.x;
    if (point.x > ext.maxX) ext.maxX = point.x;
    if (point.y < ext.minY) ext.minY = point.y;
    if (point.y > ext.maxY) ext.maxY = point.y;
  }
  return ext;
}

function fits(bounds: Rect): boolean {
  const e = extent();
  return e.minX >= bounds.minX && e.maxX <= bounds.maxX && e.minY >= bounds.minY && e.maxY <= bounds.maxY;
}

function smallestDistance(tilt: number, targetY: number, bounds: Rect): number {
  let lo = 1;
  let hi = 2000;
  for (let i = 0; i < 40; i += 1) {
    const mid = (lo + hi) / 2;
    placeProbe(tilt, mid, targetY);
    if (fits(bounds)) hi = mid;
    else lo = mid;
  }
  return hi;
}

/**
 * Closest perspective camera that shows the whole table inside the margins.
 * The look-at point slides along y so the trapezoid is framed tightly.
 */
export function fitPerspective(
  u: number,
  view: Viewport,
  margins: FitMargins,
  table: TableSize,
  out: PerspectivePose = { fov: 0, position: [0, 0, 0], target: [0, 0, 0], near: 0, far: 0 },
): PerspectivePose {
  setTable(table);
  const { tilt, fov } = blendPose(u);
  const bounds = ndcBounds(view, margins);
  probe.fov = fov;
  probe.aspect = Math.max(1, view.width) / Math.max(1, view.height);
  probe.near = 0.1;
  probe.far = 5000;
  probe.updateProjectionMatrix();
  // Alternate: fit the distance, then slide the look-at point along y until
  // the table is centered vertically inside the margins. Converges in a few rounds.
  let targetY = 0;
  let distance = smallestDistance(tilt, targetY, bounds);
  const centerY = (bounds.minY + bounds.maxY) / 2;
  for (let round = 0; round < 4; round += 1) {
    let lo = -half.d * 2;
    let hi = half.d * 2;
    for (let i = 0; i < 40; i += 1) {
      const mid = (lo + hi) / 2;
      placeProbe(tilt, distance, mid);
      const e = extent();
      // Moving the camera toward +y moves the table down the screen.
      if ((e.minY + e.maxY) / 2 > centerY) lo = mid;
      else hi = mid;
    }
    targetY = (lo + hi) / 2;
    distance = smallestDistance(tilt, targetY, bounds);
  }
  const depth = half.d + half.far + 4;
  out.fov = fov;
  out.position[0] = 0;
  out.position[1] = targetY - Math.sin(tilt) * distance;
  out.position[2] = Math.cos(tilt) * distance;
  out.target[0] = 0;
  out.target[1] = targetY;
  out.target[2] = 0;
  out.near = Math.max(0.5, distance - depth);
  out.far = distance + depth;
  return out;
}

/** Orthographic frustum (world units, camera centered on the table) with margins. */
export function fitOrthographic(
  view: Viewport,
  margins: FitMargins,
  table: TableSize,
  out: OrthoFrustum = { left: 0, right: 0, top: 0, bottom: 0 },
): OrthoFrustum {
  setTable(table);
  const bounds = ndcBounds(view, margins);
  const spanX = bounds.maxX - bounds.minX;
  const spanY = bounds.maxY - bounds.minY;
  const aspect = Math.max(1, view.width) / Math.max(1, view.height);
  // World units per NDC unit along y, chosen so both axes fit. The framed
  // region runs from -near to +far, so its middle sits off the table center.
  const perNdcY = Math.max((half.d + half.far) / spanY, (2 * half.w) / (spanX * aspect));
  const perNdcX = perNdcY * aspect;
  const centerX = (bounds.minX + bounds.maxX) / 2;
  const centerY = (bounds.minY + bounds.maxY) / 2;
  const middle = (half.far - half.d) / 2;
  out.left = (-1 - centerX) * perNdcX;
  out.right = (1 - centerX) * perNdcX;
  out.top = middle + (1 - centerY) * perNdcY;
  out.bottom = middle + (-1 - centerY) * perNdcY;
  return out;
}

const widthProbe: TableSize = { width: 1, depth: TABLE_DEPTH, handScale: HAND_SCALE_MIN, opponentHandScale: OPPONENT_HAND_SCALE };
const widthPose: PerspectivePose = { fov: 0, position: [0, 0, 0], target: [0, 0, 0], near: 0, far: 0 };

/** Width steps the table snaps to, so a 1 px resize does not relayout the board. */
export const TABLE_WIDTH_STEP = 0.1;

/**
 * Widest felt (clamped to the layout's limits, snapped to TABLE_WIDTH_STEP)
 * at which the framed table (hand aprons included) still fills the stage
 * height: the felt follows the stage aspect at a fixed tilt and depth. Runs
 * on resize, not per frame.
 */
export function tableWidthForView(
  view: Viewport,
  margins: FitMargins,
  preset: 'table' | 'topdown' = 'table',
  depth: number = TABLE_DEPTH,
  handScale: number = HAND_SCALE_MIN,
  opponentHandScale: number = OPPONENT_HAND_SCALE,
): number {
  const snap = (width: number) => clampTableWidth(Math.floor(width / TABLE_WIDTH_STEP + 1e-6) * TABLE_WIDTH_STEP);
  if (preset === 'topdown') {
    const b = ndcBounds(view, margins);
    const aspect = Math.max(1, view.width) / Math.max(1, view.height);
    const perNdcY = (framedHalfDepth(depth, handScale) + framedFarDepth(depth, opponentHandScale)) / (b.maxY - b.minY);
    return snap((b.maxX - b.minX) * aspect * perNdcY - 2 * RAIL_WIDTH);
  }
  widthProbe.depth = depth;
  widthProbe.handScale = handScale;
  widthProbe.opponentHandScale = opponentHandScale;
  let lo = 1;
  let hi = 60;
  for (let i = 0; i < 22; i += 1) {
    const mid = (lo + hi) / 2;
    widthProbe.width = mid;
    if (widthSlack(view, margins, widthProbe)) lo = mid;
    else hi = mid;
  }
  return snap(lo);
}

/** Fit the perspective camera to `table` and ask: is there slack at the sides (the height binds)? */
function widthSlack(view: Viewport, margins: FitMargins, table: TableSize): boolean {
  const pose = fitPerspective(0, view, margins, table, widthPose);
  // Re-place the probe at the fitted pose and measure the table's extent.
  const distance = Math.hypot(pose.position[1] - pose.target[1], pose.position[2]);
  placeProbe(blendPose(0).tilt, distance, pose.target[1]);
  const e = extent();
  const b = ndcBounds(view, margins);
  return e.maxX < b.maxX - 1e-4 && e.minX > b.minX + 1e-4;
}

/** Does `table` leave slack above and below (the width binds)? */
function heightSlack(view: Viewport, margins: FitMargins, preset: 'table' | 'topdown', table: TableSize): boolean {
  if (preset === 'topdown') {
    setTable(table);
    const b = ndcBounds(view, margins);
    const aspect = Math.max(1, view.width) / Math.max(1, view.height);
    return (2 * half.w) / ((b.maxX - b.minX) * aspect) > (half.d + half.far) / (b.maxY - b.minY) + 1e-6;
  }
  const pose = fitPerspective(0, view, margins, table, widthPose);
  const distance = Math.hypot(pose.position[1] - pose.target[1], pose.position[2]);
  placeProbe(blendPose(0).tilt, distance, pose.target[1]);
  const e = extent();
  const b = ndcBounds(view, margins);
  return e.maxY < b.maxY - 1e-4 && e.minY > b.minY + 1e-4;
}


export interface TableFit {
  /** Felt width. */
  width: number;
  /** Hand card scale the stage has room for. */
  handScale: number;
  /** The opponent's hand card scale for that stage. */
  opponentHandScale: number;
}

const scaleProbe: TableSize = { width: MIN_TABLE_WIDTH, depth: TABLE_DEPTH, handScale: HAND_SCALE_MIN, opponentHandScale: OPPONENT_HAND_SCALE };

/**
 * Felt width and hand scale for a stage. The felt comes first: the widest
 * that fills the stage height with the smallest hands. A stage too narrow
 * for even the minimum felt binds on the width and has height to spare, and
 * the hands grow into it (up to HAND_SCALE_MAX, snapped to HAND_SCALE_STEP).
 * The opponent's hand starts from `opponentHandBase` for the stage's height in
 * device pixels (`pixelRatio` is the screen's devicePixelRatio) and grows with
 * the player's. Runs on resize, not per frame.
 */
export function fitTableForView(
  view: Viewport,
  margins: FitMargins,
  preset: 'table' | 'topdown' = 'table',
  depth: number = TABLE_DEPTH,
  pixelRatio = 1,
): TableFit {
  const base = opponentHandBase(view.height * (Number.isFinite(pixelRatio) && pixelRatio > 0 ? pixelRatio : 1));
  const fit = (handScale: number): TableFit => ({ width, handScale, opponentHandScale: opponentHandScaleFor(base, handScale) });
  const width = tableWidthForView(view, margins, preset, depth, HAND_SCALE_MIN, opponentHandScaleFor(base, HAND_SCALE_MIN));
  if (width > MIN_TABLE_WIDTH + 1e-9) return fit(HAND_SCALE_MIN);
  scaleProbe.depth = depth;
  const probe = (handScale: number) => {
    scaleProbe.handScale = handScale;
    scaleProbe.opponentHandScale = opponentHandScaleFor(base, handScale);
    return heightSlack(view, margins, preset, scaleProbe);
  };
  let lo = HAND_SCALE_MIN;
  let hi = HAND_SCALE_MAX;
  if (probe(hi)) return fit(hi);
  for (let i = 0; i < 16; i += 1) {
    const mid = (lo + hi) / 2;
    if (probe(mid)) lo = mid;
    else hi = mid;
  }
  const snapped = Math.floor((lo - HAND_SCALE_MIN) / HAND_SCALE_STEP + 1e-6) * HAND_SCALE_STEP + HAND_SCALE_MIN;
  return fit(clampHandScale(snapped));
}

/** Applies a fitted pose to a perspective camera. */
export function applyPerspective(camera: PerspectiveCamera, pose: PerspectivePose, view: Viewport): void {
  camera.fov = pose.fov;
  camera.aspect = Math.max(1, view.width) / Math.max(1, view.height);
  camera.near = pose.near;
  camera.far = pose.far;
  camera.up.set(0, 1, 0);
  camera.position.set(pose.position[0], pose.position[1], pose.position[2]);
  camera.lookAt(pose.target[0], pose.target[1], pose.target[2]);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
}

/** Applies a fitted frustum to an orthographic camera looking straight down. */
export function applyOrthographic(camera: OrthographicCamera, frustum: OrthoFrustum): void {
  camera.left = frustum.left;
  camera.right = frustum.right;
  camera.top = frustum.top;
  camera.bottom = frustum.bottom;
  camera.near = 1;
  camera.far = 100;
  camera.up.set(0, 1, 0);
  camera.position.set(0, 0, 40);
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
}
