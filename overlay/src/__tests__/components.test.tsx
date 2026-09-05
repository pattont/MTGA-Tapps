import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Panel, deckColors } from '../components/Panel';
import { Rail } from '../components/Rail';
import { hoverCardTop, hoverSide, measureContentHeight, tintAlpha } from '../App';
import { defaultSettings } from '../tauri';
import { brawlState, inGamePayload, idlePayload, offlinePayload } from './fixtures';

afterEach(cleanup);

const noop = () => undefined;

function panelProps(overrides: Partial<Parameters<typeof Panel>[0]> = {}) {
  return {
    payload: inGamePayload(),
    link: 'online' as const,
    settings: defaultSettings(),
    pinned: true,
    dock: 'right' as const,
    sort: 'odds' as const,
    onSort: noop,
    onCollapse: noop,
    onTogglePin: noop,
    onOpenSettings: noop,
    onDragStart: noop,
    onHover: noop,
    ...overrides,
  };
}

describe('Rail', () => {
  it('shows turn, land odds and library during a game', () => {
    render(<Rail payload={inGamePayload()} link="online" landsInPlay={4} onOpenPanel={noop} onOpenSettings={noop} onDragStart={noop} />);
    expect(screen.getByText('5')).toBeTruthy();
    expect(screen.getByText('27%')).toBeTruthy();
    expect(screen.getByText('41')).toBeTruthy();
    expect(screen.getByRole('button', { name: /open the deck panel/i })).toBeTruthy();
  });

  it('shows dashes and a status dot when the tracker is down', () => {
    const { container } = render(<Rail payload={offlinePayload()} link="offline" landsInPlay={null} onOpenPanel={noop} onOpenSettings={noop} onDragStart={noop} />);
    expect(container.querySelector('.rail-status.off')).toBeTruthy();
    expect(container.querySelector('.rail')?.getAttribute('title')).toBe('Tracker not running');
  });
});

describe('Panel', () => {
  it('renders the header line, land strip and grouped lands', () => {
    const { container } = render(<Panel {...panelProps()} />);
    expect(screen.getByText('Mono-Red Aggro')).toBeTruthy();
    expect(screen.getByText('Std. BO1 Ranked · vs sansastark (1–2)')).toBeTruthy();
    expect(screen.getByText('PLAY')).toBeTruthy();
    expect(screen.getByText('Basic lands')).toBeTruthy();
    expect(screen.getByText('Nonbasic lands')).toBeTruthy();
    expect(container.querySelectorAll('.pips img').length).toBe(1);
    expect(container.querySelector('.pips img')?.getAttribute('alt')).toBe('R');
    const groups = Array.from(container.querySelectorAll('.grp')).map((g) => g.textContent);
    expect(groups[0]).toBe('Spells');
    expect(groups[1]).toBe('Lands');
  });

  it('dims exhausted rows in 60-card and collapses them in Brawl', () => {
    const { container, rerender } = render(<Panel {...panelProps()} />);
    const shock = Array.from(container.querySelectorAll('.row')).find((r) => r.textContent?.includes('Shock'));
    expect(shock?.classList.contains('dim')).toBe(true);
    const brawl = { ...inGamePayload(), state: brawlState() };
    rerender(<Panel {...panelProps({ payload: brawl })} />);
    const toggle = screen.getByRole('button', { name: /drawn \(3\)/i });
    expect(container.querySelectorAll('.row.dim').length).toBe(0);
    fireEvent.click(toggle);
    expect(container.querySelectorAll('.row.dim').length).toBe(3);
  });

  it('shows every land and reports hover boxes', () => {
    const onHover = vi.fn();
    const { container } = render(<Panel {...panelProps({ settings: { ...defaultSettings(), lands: 'all' }, onHover })} />);
    expect(screen.getByText('Mountain')).toBeTruthy();
    expect(screen.getByText('Rockface Village')).toBeTruthy();
    const row = container.querySelector('.row') as HTMLElement;
    fireEvent.mouseEnter(row);
    expect(onHover).toHaveBeenCalledWith(expect.objectContaining({ name: expect.any(String) }), expect.objectContaining({ top: expect.any(Number) }));
    fireEvent.mouseLeave(row);
    expect(onHover).toHaveBeenLastCalledWith(null, null);
  });

  it('keeps the final library up on the results screen', () => {
    const payload = inGamePayload();
    payload.state = { ...payload.state!, game_active: false, game_over: true };
    const { container } = render(<Panel {...panelProps({ payload })} />);
    expect(screen.getByText('Mono-Red Aggro')).toBeTruthy();
    expect(screen.getByText('FINAL')).toBeTruthy();
    expect(screen.getByText(/Game over · Std\. BO1 Ranked/)).toBeTruthy();
    expect(container.querySelectorAll('.row').length).toBeGreaterThan(5);
  });

  it('has empty states for idle and offline', () => {
    const { container, rerender } = render(<Panel {...panelProps({ payload: idlePayload() })} />);
    expect(screen.getByText(/Waiting for a match/)).toBeTruthy();
    expect(screen.getByText('Tapps Tracker')).toBeTruthy();
    // Between games: no turn box, no subtitle — the pill says it all.
    expect(container.querySelector('.turn')).toBeNull();
    expect(container.querySelector('.head .deck span')).toBeNull();
    rerender(<Panel {...panelProps({ payload: offlinePayload(), link: 'offline' })} />);
    expect(screen.getByText(/Tracker not running/)).toBeTruthy();
    expect(container.querySelector('.pill.off')).toBeTruthy();
  });
});

describe('deckColors', () => {
  it('reads colours from casting costs, hybrid included, in WUBRG order', () => {
    expect(deckColors([{ mana_cost: '{1}{G}' }, { mana_cost: '{W/U}' }, { mana_cost: null }])).toEqual(['W', 'U', 'G']);
  });
});

describe('tintAlpha', () => {
  it('drives only the ground: 88 % at the top, dark at the default, gone at zero', () => {
    expect(tintAlpha(1)).toBe(0.88);
    expect(tintAlpha(0.6)).toBeGreaterThan(0.7);
    expect(tintAlpha(0.6)).toBeLessThan(0.75);
    expect(tintAlpha(0)).toBe(0);
  });
});

describe('App helpers', () => {
  it('flies the hover card toward the board', () => {
    expect(hoverSide('right')).toBe('left');
    expect(hoverSide('left')).toBe('right');
    expect(hoverSide('float')).toBe('left');
    expect(hoverCardTop(100, 118, 600)).toBe(120);
    expect(hoverCardTop(540, 558, 600)).toBe(440);
  });

  it('measures the natural panel height from chrome plus the full list', () => {
    const panel = { offsetHeight: 400 } as HTMLElement;
    const list = { clientHeight: 300, scrollHeight: 520, querySelector: () => null } as unknown as HTMLElement;
    expect(measureContentHeight(panel, list)).toBe(620);
    // A window that opened tall: the list's scrollHeight equals its (large)
    // visible height, but the rows are short — the rows win, so it shrinks.
    const tall = { offsetHeight: 620 } as HTMLElement;
    const shortList = {
      clientHeight: 500,
      scrollHeight: 500,
      querySelector: () => ({ offsetHeight: 210 }),
    } as unknown as HTMLElement;
    expect(measureContentHeight(tall, shortList)).toBe(330);
    expect(measureContentHeight({ offsetHeight: 90 } as HTMLElement, null)).toBe(160);
    expect(measureContentHeight({ offsetHeight: 90 } as HTMLElement, null, { offsetTop: 34, scrollHeight: 300 } as HTMLElement)).toBe(344);
  });
});
