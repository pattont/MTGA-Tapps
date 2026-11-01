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
      record: true,
    });
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
    expect(widgetSize(games, { ...DEFAULT_OPTIONS, count: 1, record: false })).toEqual({ width: 380, height: 100 });
    expect(streamUrl('http://x', 'games', { record: false })).toBe('http://x/stream.html?widget=games&record=0');
  });

  it('sizes the full overlay for where its sideboard goes', () => {
    const overlay = widgetInfo('overlay');
    expect(widgetSize(overlay, DEFAULT_OPTIONS)).toEqual({ width: 520, height: 960 });
    expect(widgetSize(overlay, { ...DEFAULT_OPTIONS, sideboard: 'below' })).toEqual({ width: 320, height: 1320 });
    expect(widgetSize(overlay, { ...DEFAULT_OPTIONS, sideboard: 'off', scale: 150 })).toEqual({ width: 480, height: 1440 });
    expect(widgetSize(widgetInfo('record'), { ...DEFAULT_OPTIONS, scale: 200 })).toEqual({ width: 760, height: 220 });
  });

  it('adds demo and preview for the Settings preview link', () => {
    expect(streamUrl('http://x', 'spotlight', { seconds: 5 }, { demo: true, preview: true })).toBe(
      'http://x/stream.html?widget=spotlight&seconds=5&demo=1&preview=1',
    );
  });
});
