/**
 * Draws one video frame with Canvas 2D: the rendered table (the WebGL
 * canvas) with the HUD band above it, the current action as a caption below,
 * and the DOM overlays redrawn in place — pile and stat badges, the stack
 * column with card art, targeting arrows and the ending screen. All overlay
 * positions are in the live stage's CSS pixels; `FrameLayout.scale` maps
 * them onto the video.
 */
import { formatCardName } from '../../format';
import type { LogItem, LogPart } from '../logText';
import { formatClock } from '../logText';
import { arrowShape } from '../scene/arrows';
import type { LabelTone } from '../scene/labels';
import { stackCardWidth } from '../scene/stackView';

export interface FrameLayout {
  width: number;
  height: number;
  /** Video pixels per stage CSS pixel. */
  scale: number;
  /** Heights (video px) of the HUD band above and the caption band below the table (0 with the log). */
  band: number;
  caption: number;
  /** Stage size in CSS pixels. */
  sceneWidth: number;
  sceneHeight: number;
  /** Width (video px) of the actions log column at the right; 0 when off. */
  logWidth: number;
}

export interface FrameSeat {
  name: string;
  life: number;
  hand: number;
  library: number;
  active: boolean;
  /** This action's life change ("−3"), shown beside the total; null when none. */
  change?: { text: string; loss: boolean } | null;
}

export interface FrameHud {
  /** "Turn 12" or "Pre-game". */
  turn: string;
  whose: string | null;
  whoseIsPlayer: boolean;
  phase: string | null;
  clock: string;
  you: FrameSeat;
  opponent: FrameSeat;
}

export interface FrameLabel {
  x: number;
  y: number;
  text: string;
  tone: LabelTone;
  emphasis?: boolean;
}

export interface FrameStackItem {
  stackId: string;
  image: CanvasImageSource | null;
  name: string;
  who: string;
  kind: string;
  top: boolean;
  mine: boolean;
  /** Kept for the current action after leaving the stack: stamped and dimmed. */
  exit?: 'resolved' | 'countered' | 'fizzled';
}

export type FrameArrowEnd = { x: number; y: number } | { stackId: string };

export interface FrameArrow {
  from: FrameArrowEnd;
  to: FrameArrowEnd;
  glow: string;
  core: string;
  /** A player target: draw the reticle. */
  reticle: boolean;
}

export interface FrameCaption {
  text: string;
  actor: 'player' | 'opponent' | 'system';
}

export interface FrameLog {
  items: readonly LogItem[];
  /** Index of the current row in `items`, -1 before the first. */
  activeIndex: number;
  playerSeat: number;
}

export interface FrameInput {
  scene: CanvasImageSource;
  hud: FrameHud;
  labels: readonly FrameLabel[];
  stack: readonly FrameStackItem[];
  arrows: readonly FrameArrow[];
  caption: FrameCaption | null;
  /** The actions log column; null when the layout has no log column. */
  log: FrameLog | null;
  ending: { headline: string; reason: string | null; result: 'win' | 'loss' | 'draw' | 'unknown' } | null;
  /** Sleeve accent colors for the two players (HUD names). */
  colors: { player: string; opponent: string };
}

export const BAND_PX = 44;
export const CAPTION_PX = 36;
/** The actions log column, in stage CSS px (the site's panel is about this wide). */
export const LOG_PX = 340;
export const DEFAULT_TARGET_WIDTH = 1920;

const even = (n: number) => Math.max(2, Math.round(n / 2) * 2);

/**
 * Video geometry for a stage of `sceneWidth` × `sceneHeight` CSS px. With the
 * log, the column sits at the right and the caption band is dropped (the log
 * shows the current action); the whole frame is `targetWidth` wide.
 */
export function frameLayout(sceneWidth: number, sceneHeight: number, targetWidth = DEFAULT_TARGET_WIDTH, log = false): FrameLayout {
  const w = Math.max(1, sceneWidth);
  const h = Math.max(1, sceneHeight);
  const logCss = log ? LOG_PX : 0;
  const scale = Math.min(targetWidth / (w + logCss), 3);
  const band = Math.round(BAND_PX * scale);
  const caption = log ? 0 : Math.round(CAPTION_PX * scale);
  const logWidth = Math.round(logCss * scale);
  const width = even(w * scale + logWidth);
  const height = even(h * scale + band + caption);
  return { width, height, scale, band, caption, sceneWidth: w, sceneHeight: h, logWidth };
}

const COLORS = {
  background: '#0b0f14',
  band: '#121820',
  text: '#e9eef4',
  muted: '#98a4b3',
  pill: 'rgba(8, 12, 16, 0.86)',
  pillBorder: 'rgba(255, 255, 255, 0.22)',
  gold: '#f6e2b0',
  goldBorder: 'rgba(240, 198, 108, 0.6)',
  violet: '#ebe3ff',
  violetBorder: 'rgba(196, 170, 255, 0.6)',
  pileText: '#d5dde6',
  panel: 'rgba(18, 24, 32, 0.94)',
  win: '#4cc38a',
  loss: '#e5484d',
  draw: '#f0c674',
} as const;

const FONT = '"Inter", "Segoe UI", system-ui, -apple-system, sans-serif';

const EXIT_STAMPS = {
  resolved: { text: 'RESOLVED', color: '#2bb3a3' },
  countered: { text: 'COUNTERED', color: '#e5484d' },
  fizzled: { text: 'FIZZLED', color: '#f0c674' },
} as const;

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function ellipsize(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (ctx.measureText(`${text.slice(0, mid)}…`).width <= maxWidth) lo = mid;
    else hi = mid - 1;
  }
  return `${text.slice(0, lo).trimEnd()}…`;
}

function drawPill(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  text: string,
  px: number,
  weight: number,
  fill: string,
  border: string,
  color: string,
  radius: number,
): void {
  ctx.font = `${weight} ${px}px ${FONT}`;
  const padX = px * 0.6;
  const w = ctx.measureText(text).width + padX * 2;
  const h = px * 1.5;
  roundRect(ctx, cx - w / 2, cy - h / 2, w, h, radius);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.lineWidth = 1;
  ctx.strokeStyle = border;
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, cx, cy + px * 0.04);
}

function drawHud(ctx: CanvasRenderingContext2D, layout: FrameLayout, hud: FrameHud, colors: FrameInput['colors']): void {
  const { band, scale } = layout;
  const width = layout.width - layout.logWidth;
  ctx.fillStyle = COLORS.band;
  ctx.fillRect(0, 0, width, band);
  ctx.fillStyle = 'rgba(255,255,255,0.06)';
  ctx.fillRect(0, band - 1, width, 1);
  const px = 13 * scale;
  const cy = band / 2;
  ctx.textBaseline = 'middle';
  // Left: turn, whose turn, phase, clock.
  let x = 14 * scale;
  ctx.textAlign = 'left';
  ctx.font = `700 ${px}px ${FONT}`;
  ctx.fillStyle = COLORS.gold;
  ctx.fillText(hud.turn, x, cy);
  x += ctx.measureText(hud.turn).width + 12 * scale;
  ctx.font = `600 ${px}px ${FONT}`;
  if (hud.whose) {
    ctx.fillStyle = hud.whoseIsPlayer ? colors.player : colors.opponent;
    ctx.fillText(hud.whose, x, cy);
    x += ctx.measureText(hud.whose).width + 12 * scale;
  }
  ctx.fillStyle = COLORS.text;
  if (hud.phase) {
    ctx.fillText(hud.phase, x, cy);
    x += ctx.measureText(hud.phase).width + 12 * scale;
  }
  ctx.font = `500 ${px}px ${FONT}`;
  ctx.fillStyle = COLORS.muted;
  ctx.fillText(`${hud.clock} elapsed`, x, cy);
  // Right: the two seats, the active one underlined.
  ctx.textAlign = 'right';
  let rx = width - 14 * scale;
  const seats: Array<[FrameSeat, string]> = [
    [hud.opponent, colors.opponent],
    [hud.you, colors.player],
  ];
  seats.forEach(([seat, accent], i) => {
    const counts = `Hand ${seat.hand} · Library ${seat.library}`;
    ctx.font = `500 ${px * 0.85}px ${FONT}`;
    ctx.fillStyle = COLORS.muted;
    ctx.fillText(counts, rx, cy);
    rx -= ctx.measureText(counts).width + 10 * scale;
    if (seat.change) {
      const changePx = px * 0.9;
      ctx.font = `800 ${changePx}px ${FONT}`;
      const w = ctx.measureText(seat.change.text).width + changePx * 1.2;
      drawPill(ctx, rx - w / 2, cy, seat.change.text, changePx, 800, seat.change.loss ? '#c4221c' : '#24843e', 'rgba(255,255,255,0.25)', '#ffffff', 999);
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      rx -= w + 6 * scale;
    }
    ctx.font = `800 ${px * 1.35}px ${FONT}`;
    ctx.fillStyle = COLORS.text;
    const life = String(seat.life);
    ctx.fillText(life, rx, cy);
    rx -= ctx.measureText(life).width + 8 * scale;
    ctx.font = `700 ${px}px ${FONT}`;
    ctx.fillStyle = accent;
    ctx.fillText(seat.name, rx, cy);
    const nameWidth = ctx.measureText(seat.name).width;
    if (seat.active) {
      ctx.fillRect(rx - nameWidth, cy + px * 0.85, nameWidth, Math.max(1, 2 * scale));
    }
    rx -= nameWidth + (i === 0 ? 22 * scale : 0);
    if (i === 0) {
      ctx.fillStyle = 'rgba(255,255,255,0.14)';
      ctx.fillRect(rx + 10 * scale, cy - px, 1, px * 2);
    }
  });
}

/** A chosen basic land type's chip (labels.ts LandTypeTone): fill, border, text, as in replay.css. */
const LAND_TYPE_PILLS: Record<string, [string, string, string]> = {
  'land-plains': ['rgba(214,196,140,0.96)', 'rgba(255,246,214,0.8)', '#2a2414'],
  'land-island': ['rgba(26,110,196,0.96)', 'rgba(168,214,255,0.75)', '#ffffff'],
  'land-swamp': ['rgba(52,40,62,0.96)', 'rgba(196,176,214,0.65)', '#ffffff'],
  'land-mountain': ['rgba(196,58,40,0.96)', 'rgba(255,180,160,0.75)', '#ffffff'],
  'land-forest': ['rgba(36,120,58,0.96)', 'rgba(170,230,170,0.7)', '#ffffff'],
};

function drawLabels(ctx: CanvasRenderingContext2D, layout: FrameLayout, labels: readonly FrameLabel[]): void {
  const s = layout.scale;
  for (const label of labels) {
    const cx = label.x * s;
    const cy = layout.band + label.y * s;
    if (label.tone === 'pile') {
      drawPill(ctx, cx, cy, label.text, 10.5 * s, 600, 'rgba(8,12,16,0.62)', 'rgba(255,255,255,0.1)', COLORS.pileText, 999);
    } else if (label.tone === 'counters') {
      drawPill(ctx, cx, cy, label.text, 10 * s, 600, 'rgba(8,12,16,0.84)', 'rgba(240,198,108,0.4)', COLORS.gold, 999);
    } else if (label.tone === 'damage') {
      drawPill(ctx, cx, cy, label.text, 17 * s, 800, 'rgba(176,24,20,0.96)', 'rgba(255,168,158,0.75)', '#ffffff', 999);
    } else if (label.tone in LAND_TYPE_PILLS) {
      const [fill, border, ink] = LAND_TYPE_PILLS[label.tone];
      drawPill(ctx, cx, cy, label.text.toUpperCase(), 10 * s, 800, fill, border, ink, 999);
    } else if (label.tone === 'castable') {
      const plot = label.emphasis === true;
      const text = label.text.toUpperCase();
      drawPill(ctx, cx, cy, text, 9.5 * s, 600, 'rgba(8,12,16,0.86)', plot ? COLORS.goldBorder : 'rgba(159,208,255,0.55)', plot ? COLORS.gold : '#d8ecff', 999);
    } else if (label.tone === 'life-loss' || label.tone === 'life-gain') {
      const loss = label.tone === 'life-loss';
      drawPill(ctx, cx, cy, label.text, 38 * s, 900, loss ? 'rgba(176,24,20,0.96)' : 'rgba(30,120,56,0.96)', loss ? 'rgba(255,168,158,0.75)' : 'rgba(160,240,170,0.75)', '#ffffff', 999);
    } else if (label.tone === 'buff' || label.tone === 'debuff') {
      const buff = label.tone === 'buff';
      drawPill(ctx, cx, cy, label.text, 13.5 * s, 800, buff ? 'rgba(34,124,58,0.96)' : 'rgba(104,48,164,0.96)', buff ? 'rgba(160,240,170,0.7)' : 'rgba(214,176,255,0.7)', '#ffffff', 999);
    } else if (label.tone === 'removed') {
      drawPill(ctx, cx, cy, label.text.toUpperCase(), 10.5 * s, 700, 'rgba(18,20,24,0.92)', 'rgba(255,255,255,0.3)', '#f4f6f8', 999);
    } else if (label.tone === 'effect') {
      drawPill(ctx, cx, cy, label.text.toUpperCase(), 10 * s, 700, 'rgba(8,12,16,0.88)', 'rgba(242,153,74,0.65)', '#ffd9b3', 999);
    } else if (label.tone === 'loyalty') {
      drawPill(ctx, cx, cy, label.text, 14.5 * s, 700, COLORS.pill, COLORS.violetBorder, COLORS.violet, 7 * s);
    } else {
      const emphasis = label.emphasis === true;
      drawPill(
        ctx,
        cx,
        cy,
        label.text,
        14.5 * s,
        700,
        COLORS.pill,
        emphasis ? COLORS.goldBorder : COLORS.pillBorder,
        emphasis ? COLORS.gold : COLORS.text,
        999,
      );
    }
  }
}

interface StackRect {
  stackId: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Where the stack column's cards land (stage CSS px): full cards first, then compact rows. */
export function stackRects(layout: FrameLayout, items: readonly FrameStackItem[]): StackRect[] {
  if (!items.length) return [];
  const cardW = stackCardWidth(layout.sceneHeight);
  const fullH = cardW * 1.395 + 44;
  const chipH = 56;
  const gap = 8;
  const full = items.length === 1 ? 1 : 1;
  const chips = Math.min(items.length - full, 6);
  const total = full * fullH + chips * (chipH + gap) + (full && chips ? gap : 0);
  let y = Math.max(10, (layout.sceneHeight - total) / 2);
  const x = layout.sceneWidth - 10 - cardW;
  const rects: StackRect[] = [];
  items.slice(0, full + chips).forEach((item, i) => {
    const h = i < full ? fullH : chipH;
    rects.push({ stackId: item.stackId, x, y, w: cardW, h });
    y += h + gap;
  });
  return rects;
}

function drawCardImage(ctx: CanvasRenderingContext2D, image: CanvasImageSource | null, x: number, y: number, w: number, h: number, r: number): void {
  ctx.save();
  roundRect(ctx, x, y, w, h, r);
  ctx.clip();
  if (image) {
    try {
      ctx.drawImage(image, x, y, w, h);
    } catch {
      ctx.fillStyle = '#1b222c';
      ctx.fillRect(x, y, w, h);
    }
  } else {
    ctx.fillStyle = '#1b222c';
    ctx.fillRect(x, y, w, h);
  }
  ctx.restore();
}

function drawStack(ctx: CanvasRenderingContext2D, layout: FrameLayout, items: readonly FrameStackItem[], colors: FrameInput['colors']): StackRect[] {
  const rects = stackRects(layout, items);
  const s = layout.scale;
  rects.forEach((rect, i) => {
    const item = items[i];
    const x = rect.x * s;
    const y = layout.band + rect.y * s;
    const w = rect.w * s;
    const h = rect.h * s;
    const accent = item.mine ? colors.player : colors.opponent;
    roundRect(ctx, x, y, w, h, 10 * s);
    ctx.fillStyle = COLORS.panel;
    ctx.fill();
    ctx.lineWidth = item.top ? 2 * s : 1;
    ctx.strokeStyle = item.top ? accent : 'rgba(255,255,255,0.14)';
    ctx.stroke();
    const pad = 5 * s;
    if (i === 0) {
      const imgW = w - pad * 2;
      const imgH = imgW * 1.395;
      drawCardImage(ctx, item.image, x + pad, y + pad, imgW, imgH, 6 * s);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.font = `700 ${12.5 * s}px ${FONT}`;
      ctx.fillStyle = COLORS.text;
      ctx.fillText(ellipsize(ctx, item.name, imgW), x + pad + 2 * s, y + pad + imgH + 6 * s);
      ctx.font = `500 ${10.5 * s}px ${FONT}`;
      ctx.fillStyle = COLORS.muted;
      const kind = `${item.who} · ${item.kind}${item.top ? ' · resolves next' : ''}`;
      ctx.fillText(ellipsize(ctx, kind, imgW), x + pad + 2 * s, y + pad + imgH + 22 * s);
    } else {
      const thumbW = 32 * s;
      const thumbH = h - pad * 2;
      drawCardImage(ctx, item.image, x + pad, y + pad, thumbW, thumbH, 4 * s);
      const tx = x + pad + thumbW + 8 * s;
      const maxW = w - (tx - x) - pad;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.font = `700 ${11.5 * s}px ${FONT}`;
      ctx.fillStyle = COLORS.text;
      ctx.fillText(ellipsize(ctx, item.name, maxW), tx, y + pad + 6 * s);
      ctx.font = `500 ${10 * s}px ${FONT}`;
      ctx.fillStyle = COLORS.muted;
      ctx.fillText(ellipsize(ctx, `${item.who} · ${item.kind}`, maxW), tx, y + pad + 24 * s);
    }
    if (item.exit) {
      // Kept for the current action: dimmed under an exit stamp, as in the stack preview.
      roundRect(ctx, x, y, w, h, 10 * s);
      ctx.fillStyle = 'rgba(8,12,16,0.28)';
      ctx.fill();
      const stamp = EXIT_STAMPS[item.exit];
      ctx.save();
      ctx.translate(x + w / 2, y + Math.min(h * 0.34, h / 2));
      ctx.rotate((-8 * Math.PI) / 180);
      drawPill(ctx, 0, 0, stamp.text, 12 * s, 800, 'rgba(8,12,16,0.78)', stamp.color, stamp.color, 6 * s);
      ctx.restore();
    }
  });
  const hidden = items.length - rects.length;
  if (hidden > 0 && rects.length) {
    const last = rects[rects.length - 1];
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.font = `600 ${10.5 * s}px ${FONT}`;
    ctx.fillStyle = COLORS.muted;
    ctx.fillText(`+${hidden} more on the stack`, (last.x + last.w / 2) * s, layout.band + (last.y + last.h + 8) * s);
  }
  return rects;
}

function resolveEnd(end: FrameArrowEnd, rects: readonly StackRect[]): { x: number; y: number } | null {
  if ('stackId' in end) {
    const rect = rects.find((r) => r.stackId === end.stackId);
    return rect ? { x: rect.x, y: rect.y + rect.h / 2 } : null;
  }
  return end;
}

function drawArrows(ctx: CanvasRenderingContext2D, layout: FrameLayout, arrows: readonly FrameArrow[], rects: readonly StackRect[]): void {
  const s = layout.scale;
  ctx.save();
  ctx.translate(0, layout.band);
  ctx.scale(s, s);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (const arrow of arrows) {
    const from = resolveEnd(arrow.from, rects);
    const to = resolveEnd(arrow.to, rects);
    if (!from || !to) continue;
    const shape = arrowShape(Math.round(from.x), Math.round(from.y), Math.round(to.x), Math.round(to.y));
    const path = new Path2D(shape.d);
    ctx.globalAlpha = 0.35;
    ctx.strokeStyle = arrow.glow;
    ctx.lineWidth = 11;
    ctx.stroke(path);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = arrow.core;
    ctx.lineWidth = 3;
    ctx.stroke(path);
    const head = new Path2D(`M${shape.head.split(' ').join('L')}Z`);
    ctx.fillStyle = arrow.core;
    ctx.fill(head);
    if (arrow.reticle) {
      ctx.beginPath();
      ctx.arc(to.x, to.y, 9, 0, Math.PI * 2);
      ctx.lineWidth = 2;
      ctx.strokeStyle = arrow.core;
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawCaption(ctx: CanvasRenderingContext2D, layout: FrameLayout, caption: FrameCaption | null, colors: FrameInput['colors']): void {
  const { height, caption: band, scale } = layout;
  if (!band) return;
  const width = layout.width - layout.logWidth;
  const top = height - band;
  ctx.fillStyle = COLORS.band;
  ctx.fillRect(0, top, width, band);
  ctx.fillStyle = 'rgba(255,255,255,0.06)';
  ctx.fillRect(0, top, width, 1);
  if (!caption) return;
  const px = 13 * scale;
  const cy = top + band / 2;
  const dot = 4 * scale;
  const x0 = 14 * scale;
  ctx.fillStyle = caption.actor === 'player' ? colors.player : caption.actor === 'opponent' ? colors.opponent : COLORS.muted;
  ctx.beginPath();
  ctx.arc(x0 + dot, cy, dot, 0, Math.PI * 2);
  ctx.fill();
  ctx.font = `500 ${px}px ${FONT}`;
  ctx.fillStyle = COLORS.text;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(ellipsize(ctx, caption.text, width - x0 * 2 - dot * 4), x0 + dot * 2 + 8 * scale, cy);
}

function drawEnding(ctx: CanvasRenderingContext2D, layout: FrameLayout, ending: NonNullable<FrameInput['ending']>): void {
  const { band, scale, sceneHeight } = layout;
  const width = layout.width - layout.logWidth;
  const sceneH = sceneHeight * scale;
  ctx.fillStyle = 'rgba(6, 9, 13, 0.55)';
  ctx.fillRect(0, band, width, sceneH);
  const tone = ending.result === 'win' ? COLORS.win : ending.result === 'loss' ? COLORS.loss : COLORS.draw;
  const cx = width / 2;
  const cy = band + sceneH / 2;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = `600 ${13 * scale}px ${FONT}`;
  ctx.fillStyle = COLORS.muted;
  ctx.fillText('GAME OVER', cx, cy - 46 * scale);
  ctx.font = `800 ${56 * scale}px ${FONT}`;
  ctx.fillStyle = tone;
  ctx.fillText(ending.headline, cx, cy);
  if (ending.reason) {
    ctx.font = `500 ${16 * scale}px ${FONT}`;
    ctx.fillStyle = COLORS.text;
    ctx.fillText(ellipsize(ctx, ending.reason, width * 0.8), cx, cy + 46 * scale);
  }
}

/* --- Actions log column (stage CSS px; drawn under a scale transform) --- */

const LOG = {
  pad: 10,
  timeWidth: 34,
  gap: 8,
  bar: 3,
  rowPadY: 4,
  rowPadX: 10,
  lineHeight: 18,
  font: 13,
  timeFont: 11.5,
  metaFont: 12,
  headerHeight: 28,
  headerFont: 12,
  gapBetweenRows: 2,
  /** The current row sits this far down the column. */
  activeAt: 0.58,
} as const;

interface LogSpan {
  text: string;
  style: 'text' | 'card' | 'meta';
  width: number;
}

type LogLine = LogSpan[];

const lineCache = new WeakMap<LogItem, { width: number; lines: LogLine[] }>();

function logFont(style: LogSpan['style']): string {
  if (style === 'card') return `700 ${LOG.font}px ${FONT}`;
  if (style === 'meta') return `700 ${LOG.metaFont}px ${FONT}`;
  return `500 ${LOG.font}px ${FONT}`;
}

/** Greedy word wrap of a row's parts into lines of styled spans (cached per row and width). */
function wrapParts(ctx: CanvasRenderingContext2D, item: LogItem, parts: readonly LogPart[], width: number): LogLine[] {
  const cached = lineCache.get(item);
  if (cached && cached.width === width) return cached.lines;
  const spans: Array<{ text: string; style: LogSpan['style']; glue: boolean }> = [];
  for (const part of parts) {
    if (part.kind === 'card') {
      spans.push({ text: formatCardName(part.text), style: 'card', glue: false });
      if (part.meta) spans.push({ text: part.meta, style: 'meta', glue: false });
    } else {
      for (const word of part.text.split(/(\s+)/)) {
        if (!word) continue;
        if (/^\s+$/.test(word)) spans.push({ text: ' ', style: 'text', glue: true });
        else spans.push({ text: word, style: 'text', glue: false });
      }
    }
  }
  const lines: LogLine[] = [];
  let line: LogLine = [];
  let used = 0;
  const measure = (text: string, style: LogSpan['style']) => {
    ctx.font = logFont(style);
    return ctx.measureText(text).width;
  };
  for (const span of spans) {
    const w = measure(span.text, span.style);
    if (span.glue) {
      if (line.length) {
        line.push({ text: ' ', style: 'text', width: w });
        used += w;
      }
      continue;
    }
    if (used + w > width && line.length) {
      while (line.length && line[line.length - 1].text === ' ') line.pop();
      lines.push(line);
      line = [];
      used = 0;
    }
    line.push({ text: span.text, style: span.style, width: w });
    used += w;
  }
  while (line.length && line[line.length - 1].text === ' ') line.pop();
  if (line.length) lines.push(line);
  if (!lines.length) lines.push([]);
  lineCache.set(item, { width, lines });
  return lines;
}

function rowHeight(lines: number): number {
  return LOG.rowPadY * 2 + lines * LOG.lineHeight;
}

function drawLogRow(ctx: CanvasRenderingContext2D, item: LogItem, y: number, panelWidth: number, lines: LogLine[], active: boolean, playerSeat: number): void {
  if (item.type === 'turn') {
    ctx.fillStyle = '#1a222c';
    ctx.fillRect(0, y, panelWidth, LOG.headerHeight);
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fillRect(0, y, panelWidth, 1);
    ctx.fillRect(0, y + LOG.headerHeight - 1, panelWidth, 1);
    ctx.font = `700 ${LOG.headerFont}px ${FONT}`;
    ctx.fillStyle = COLORS.draw;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const whose = item.seat === null ? '' : item.seat === playerSeat ? ' – YOUR TURN' : " – OPPONENT'S TURN";
    ctx.fillText(item.turn === null ? 'PRE-GAME' : `TURN ${item.turn}${whose}`, LOG.pad + 2, y + LOG.headerHeight / 2);
    return;
  }
  const h = rowHeight(lines.length);
  const x0 = LOG.pad;
  const w = panelWidth - LOG.pad * 2;
  if (active) {
    ctx.fillStyle = 'rgba(43, 179, 163, 0.16)';
    roundRect(ctx, x0, y, w, h, 3);
    ctx.fill();
    ctx.strokeStyle = 'rgba(43, 179, 163, 0.65)';
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  ctx.fillStyle = item.actor === 'player' ? 'rgba(76,195,138,0.8)' : item.actor === 'opponent' ? 'rgba(229,72,77,0.8)' : 'rgba(255,255,255,0.14)';
  ctx.fillRect(x0, y, LOG.bar, h);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  const baseline = y + LOG.rowPadY + LOG.lineHeight * 0.74;
  ctx.font = `500 ${LOG.timeFont}px ${FONT}`;
  ctx.fillStyle = COLORS.muted;
  ctx.fillText(formatClock(item.t), x0 + LOG.rowPadX, baseline);
  let lx = x0 + LOG.rowPadX + LOG.timeWidth + LOG.gap;
  const left = lx;
  lines.forEach((line, i) => {
    lx = left;
    const ly = baseline + i * LOG.lineHeight;
    for (const span of line) {
      ctx.font = logFont(span.style);
      ctx.fillStyle = span.style === 'card' ? COLORS.draw : span.style === 'meta' ? COLORS.muted : item.actor === 'system' ? COLORS.muted : COLORS.text;
      ctx.fillText(span.text, lx, ly);
      lx += span.width + (span.style === 'meta' ? 0 : 0);
      if (span.style === 'card') lx += 4;
    }
  });
}

function drawLog(ctx: CanvasRenderingContext2D, layout: FrameLayout, log: FrameLog): void {
  const { scale, logWidth, height } = layout;
  if (!logWidth) return;
  const panelX = layout.width - logWidth;
  const panelWidth = logWidth / scale;
  const panelHeight = height / scale;
  ctx.save();
  ctx.translate(panelX, 0);
  ctx.scale(scale, scale);
  ctx.fillStyle = COLORS.band;
  ctx.fillRect(0, 0, panelWidth, panelHeight);
  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  ctx.fillRect(0, 0, 1, panelHeight);
  // Header, level with the HUD band.
  const header = BAND_PX;
  ctx.font = `700 ${11.5}px ${FONT}`;
  ctx.fillStyle = COLORS.muted;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText('ACTIONS', LOG.pad + 2, header / 2);
  ctx.fillStyle = 'rgba(255,255,255,0.06)';
  ctx.fillRect(0, header - 1, panelWidth, 1);
  // Rows: the active one at a fixed height, the rest filling up and down.
  ctx.beginPath();
  ctx.rect(0, header, panelWidth, panelHeight - header);
  ctx.clip();
  const textWidth = panelWidth - LOG.pad * 2 - LOG.rowPadX - LOG.timeWidth - LOG.gap - 6;
  const linesOf = (item: LogItem): LogLine[] => (item.type === 'turn' ? [] : wrapParts(ctx, item, item.parts, textWidth));
  const heightOf = (item: LogItem) => (item.type === 'turn' ? LOG.headerHeight : rowHeight(linesOf(item).length));
  const { items } = log;
  const active = Math.min(items.length - 1, Math.max(-1, log.activeIndex));
  const draw = (index: number, y: number) => {
    const item = items[index];
    drawLogRow(ctx, item, y, panelWidth, linesOf(item), index === active, log.playerSeat);
  };
  if (!items.length) {
    ctx.restore();
    return;
  }
  const anchor = active >= 0 ? active : 0;
  let y = active >= 0 ? header + (panelHeight - header) * LOG.activeAt - heightOf(items[anchor]) / 2 : header + 6;
  y = Math.max(header + 6, y);
  // Above the anchor.
  let yUp = y;
  for (let i = anchor - 1; i >= 0 && yUp > header; i -= 1) {
    yUp -= heightOf(items[i]) + LOG.gapBetweenRows;
    draw(i, yUp);
  }
  // The anchor and below.
  let yDown = y;
  for (let i = anchor; i < items.length && yDown < panelHeight; i += 1) {
    draw(i, yDown);
    yDown += heightOf(items[i]) + LOG.gapBetweenRows;
  }
  ctx.restore();
}

/** Paints the whole frame into `ctx` (a canvas of `layout.width` × `layout.height`). */
export function composeFrame(ctx: CanvasRenderingContext2D, layout: FrameLayout, input: FrameInput): void {
  const { width, height, band, scale, sceneWidth, sceneHeight } = layout;
  ctx.save();
  ctx.globalAlpha = 1;
  ctx.fillStyle = COLORS.background;
  ctx.fillRect(0, 0, width, height);
  try {
    ctx.drawImage(input.scene, 0, band, sceneWidth * scale, sceneHeight * scale);
  } catch {
    // A lost context leaves the background.
  }
  drawLabels(ctx, layout, input.labels);
  const rects = drawStack(ctx, layout, input.stack, input.colors);
  drawArrows(ctx, layout, input.arrows, rects);
  if (input.ending) drawEnding(ctx, layout, input.ending);
  drawHud(ctx, layout, input.hud, input.colors);
  drawCaption(ctx, layout, input.caption, input.colors);
  if (input.log && layout.logWidth) drawLog(ctx, layout, input.log);
  ctx.restore();
}
