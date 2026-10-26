import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BAND_PX, CAPTION_PX, LOG_PX, composeFrame, frameLayout, stackRects } from './frameComposer';
import type { FrameInput, FrameStackItem } from './frameComposer';

/** A 2D context that records every call and measures text by length. */
function recordingContext() {
  const calls: Array<{ name: string; args: unknown[] }> = [];
  const texts: string[] = [];
  const ctx = new Proxy({} as Record<string, unknown>, {
    get(target, prop: string) {
      if (prop === 'calls') return calls;
      if (prop === 'texts') return texts;
      if (prop === 'measureText') return (text: string) => ({ width: text.length * 7 });
      if (prop in target) return target[prop];
      return (...args: unknown[]) => {
        calls.push({ name: prop, args });
        if (prop === 'fillText') texts.push(String(args[0]));
      };
    },
    set(target, prop: string, value) {
      target[prop] = value;
      return true;
    },
  });
  return ctx as unknown as CanvasRenderingContext2D & { calls: typeof calls; texts: string[] };
}

const item = (stackId: string, top = false): FrameStackItem => ({
  stackId,
  image: null,
  name: `Card ${stackId}`,
  who: 'You',
  kind: 'Spell',
  top,
  mine: true,
});

describe('frame layout', () => {
  it('scales the stage up to the target width (at most 3×) with even dimensions and bands', () => {
    const layout = frameLayout(840, 659, 1920);
    expect(layout.width % 2).toBe(0);
    expect(layout.height % 2).toBe(0);
    expect(layout.scale).toBeCloseTo(1920 / 840, 6);
    expect(layout.width).toBe(1920);
    expect(layout.height).toBe(Math.round((659 * layout.scale + layout.band + layout.caption) / 2) * 2);
    expect(layout.band).toBe(Math.round(BAND_PX * layout.scale));
    expect(layout.caption).toBe(Math.round(CAPTION_PX * layout.scale));
    expect(frameLayout(400, 300, 1920).scale).toBe(3);
  });

  it('stacks one full card then compact rows at the right edge, centered on the stage', () => {
    const layout = frameLayout(1132, 659, 1920);
    const rects = stackRects(layout, [item('a', true), item('b'), item('c')]);
    expect(rects).toHaveLength(3);
    expect(rects[0].h).toBeGreaterThan(rects[1].h);
    expect(rects[1].h).toBe(rects[2].h);
    expect(rects[0].x + rects[0].w).toBe(layout.sceneWidth - 10);
    expect(rects[0].y).toBeGreaterThan(10);
    expect(rects[2].y + rects[2].h).toBeLessThan(layout.sceneHeight);
    expect(stackRects(layout, [])).toEqual([]);
    // Deep stacks show at most seven rows.
    expect(stackRects(layout, Array.from({ length: 12 }, (_, i) => item(String(i), i === 0)))).toHaveLength(7);
  });
});

describe('composeFrame', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'Path2D',
      class {
        d: string;

        constructor(d: string) {
          this.d = d;
        }
      },
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it('draws the scene, HUD, badges, stack, arrows, caption and ending without throwing', () => {
    const layout = frameLayout(1132, 659, 1920);
    const ctx = recordingContext();
    const input: FrameInput = {
      scene: {} as CanvasImageSource,
      hud: {
        turn: 'Turn 12',
        whose: "Opponent's turn",
        whoseIsPlayer: false,
        phase: 'Main 1',
        clock: '5:51',
        you: { name: 'You', life: 34, hand: 2, library: 42, active: false },
        opponent: { name: 'skking', life: 10, hand: 3, library: 46, active: true },
      },
      labels: [
        { x: 300, y: 400, text: '10/10', tone: 'stat', emphasis: true },
        { x: 500, y: 400, text: '4', tone: 'loyalty' },
        { x: 120, y: 600, text: 'Library 42', tone: 'pile' },
        { x: 300, y: 320, text: '+1/+1 ×2', tone: 'counters' },
      ],
      stack: [item('s1', true), item('s2')],
      arrows: [
        { from: { stackId: 's1' }, to: { x: 300, y: 400 }, glow: '#f00', core: '#fff', reticle: false },
        { from: { x: 300, y: 400 }, to: { x: 500, y: 50 }, glow: '#0f0', core: '#fff', reticle: true },
        { from: { stackId: 'missing' }, to: { x: 1, y: 1 }, glow: '#00f', core: '#fff', reticle: false },
      ],
      caption: { text: 'You: cast Ajani Resolute', actor: 'player' },
      log: null,
      ending: {
        headline: 'Victory',
        reason: 'Opponent conceded',
        result: 'win',
        yourLife: 26,
        opponentName: 'Jams',
        theirLife: 11,
        facts: '10 turns · 3 min',
      },
      colors: { player: '#4cc38a', opponent: '#e5484d' },
    };
    composeFrame(ctx, layout, input);
    const names = ctx.calls.map((c) => c.name);
    expect(names.filter((n) => n === 'drawImage')).toHaveLength(1);
    expect(ctx.texts).toEqual(expect.arrayContaining(['Turn 12', "Opponent's turn", '34', '10', '10/10', '4', 'Library 42', 'Card s1', 'GAME OVER', 'VICTORY', 'Opponent conceded', 'YOU', 'JAMS', '26', '11', '10 turns · 3 min']));
    expect(ctx.texts.some((t) => t.startsWith('You: cast'))).toBe(true);
    // Two drawable arrows: each strokes a glow and a core and fills a head.
    expect(names.filter((n) => n === 'stroke').length).toBeGreaterThanOrEqual(4);
    expect(names.filter((n) => n === 'arc')).toHaveLength(2);
  });

  it('draws the actions log column with turn headers, wrapped rows and the active row, instead of a caption', () => {
    const layout = frameLayout(840, 659, 1920, true);
    expect(layout.caption).toBe(0);
    expect(layout.logWidth).toBe(Math.round(LOG_PX * layout.scale));
    expect(layout.width).toBe(1920);
    const ctx = recordingContext();
    const items = [
      { type: 'turn' as const, key: 'turn:1', turn: 1, seat: 1, seq: 1 },
      { type: 'event' as const, key: 'e:2', seq: 2, t: 5, actor: 'player' as const, parts: [{ kind: 'text' as const, text: 'You: cast ' }, { kind: 'card' as const, name: 'Ajani Resolute', text: 'Ajani Resolute', meta: 'Planeswalker' }] },
      { type: 'event' as const, key: 'e:3', seq: 3, t: 9, actor: 'opponent' as const, parts: [{ kind: 'text' as const, text: 'Opponent: a very long line of text that has to wrap onto a second line in the narrow column of the video' }] },
    ];
    composeFrame(ctx, layout, {
      scene: {} as CanvasImageSource,
      hud: {
        turn: 'Turn 1',
        whose: 'Your turn',
        whoseIsPlayer: true,
        phase: null,
        clock: '0:09',
        you: { name: 'You', life: 20, hand: 7, library: 53, active: true },
        opponent: { name: 'Opponent', life: 20, hand: 7, library: 53, active: false },
      },
      labels: [],
      stack: [],
      arrows: [],
      caption: { text: 'should not be drawn', actor: 'player' },
      log: { items, activeIndex: 2, playerSeat: 1 },
      ending: null,
      colors: { player: '#4cc38a', opponent: '#e5484d' },
    });
    expect(ctx.texts).toContain('ACTIONS');
    expect(ctx.texts).toContain('TURN 1 – YOUR TURN');
    expect(ctx.texts).toContain('Ajani Resolute');
    expect(ctx.texts).toContain('Planeswalker');
    expect(ctx.texts.some((t) => t.startsWith('Opponent:'))).toBe(true);
    expect(ctx.texts).not.toContain('should not be drawn');
    // The long row wrapped: its words land on more than one baseline.
    const ys = ctx.calls.filter((c) => c.name === 'fillText' && /^(a|very|long|line|wrap|column|video)$/.test(String(c.args[0]))).map((c) => c.args[2]);
    expect(new Set(ys).size).toBeGreaterThan(1);
  });

  it('skips the ending and caption when absent and tolerates a scene that cannot be drawn', () => {
    const layout = frameLayout(840, 659, 1280);
    const ctx = recordingContext();
    const scene = {} as CanvasImageSource;
    ctx.drawImage = () => {
      throw new Error('tainted');
    };
    composeFrame(ctx, layout, {
      scene,
      hud: {
        turn: 'Pre-game',
        whose: null,
        whoseIsPlayer: false,
        phase: null,
        clock: '0:00',
        you: { name: 'You', life: 20, hand: 7, library: 53, active: false },
        opponent: { name: 'Opponent', life: 20, hand: 7, library: 53, active: false },
      },
      labels: [],
      stack: [],
      arrows: [],
      caption: null,
      log: null,
      ending: null,
      colors: { player: '#4cc38a', opponent: '#e5484d' },
    });
    expect(ctx.texts).toContain('Pre-game');
    expect(ctx.texts).not.toContain('GAME OVER');
  });
});
