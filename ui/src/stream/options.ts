import type { Period } from './liveView';
/**
 * Stream Kit options. Everything a widget needs is in its URL, so OBS keeps
 * the settings with the browser source and the tracker stores nothing.
 */

export type WidgetId =
  | 'overlay'
  | 'deck'
  | 'scorebug'
  | 'record'
  | 'games'
  | 'deckstats'
  | 'matchup'
  | 'opponent'
  | 'lands'
  | 'result'
  | 'spotlight'
  | 'break';
export type Background = 'solid' | 'glass' | 'none';
export type DeckSort = 'mana' | 'odds' | 'name';
export type SpotlightWho = 'both' | 'opponent' | 'you';
export type SideboardPlace = 'right' | 'left' | 'below' | 'off';

/**
 * Each widget's optional parts, in display order, with their Settings label.
 * Everything shows unless the link's `hide` lists it, so a streamer running
 * several widgets can turn off what another one already shows.
 */
export const WIDGET_PARTS: Record<WidgetId, ReadonlyArray<readonly [string, string]>> = {
  overlay: [
    ['h2h', 'Head-to-head'],
    ['turn', 'Turn number'],
    ['drops', 'Land-drop odds'],
    ['order', 'Play / draw'],
    ['library', 'Library count'],
  ],
  deck: [
    ['library', 'Library count'],
    ['odds', 'Land next draw'],
  ],
  scorebug: [
    ['yourdeck', 'Your deck'],
    ['theirdeck', 'Their deck'],
    ['timer', 'Turn timer'],
    ['match', 'Bo3 score'],
  ],
  record: [
    ['turn', 'Play / draw'],
    ['rank', 'Rank'],
    ['deck', 'Deck record'],
  ],
  games: [
    ['record', 'Record'],
    ['turn', 'Play / draw totals'],
    ['order', 'Play / draw per game'],
    ['details', 'Turns and length'],
  ],
  deckstats: [
    ['queues', 'Ranked / casual'],
    ['turn', 'Play / draw'],
    ['form', 'Last 10 games'],
  ],
  matchup: [
    ['order', 'Play / draw'],
    ['game', 'Bo3 game'],
    ['turn', 'Turn number'],
    ['h2h', 'Head-to-head'],
  ],
  opponent: [
    ['record', 'Your record vs their deck'],
    ['art', 'Card art'],
  ],
  lands: [
    ['odds', 'Next draw odds'],
    ['reason', 'Explanation'],
  ],
  result: [
    ['match', 'Match score'],
    ['details', 'Turns, length, play / draw'],
    ['facts', 'Highlights'],
    ['record', 'Record'],
  ],
  spotlight: [],
  break: [
    ['session', 'Record'],
    ['results', 'Results'],
    ['deck', 'Deck'],
    ['rank', 'Rank climb'],
  ],
};

/** Whether a widget shows one of its optional parts. */
export function shows(options: Pick<StreamOptions, 'hide'>, part: string): boolean {
  return !options.hide.includes(part);
}

/** Longest intermission title. */
export const TITLE_MAX = 40;

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
  /** Record widget: this session's games or today's. */
  period: Period;
  /** The widget's optional parts that are turned off (WIDGET_PARTS). */
  hide: string[];
  /** Intermission card: its heading. */
  title: string;
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
    options: ['opacity', 'sideboard', 'sort', 'lands', 'names', 'opponent', 'idle', 'hide'],
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
    options: ['idle', 'sort', 'lands', 'hide'],
  },
  {
    id: 'scorebug',
    title: 'Scorebug',
    description: 'A TV-style bar: both players, life totals that flash when they change, the turn and whose it is, and the match score in Bo3.',
    width: 900,
    height: 110,
    options: ['opponent', 'idle', 'hide'],
  },
  {
    id: 'record',
    title: 'Record',
    description: 'Wins and losses this session or today, win rate, on the play and on the draw, rank, and your record with the current deck.',
    width: 440,
    height: 110,
    options: ['period', 'hide'],
  },
  {
    id: 'games',
    title: 'Recent games',
    description: 'Today’s games, newest first: win or loss, play or draw, deck, opponent, turns and length, under your session’s or today’s record.',
    width: GAMES_SIZE.width,
    height: GAMES_SIZE.head + GAMES_SIZE.record + 10 * GAMES_SIZE.row,
    options: ['count', 'opponent', 'period', 'hide'],
    size: (options) => ({
      width: GAMES_SIZE.width,
      height: GAMES_SIZE.head + (shows(options, 'record') ? GAMES_SIZE.record : 0) + options.count * GAMES_SIZE.row,
    }),
  },
  {
    id: 'deckstats',
    title: 'Deck stats',
    description: 'The deck you’re playing: its win rate and record, with ranked and casual, play and draw, and recent form.',
    width: 440,
    height: 230,
    options: ['idle', 'hide'],
    // The headline, then a strip for ranked/casual and play/draw, and the recent-form row.
    size: (options) => ({
      width: 440,
      height:
        100 +
        (shows(options, 'queues') || shows(options, 'turn') ? 85 : 0) +
        (shows(options, 'form') ? 45 : 0),
    }),
  },
  {
    id: 'matchup',
    title: 'Matchup',
    description: 'Who you’re playing, their colors and likely deck, your record against them, play or draw.',
    width: 440,
    height: 150,
    options: ['idle', 'opponent', 'hide'],
  },
  {
    id: 'opponent',
    title: 'What they’re on',
    description: 'The opponent’s likely deck and your record against it, then every card they’ve played this game, grouped by type.',
    width: 360,
    height: 560,
    options: ['lands', 'opponent', 'idle', 'hide'],
  },
  {
    id: 'lands',
    title: 'Flood / screw meter',
    description: 'Lands you’ve seen against what your deck should give you, Game Detail’s flood or screw verdict, and the chance the next draw is a land.',
    width: 380,
    height: 190,
    options: ['idle', 'hide'],
  },
  {
    id: 'result',
    title: 'Game result',
    description: 'A Victory or Defeat card for a few seconds after each game, with turns, length, the match score and a highlight.',
    width: 560,
    height: 300,
    options: ['seconds', 'opponent', 'period', 'hide'],
  },
  {
    id: 'spotlight',
    title: 'Card spotlight',
    description: 'A large image of each card as it’s cast, so viewers can read it, then it fades.',
    width: 300,
    height: 470,
    options: ['who', 'seconds'],
  },
  {
    id: 'break',
    title: 'Intermission',
    description: 'For a “be right back” or between-games scene: your title, your session’s or today’s record and results, the deck and your rank climb.',
    width: 560,
    height: 380,
    options: ['title', 'period', 'hide'],
    size: (options) => ({
      width: 560,
      height: 110 + WIDGET_PARTS.break.filter(([part]) => shows(options, part)).length * 66,
    }),
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
  period: 'session',
  hide: [],
  title: 'Be right back',
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

function text(value: string | null, fallback: string): string {
  if (value === null) return fallback;
  return value.replace(/\s+/g, ' ').trim().slice(0, TITLE_MAX);
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

/** The widget's parts listed in `hide`, in its own order; unknown names are dropped. */
function hiddenParts(params: URLSearchParams, widget: WidgetId | null): string[] {
  if (!widget) return [];
  const listed = new Set((params.get('hide') ?? '').split(',').map((part) => part.trim()));
  // Recent games links from 0.7.5–0.7.6 hid the session record with record=0.
  if (widget === 'games' && params.get('record') !== null && !flag(params.get('record'), true)) listed.add('record');
  return WIDGET_PARTS[widget].map(([part]) => part).filter((part) => listed.has(part));
}

export function parseStreamOptions(search: string): StreamOptions {
  const params = new URLSearchParams(search);
  const d = DEFAULT_OPTIONS;
  const widget = params.get('widget');
  const known = WIDGETS.some((info) => info.id === widget) ? (widget as WidgetId) : null;
  return {
    widget: known,
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
    period: pick(params.get('period'), ['session', 'today'] as const, d.period),
    hide: hiddenParts(params, known),
    title: text(params.get('title'), d.title),
  };
}

function encode(value: StreamOptions[keyof StreamOptions]): string {
  if (typeof value === 'boolean') return value ? '1' : '0';
  if (Array.isArray(value)) return value.join(',');
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
    if (encode(merged[key]) !== encode(DEFAULT_OPTIONS[key])) {
      params.set(key, encode(merged[key]));
    }
  }
  if (extra.demo) params.set('demo', '1');
  if (extra.preview) params.set('preview', '1');
  return `${origin.replace(/\/$/, '')}/stream.html?${params.toString()}`;
}
