import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Panel, deckColors } from '../components/Panel';
import { Rail, deckTone } from '../components/Rail';
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
    sideboardOpen: false,
    onToggleSideboard: noop,
    ...overrides,
  };
}

describe('Rail', () => {
  it('shows turn, land odds and library during a game', () => {
    render(<Rail payload={inGamePayload()} link="online" dock="right" landsInPlay={4} onOpenPanel={noop} onOpenSettings={noop} onDragStart={noop} />);
    expect(screen.getByText('5')).toBeTruthy();
    expect(screen.getByText('27%')).toBeTruthy();
    expect(screen.getByText('41')).toBeTruthy();
    expect(screen.getByRole('button', { name: /open the deck panel/i })).toBeTruthy();
  });

  it('shows dashes and a status dot when the tracker is down', () => {
    const { container } = render(<Rail payload={offlinePayload()} link="offline" dock="right" landsInPlay={null} onOpenPanel={noop} onOpenSettings={noop} onDragStart={noop} />);
    // No status dot: a broken tracker link shows as a warning badge on the
    // icon with a tooltip that says what to do; a working one shows nothing.
    expect(container.querySelector('.logo-wrap.offline .warn-badge')).toBeTruthy();
    expect(container.querySelector('.logo-wrap')?.getAttribute('title')).toMatch(/Not connected to Tapps Tracker/);
    const online = render(<Rail payload={inGamePayload()} link="online" dock="right" landsInPlay={4} onOpenPanel={noop} onOpenSettings={noop} onDragStart={noop} />);
    expect(online.container.querySelector('.warn-badge')).toBeNull();
  });
});

describe('Panel', () => {
  it('renders the header line, land strip and grouped lands', () => {
    const { container } = render(<Panel {...panelProps()} />);
    expect(screen.getByText('Mono-Red Aggro')).toBeTruthy();
    expect(screen.getByText('Std. BO1 Ranked · vs sansastark (1–2)')).toBeTruthy();
    expect(screen.getByText('PLAY')).toBeTruthy();
    // Lands fold into one row until opened.
    const landRow = screen.getByRole('button', { name: /Lands, 11 of 20 left/ });
    expect(landRow.textContent).toContain('11/20');
    expect(landRow.textContent).toContain('27%');
    expect(landRow.textContent).not.toContain('26.8');
    expect(screen.queryByText('Basic lands')).toBeNull();
    fireEvent.click(landRow);
    expect(screen.getByText('Basic lands')).toBeTruthy();
    expect(screen.getByText('Nonbasic lands')).toBeTruthy();
    expect(container.querySelectorAll('.pips img').length).toBe(1);
    expect(container.querySelector('.pips img')?.getAttribute('alt')).toBe('R');
    // No "Spells" caption: the list starts straight at the cards, and the
    // opened land rows sit a step in under the Lands row.
    expect(container.querySelector('.grp')).toBeNull();
    expect(container.querySelectorAll('.row.sub').length).toBe(2);
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
    fireEvent.click(screen.getByRole('button', { name: /^Lands,/ }));
    expect(screen.getByText('Mountain')).toBeTruthy();
    expect(screen.getByText('Rockface Village')).toBeTruthy();
    const row = container.querySelector('.row') as HTMLElement;
    fireEvent.mouseEnter(row);
    expect(onHover).toHaveBeenCalledWith(expect.objectContaining({ name: expect.any(String) }), expect.objectContaining({ top: expect.any(Number) }));
    fireEvent.mouseLeave(row);
    expect(onHover).toHaveBeenLastCalledWith(null, null);
  });

  it('offers the sideboard as a row when the deck has one', () => {
    const onToggleSideboard = vi.fn();
    const payload = inGamePayload();
    payload.state = {
      ...payload.state!,
      sideboard: [
        { name: 'Obliterating Bolt', type_category: 'Sorcery', mana_cost: '{1}{R}', mana_value: 2, count: 3, land: false },
        { name: 'Urabrask\'s Forge', type_category: 'Artifact', mana_cost: '{2}{R}', mana_value: 3, count: 2, land: false },
      ],
    };
    render(<Panel {...panelProps({ payload, onToggleSideboard })} />);
    const row = screen.getByRole('button', { name: /Sideboard, 5 cards/ });
    fireEvent.click(row);
    expect(onToggleSideboard).toHaveBeenCalled();
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

describe('deckTone', () => {
  it('goes yellow at half the deck and red under 15 cards', () => {
    expect(deckTone(41, 60)).toBe('ok');
    expect(deckTone(30, 60)).toBe('warn');
    expect(deckTone(15, 60)).toBe('warn');
    expect(deckTone(14, 60)).toBe('low');
    expect(deckTone(60, 100)).toBe('ok');
    expect(deckTone(50, 100)).toBe('warn');
  });
});

describe('App helpers', () => {
  it('flies the hover card toward the board', () => {
    expect(hoverSide('right')).toBe('left');
    expect(hoverSide('left')).toBe('right');
    expect(hoverSide('float')).toBe('left');
    // Level with the row, kept whole inside the window (card image + odds = 446).
    expect(hoverCardTop(100, 118, 600)).toBe(100);
    expect(hoverCardTop(540, 558, 600)).toBe(600 - 446 - 2);
    expect(hoverCardTop(0, 18, 600)).toBe(2);
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
