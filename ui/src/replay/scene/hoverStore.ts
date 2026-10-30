/** Tiny external store for the hovered card, so pointer moves re-render only the preview. */
import type { CardKey, Zone } from '../types';

/** A card tucked under the hovered permanent, listed in its preview. */
export interface HoverUnder {
  card: CardKey | null;
  name: string;
  zone: Zone;
}

export interface HoverInfo {
  key: string;
  card: CardKey | null;
  name: string;
  /** Cards tucked under the hovered card (auras, equipment, cards it exiled), bottom first. */
  under?: readonly HoverUnder[];
  /** A short status line under the image (a summoning-sick creature's), when set. */
  note?: string;
  /** Viewport coordinates of the pointer or the anchor's edge. */
  x: number;
  y: number;
  /** 'scene': follow the pointer; 'log': open to the left of the anchor. */
  source: 'scene' | 'log';
}

export class HoverStore {
  private current: HoverInfo | null = null;
  private readonly listeners = new Set<() => void>();

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly get = (): HoverInfo | null => this.current;

  set(info: HoverInfo | null): void {
    const prev = this.current;
    if (prev === info) return;
    if (prev && info && prev.key === info.key && prev.x === info.x && prev.y === info.y) return;
    this.current = info;
    for (const listener of [...this.listeners]) listener();
  }

  /** Clears only when `key` is still the hovered item (pointer-out ordering is not guaranteed). */
  clear(key: string): void {
    if (this.current?.key === key) this.set(null);
  }
}

const GAP = 16;
const EDGE = 12;
/** The "under this card" list: most rows shown, and their CSS heights (replay.css `.replay-preview-under`). */
export const UNDER_MAX_ROWS = 6;
const UNDER_HEADER_PX = 26;
const UNDER_ROW_PX = 34;
const UNDER_MORE_PX = 20;

/** Height the status note adds below the image (replay.css `.replay-preview-note`). */
export const NOTE_PX = 40;
/** What a summoning-sick creature's preview says. */
export const SICK_NOTE = "Summoning sick: can't attack or use {T} abilities until its controller's next turn.";

/** Height the tucked-card list adds below the image. */
export function underListHeight(count: number): number {
  if (count <= 0) return 0;
  return UNDER_HEADER_PX + Math.min(count, UNDER_MAX_ROWS) * UNDER_ROW_PX + (count > UNDER_MAX_ROWS ? UNDER_MORE_PX : 0);
}

/** One picture beside the preview: a distinct card in the tucked stack and how many copies are there. */
export interface UnderPicture {
  card: CardKey;
  name: string;
  count: number;
}

/** Pictures shown beside the preview: at most this many distinct cards. */
export const PICTURES_MAX = 4;
const PICTURE_GAP = 8;
/** With three or four distinct cards the pictures shrink into a 2×2 grid. */
const PICTURE_SCALE = 0.62;
const PICTURE_MORE_PX = 20;
const IMAGE_RATIO = 680 / 488;

/** The distinct known cards in a tucked stack, top of the stack first, with their copy counts. */
export function underPictures(under: readonly HoverUnder[]): UnderPicture[] {
  const out: UnderPicture[] = [];
  for (let i = under.length - 1; i >= 0; i -= 1) {
    const item = under[i];
    if (!item.card || !item.name) continue;
    const seen = out.find((p) => p.card === item.card);
    if (seen) seen.count += 1;
    else out.push({ card: item.card, name: item.name, count: 1 });
  }
  return out;
}

export interface PreviewBox {
  left: number;
  top: number;
  /** Whole box, pictures included. */
  width: number;
  /** The hovered card's column (image plus list). */
  hostWidth: number;
  /** Each picture's width and the grid's column count (0 when there are none). */
  pictureWidth: number;
  pictureColumns: number;
}

/** Fixed-position box for the preview: beside the pointer (scene) or left of the log. */
export function previewPosition(info: HoverInfo, viewport: { width: number; height: number }): PreviewBox {
  const hostWidth = Math.min(300, Math.max(240, viewport.width * 0.22));
  const under = info.under ?? [];
  const pictures = underPictures(under);
  const shown = Math.min(pictures.length, PICTURES_MAX);
  const pictureColumns = shown === 0 ? 0 : Math.min(shown, 2);
  const pictureRows = shown <= 2 ? 1 : 2;
  const pictureWidth = shown <= 2 ? hostWidth - 10 : Math.round((hostWidth - 10) * PICTURE_SCALE);
  const picturesWidth = pictureColumns ? pictureColumns * pictureWidth + (pictureColumns - 1) * PICTURE_GAP : 0;
  const width = hostWidth + (pictureColumns ? PICTURE_GAP + picturesWidth : 0);
  const hostHeight = (hostWidth - 10) * IMAGE_RATIO + 10 + (info.note ? NOTE_PX : 0) + underListHeight(under.length);
  const picturesHeight = pictureColumns
    ? pictureRows * pictureWidth * IMAGE_RATIO + (pictureRows - 1) * PICTURE_GAP + 10 + (pictures.length > shown ? PICTURE_MORE_PX : 0)
    : 0;
  const height = Math.max(hostHeight, picturesHeight);
  let left: number;
  let top: number;
  if (info.source === 'log') {
    left = info.x - GAP - width;
    top = info.y - height / 2;
  } else {
    left = info.x + GAP;
    if (left + width > viewport.width - EDGE) left = info.x - GAP - width;
    top = info.y - height * 0.4;
  }
  left = Math.max(EDGE, Math.min(left, viewport.width - width - EDGE));
  top = Math.max(EDGE, Math.min(top, viewport.height - height - EDGE));
  return { left, top, width, hostWidth, pictureWidth, pictureColumns };
}

