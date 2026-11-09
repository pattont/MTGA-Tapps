import { describe, expect, it } from 'vitest';
import { DEFAULT_OPTIONS, parseStreamOptions, streamUrl, widgetInfo, widgetSize } from './options';

describe('parseStreamOptions', () => {
  it('reads every option and falls back to defaults', () => {
    expect(parseStreamOptions('')).toEqual(DEFAULT_OPTIONS);
    const options = parseStreamOptions(
      '?widget=deck&scale=150&bg=glass&brand=0&demo=1&preview=1&idle=show&sort=odds&lands=all&opponent=0&who=opponent&seconds=12',
    );
    expect(options).toEqual({
      widget: 'deck',
      scale: 150,
      bg: 'glass',
      brand: false,
      demo: true,
      preview: true,
      idle: 'show',
      sort: 'odds',
      lands: 'all',
      opponent: false,
      who: 'opponent',
      seconds: 12,
      opacity: 60,
      sideboard: 'right',
      names: 'type',
      count: 10,
      period: 'session',
      hide: [],
      title: 'Be right back',
    });
  });

  it('reads hidden parts and text options', () => {
    const options = parseStreamOptions('?widget=deckstats&hide=form,bogus,queues&title=%20%20Back%20%20soon%20');
    // The widget's own parts, in its order; unknown names are dropped.
    expect(options.hide).toEqual(['queues', 'form']);
    expect(options.title).toBe('Back soon');
    // Parts belong to a widget: another widget's names, or no widget, hide nothing.
    expect(parseStreamOptions('?widget=record&hide=form,rank').hide).toEqual(['rank']);
    expect(parseStreamOptions('?hide=rank').hide).toEqual([]);
    // Recent games links from before `hide` turned the session record off with record=0.
    expect(parseStreamOptions('?widget=games&record=0').hide).toEqual(['record']);
    expect(parseStreamOptions('?widget=games&record=1').hide).toEqual([]);
    expect(parseStreamOptions(`?title=${'x'.repeat(80)}`).title).toHaveLength(40);
  });

  it('rejects unknown values and clamps numbers', () => {
    const options = parseStreamOptions('?widget=chat&scale=9000&bg=neon&sort=random&seconds=-4&who=everyone');
    expect(options.widget).toBeNull();
    expect(options.scale).toBe(300);
    expect(options.bg).toBe('solid');
    expect(options.sort).toBe('mana');
    expect(options.seconds).toBe(3);
    expect(options.who).toBe('both');
    expect(parseStreamOptions('?scale=abc').scale).toBe(100);
    expect(parseStreamOptions('?opacity=140&sideboard=top&names=pink')).toMatchObject({ opacity: 100, sideboard: 'right', names: 'type' });
    expect(parseStreamOptions('?opacity=0&sideboard=below&names=white')).toMatchObject({ opacity: 0, sideboard: 'below', names: 'white' });
    expect(parseStreamOptions('?count=0').count).toBe(1);
    expect(parseStreamOptions('?count=99').count).toBe(25);
    expect(parseStreamOptions('?count=5').count).toBe(5);
  });
});

describe('streamUrl', () => {
  it('carries only the widget’s own options that differ from the defaults', () => {
    expect(streamUrl('http://127.0.0.1:8765/', 'record')).toBe('http://127.0.0.1:8765/stream.html?widget=record');
    const url = streamUrl('http://127.0.0.1:8765', 'deck', { scale: 125, sort: 'odds', who: 'you', brand: false });
    // `who` belongs to the spotlight, so the deck URL leaves it out.
    expect(url).toBe('http://127.0.0.1:8765/stream.html?widget=deck&scale=125&brand=0&sort=odds');
    expect(parseStreamOptions(new URL(url).search)).toMatchObject({ widget: 'deck', scale: 125, brand: false, sort: 'odds', who: 'both' });
  });

  it('gives the full overlay its own background instead of the shared one', () => {
    const url = streamUrl('http://x', 'overlay', { bg: 'glass', opacity: 35, sideboard: 'below', names: 'white', opponent: false, seconds: 5 });
    expect(url).toBe('http://x/stream.html?widget=overlay&opacity=35&sideboard=below&names=white&opponent=0');
  });

  it('sizes recent games by how many it lists', () => {
    const games = widgetInfo('games');
    expect(streamUrl('http://x', 'games', { count: 3, opponent: false })).toBe('http://x/stream.html?widget=games&count=3&opponent=0');
    expect(widgetSize(games, DEFAULT_OPTIONS)).toEqual({ width: 380, height: 590 });
    expect(widgetSize(games, { ...DEFAULT_OPTIONS, count: 1, hide: ['record'] })).toEqual({ width: 380, height: 100 });
    expect(streamUrl('http://x', 'games', { hide: ['record'] })).toBe('http://x/stream.html?widget=games&hide=record');
  });

  it('sizes the full overlay for where its sideboard goes', () => {
    const overlay = widgetInfo('overlay');
    expect(widgetSize(overlay, DEFAULT_OPTIONS)).toEqual({ width: 520, height: 960 });
    expect(widgetSize(overlay, { ...DEFAULT_OPTIONS, sideboard: 'below' })).toEqual({ width: 320, height: 1320 });
    expect(widgetSize(overlay, { ...DEFAULT_OPTIONS, sideboard: 'off', scale: 150 })).toEqual({ width: 480, height: 1440 });
    expect(widgetSize(widgetInfo('record'), { ...DEFAULT_OPTIONS, scale: 200 })).toEqual({ width: 880, height: 220 });
  });

  it('writes list and text options only when they differ', () => {
    expect(streamUrl('http://x', 'deckstats', { hide: [] })).toBe('http://x/stream.html?widget=deckstats');
    expect(parseStreamOptions('?widget=record&period=today').period).toBe('today');
    expect(parseStreamOptions('?widget=record&period=week').period).toBe('session');
    expect(streamUrl('http://x', 'record', { period: 'today' })).toBe('http://x/stream.html?widget=record&period=today');
    expect(streamUrl('http://x', 'deckstats', { hide: ['turn'] })).toBe('http://x/stream.html?widget=deckstats&hide=turn');
    const url = streamUrl('http://x', 'break', { title: 'Back in 5!', hide: ['results', 'deck'] });
    expect(url).toBe('http://x/stream.html?widget=break&title=Back+in+5%21&hide=results%2Cdeck');
    expect(parseStreamOptions(new URL(url).search)).toMatchObject({ title: 'Back in 5!', hide: ['results', 'deck'] });
    expect(streamUrl('http://x', 'scorebug', { hide: ['timer'] })).toBe('http://x/stream.html?widget=scorebug&hide=timer');
    // The spotlight has no optional parts, so its link never carries them.
    expect(streamUrl('http://x', 'spotlight', { hide: ['timer'] })).toBe('http://x/stream.html?widget=spotlight');
  });

  it('sizes deck stats and intermission by what they show', () => {
    expect(widgetSize(widgetInfo('deckstats'), DEFAULT_OPTIONS)).toEqual({ width: 440, height: 230 });
    expect(widgetSize(widgetInfo('deckstats'), { ...DEFAULT_OPTIONS, hide: ['queues', 'turn', 'form'] })).toEqual({ width: 440, height: 100 });
    expect(widgetSize(widgetInfo('break'), DEFAULT_OPTIONS)).toEqual({ width: 560, height: 374 });
    expect(widgetSize(widgetInfo('break'), { ...DEFAULT_OPTIONS, hide: ['results', 'deck', 'rank'] })).toEqual({ width: 560, height: 176 });
  });

  it('adds demo and preview for the Settings preview link', () => {
    expect(streamUrl('http://x', 'spotlight', { seconds: 5 }, { demo: true, preview: true })).toBe(
      'http://x/stream.html?widget=spotlight&seconds=5&demo=1&preview=1',
    );
  });
});
