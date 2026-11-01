/**
 * Stream Kit options. Everything a widget needs is in its URL, so OBS keeps
 * the settings with the browser source and the tracker stores nothing.
 */

export type WidgetId = 'overlay' | 'deck' | 'record' | 'games' | 'matchup' | 'spotlight';
export type Background = 'solid' | 'glass' | 'none';
export type DeckSort = 'mana' | 'odds' | 'name';
export type SpotlightWho = 'both' | 'opponent' | 'you';
export type SideboardPlace = 'right' | 'left' | 'below' | 'off';

export interface StreamOptions {
  widget: WidgetId | null;
  /** Size of everything, percent. */
  scale: number;
  bg: Background;
  /** The small "Tapps Tracker" credit. */
  brand: boolean;
  /** Sample data, for placing sources without a game running. */
  demo: boolean;
  /** A checkerboard behind the widget, for a normal browser tab. */
  preview: boolean;
  /** Keep game widgets up between games (the last game stays on screen). */
  idle: 'hide' | 'show';
  sort: DeckSort;
  lands: 'grouped' | 'all';
  /** Show the opponent's Arena name on the matchup widget. */
  opponent: boolean;
  who: SpotlightWho;
  /** How long a spotlighted card stays up. */
  seconds: number;
  /** Full overlay: the in-game overlay's background slider, 0–100 (0 = text only). */
  opacity: number;
  /** Full overlay: where the sideboard goes. */
  sideboard: SideboardPlace;
  /** Full overlay: card names in their type colour, or plain white. */
  names: 'type' | 'white';
  /** Recent games: how many to list, newest first. */
  count: number;
  /** Recent games: the session record in the heading. */
  record: boolean;
}

export interface WidgetInfo {
  id: WidgetId;
  title: string;
  description: string;
  /** Suggested OBS source size, before scale. */
  width: number;
  height: number;
  /** Which options this widget reads (the URL carries only these). */
  options: Array<keyof StreamOptions>;
  /** Shared options it reads, when not all of them (the full overlay has its own background). */
  shared?: Array<keyof StreamOptions>;
  /** Suggested size when it depends on the options. */
  size?: (options: StreamOptions) => { width: number; height: number };
}

/** Recent games: the heading, then one row per game (base px, before scale). */
const GAMES_SIZE = { width: 380, head: 50, record: 40, row: 50 };

/** The full overlay's panel and the sideboard beside it (base px, before scale). */
const OVERLAY_SIZE = { width: 320, height: 960, side: 200, below: 360 };

export const WIDGETS: WidgetInfo[] = [
  {
    id: 'overlay',
    title: 'Full overlay',
    description:
      'The in-game overlay as one source: deck, land-drop odds, every card left with its odds, and the sideboard.',
    width: OVERLAY_SIZE.width + OVERLAY_SIZE.side,
    height: OVERLAY_SIZE.height,
    options: ['opacity', 'sideboard', 'sort', 'lands', 'names', 'opponent', 'idle'],
    shared: ['scale', 'brand'],
    size: (options) => {
      if (options.sideboard === 'below') return { width: OVERLAY_SIZE.width, height: OVERLAY_SIZE.height + OVERLAY_SIZE.below };
      if (options.sideboard === 'off') return { width: OVERLAY_SIZE.width, height: OVERLAY_SIZE.height };
      return { width: OVERLAY_SIZE.width + OVERLAY_SIZE.side, height: OVERLAY_SIZE.height };
    },
  },
  {
    id: 'deck',
    title: 'Deck tracker',
    description: 'Your deck with copies left in the library and the odds of drawing each card next.',
    width: 320,
    height: 720,
    options: ['idle', 'sort', 'lands'],
  },
  {
    id: 'record',
    title: 'Session record',
    description: 'Wins and losses this session, win rate, rank, and today’s record with the current deck.',
    width: 380,
    height: 110,
    options: [],
  },
  {
    id: 'games',
    title: 'Recent games',
    description: 'Today’s games, newest first: win or loss, play or draw, deck, opponent, turns and length, under the session record.',
    width: GAMES_SIZE.width,
    height: GAMES_SIZE.head + GAMES_SIZE.record + 10 * GAMES_SIZE.row,
    options: ['count', 'record', 'opponent'],
    size: (options) => ({
      width: GAMES_SIZE.width,
      height: GAMES_SIZE.head + (options.record ? GAMES_SIZE.record : 0) + options.count * GAMES_SIZE.row,
    }),
  },
  {
    id: 'matchup',
    title: 'Matchup',
    description: 'Who you’re playing, their colors and likely deck, your record against them, play or draw.',
    width: 440,
    height: 150,
    options: ['idle', 'opponent'],
  },
  {
    id: 'spotlight',
    title: 'Card spotlight',
    description: 'A large image of each card as it’s cast, so viewers can read it, then it fades.',
    width: 300,
    height: 470,
    options: ['who', 'seconds'],
  },
];

export const DEFAULT_OPTIONS: StreamOptions = {
  widget: null,
  scale: 100,
  bg: 'solid',
  brand: true,
  demo: false,
  preview: false,
  idle: 'hide',
  sort: 'mana',
  lands: 'grouped',
  opponent: true,
  who: 'both',
  seconds: 8,
  opacity: 60,
  sideboard: 'right',
  names: 'type',
  count: 10,
  record: true,
};

/** Options every widget reads. */
const COMMON: Array<keyof StreamOptions> = ['scale', 'bg', 'brand'];

const SCALE_RANGE: [number, number] = [50, 300];
const SECONDS_RANGE: [number, number] = [3, 30];
const OPACITY_RANGE: [number, number] = [0, 100];
const COUNT_RANGE: [number, number] = [1, 25];

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function flag(value: string | null, fallback: boolean): boolean {
  if (value === null) return fallback;
  return !['0', 'false', 'no', 'off'].includes(value.toLowerCase());
}

function bounded(value: string | null, [low, high]: [number, number], fallback: number): number {
  if (value === null || value.trim() === '') return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(high, Math.max(low, Math.round(parsed)));
}

export function widgetInfo(id: WidgetId): WidgetInfo {
  return WIDGETS.find((widget) => widget.id === id)!;
}

/** Suggested OBS source size for a widget with these options, scale applied. */
export function widgetSize(widget: WidgetInfo, options: StreamOptions): { width: number; height: number } {
  const base = widget.size ? widget.size(options) : { width: widget.width, height: widget.height };
  const scale = options.scale / 100;
  return { width: Math.round(base.width * scale), height: Math.round(base.height * scale) };
}

export function parseStreamOptions(search: string): StreamOptions {
  const params = new URLSearchParams(search);
  const d = DEFAULT_OPTIONS;
  const widget = params.get('widget');
  return {
    widget: WIDGETS.some((info) => info.id === widget) ? (widget as WidgetId) : null,
    scale: bounded(params.get('scale'), SCALE_RANGE, d.scale),
    bg: pick(params.get('bg'), ['solid', 'glass', 'none'] as const, d.bg),
    brand: flag(params.get('brand'), d.brand),
    demo: flag(params.get('demo'), d.demo),
    preview: flag(params.get('preview'), d.preview),
    idle: pick(params.get('idle'), ['hide', 'show'] as const, d.idle),
    sort: pick(params.get('sort'), ['mana', 'odds', 'name'] as const, d.sort),
    lands: pick(params.get('lands'), ['grouped', 'all'] as const, d.lands),
    opponent: flag(params.get('opponent'), d.opponent),
    who: pick(params.get('who'), ['both', 'opponent', 'you'] as const, d.who),
    seconds: bounded(params.get('seconds'), SECONDS_RANGE, d.seconds),
    opacity: bounded(params.get('opacity'), OPACITY_RANGE, d.opacity),
    sideboard: pick(params.get('sideboard'), ['right', 'left', 'below', 'off'] as const, d.sideboard),
    names: pick(params.get('names'), ['type', 'white'] as const, d.names),
    count: bounded(params.get('count'), COUNT_RANGE, d.count),
    record: flag(params.get('record'), d.record),
  };
}

function encode(value: StreamOptions[keyof StreamOptions]): string {
  if (typeof value === 'boolean') return value ? '1' : '0';
  return String(value);
}

/**
 * The browser-source URL for one widget: only the options it reads and only
 * where they differ from the defaults, so URLs stay short and readable.
 */
export function streamUrl(
  origin: string,
  widget: WidgetId,
  options: Partial<StreamOptions> = {},
  extra: { demo?: boolean; preview?: boolean } = {},
): string {
  const params = new URLSearchParams({ widget });
  const merged = { ...DEFAULT_OPTIONS, ...options };
  const info = widgetInfo(widget);
  for (const key of [...(info.shared ?? COMMON), ...info.options]) {
    if (merged[key] !== DEFAULT_OPTIONS[key]) {
      params.set(key, encode(merged[key]));
    }
  }
  if (extra.demo) params.set('demo', '1');
  if (extra.preview) params.set('preview', '1');
  return `${origin.replace(/\/$/, '')}/stream.html?${params.toString()}`;
}
