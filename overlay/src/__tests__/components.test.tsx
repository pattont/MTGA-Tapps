import { cleanup, fireEvent, render, screen, within } from '@testing-library/preact';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Panel, deckColors } from '../components/Panel';
import { Rail, deckTone } from '../components/Rail';
import { Flyout } from '../components/Flyout';
import { rankText } from '../components/TodayRecord';
import { App, hoverCardTop, hoverSide, measureContentHeight, tintAlpha } from '../App';
import { defaultSettings } from '../tauri';
import { brawlState, drawQuality, inGamePayload, idlePayload, offlinePayload, todayRecord } from './fixtures';

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
    cursor: null,
    sideboardOpen: false,
    onToggleSideboard: noop,
    ...overrides,
  };
}

describe('Rail', () => {
  it('shows turn, land odds and library during a game', () => {
    render(<Rail payload={inGamePayload()} link="online" dock="right" landsInPlay={4} onOpenPanel={noop} onOpenSettings={noop} onDragStart={noop} />);
    expect(screen.getByText('5')).toBeTruthy();
    expect(screen.getByText('27').closest('.v.land')?.textContent).toBe('27%');
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

  it('shows every land when asked', () => {
    render(<Panel {...panelProps({ settings: { ...defaultSettings(), lands: 'all' } })} />);
    fireEvent.click(screen.getByRole('button', { name: /^Lands,/ }));
    expect(screen.getByText('Mountain')).toBeTruthy();
    expect(screen.getByText('Rockface Village')).toBeTruthy();
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

  it('marks counts as ceilings and says why when cards left the library unseen', () => {
    const payload = inGamePayload();
    payload.state = { ...payload.state!, library_size: 21, unseen: 24, draw_pool: 45 };
    const { container } = render(<Panel {...panelProps({ payload })} />);
    expect(container.querySelector('.note.warn')?.textContent).toContain('24 cards left your library');
    // The note leads the list, where it cannot scroll out of sight.
    expect(container.querySelector('.list-body')?.firstElementChild?.className).toBe('note warn');
    expect(screen.getByRole('button', { name: /Lands, 11 of 20 left/ }).textContent).toContain('≤11/20');
    expect(container.querySelector('.lands small')?.textContent).toBe('up to 11 of 21 left');
    const rage = container.querySelector('[data-key="Monstrous Rage"] .cnt');
    expect(rage?.textContent).toBe('≤4/4');
    expect(rage?.getAttribute('title')).toBe('At most 4 left');
    // A card with none left is certain: no ceiling mark.
    expect(container.querySelector('[data-key="Shock"] .cnt')?.textContent).toBe('0/4');
  });

  it('warns that counts may be stale after a message Arena only summarized', () => {
    const payload = inGamePayload();
    payload.state = { ...payload.state!, log_gap: true };
    const { container } = render(<Panel {...panelProps({ payload })} />);
    expect(container.querySelector('.note.warn')?.textContent).toContain("Arena's log skipped a large move");
    expect(container.querySelector('[data-key="Monstrous Rage"] .cnt')?.textContent).toBe('4/4');
  });

  it('shows no note while every card is accounted for', () => {
    const { container } = render(<Panel {...panelProps()} />);
    expect(container.querySelector('.note.warn')).toBeNull();
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

describe("Today's record", () => {
  const withSession = (today = todayRecord(), base = inGamePayload()) => ({ ...base, today });

  it('shows the record, win rate and Play / Draw win rates on one line by default', () => {
    const { container } = render(<Panel {...panelProps({ payload: withSession() })} />);
    const footer = container.querySelector('.ss.ss-line');
    expect(footer).toBeTruthy();
    expect(footer?.querySelector('.ss-lab')?.textContent).toBe('Today');
    expect(footer?.querySelector('.ss-rec')?.textContent).toBe('6–2');
    expect(footer?.querySelector('.ss-rate')?.textContent).toBe('75%');
    expect(Array.from(footer?.querySelectorAll('.ss-pd-v .ss-up') ?? []).map((el) => el.textContent)).toEqual(['67%', '80%']);
    expect(footer?.getAttribute('aria-label')).toMatch(/on the play: 2 wins, 1 loss/);
    // The last thing in the panel, after the card list.
    expect(container.querySelector('.panel')?.lastElementChild).toBe(footer);
  });

  describe('full (the Stream Kit record widget)', () => {
    const settings = { ...defaultSettings(), sessionRecord: 'split' as const };
    const footer = (session = todayRecord()) => render(<Panel {...panelProps({ payload: withSession(session), settings })} />).container.querySelector('.ss.ss-split');

    it('puts the record over the rank and deck chips, with Play and Draw columns', () => {
      const el = footer();
      expect(el?.querySelector('.ss-rec')?.textContent).toBe('6–2');
      expect(el?.querySelector('.ss-rate')?.textContent).toBe('75%');
      expect(Array.from(el?.querySelectorAll('.ss-chip') ?? []).map((chip) => chip.textContent)).toEqual(['Diamond 2 · 3/6', 'Deck 3–1']);
      // Each side's win rate over its record, from the first game.
      expect(Array.from(el?.querySelectorAll('.ss-col') ?? []).map((col) => col.textContent)).toEqual(['Play67%2–1', 'Draw80%4–1']);
      expect(el?.getAttribute('aria-label')).toMatch(/rank: Diamond 2 · 3\/6; with this deck: 3 wins, 1 loss/);
    });

    it('shows no rank outside ranked queues and keeps the deck record', () => {
      const el = footer({ ...todayRecord(), rank: null });
      expect(Array.from(el?.querySelectorAll('.ss-chip') ?? []).map((chip) => chip.textContent)).toEqual(['Deck 3–1']);
    });

    it('drops the chips without a rank or a deck result, and a side with no games', () => {
      // An older tracker sends neither field.
      const { rank: _rank, deck: _deck, ...older } = todayRecord();
      const el = footer({ ...older, draw: { wins: 0, losses: 0 } });
      expect(el?.querySelector('.ss-chips')).toBeNull();
      expect(Array.from(el?.querySelectorAll('.ss-col') ?? []).map((col) => col.textContent)).toEqual(['Play67%2–1']);
      expect(footer({ ...todayRecord(), deck: { wins: 0, losses: 0 }, rank: null })?.querySelector('.ss-chips')).toBeNull();
    });

    it('names Mythic by rank or percentile', () => {
      const mythic = { rank_class: 'Mythic', rank_level: 1, rank_step: 0, rank_steps: 1, mythic_percentile: 92, mythic_rank: null };
      expect(rankText(mythic)).toBe('Mythic 92%');
      expect(rankText({ ...mythic, mythic_rank: 431 })).toBe('Mythic #431');
      expect(rankText({ ...mythic, mythic_percentile: null })).toBe('Mythic');
    });
  });

  it('shows draws, a red rate under 50% and a dash for a side with no games', () => {
    const session = { ...todayRecord(), wins: 1, losses: 3, draws: 1, win_rate: 25, play: { wins: 1, losses: 3 }, draw: { wins: 0, losses: 0 } };
    const { container } = render(<Panel {...panelProps({ payload: withSession(session) })} />);
    expect(container.querySelector('.ss-rec')?.textContent).toBe('1–3–1');
    expect(container.querySelector('.ss-pd-v .ss-down')?.textContent).toBe('25%');
    expect(container.querySelector('.ss-pd-v')?.textContent).toBe('25%/–');
  });

  it('stays between games and hides when off, before the first result, or without a tracker', () => {
    const { container, rerender } = render(<Panel {...panelProps({ payload: withSession(todayRecord(), idlePayload()) })} />);
    expect(screen.getByText(/Waiting for a match/)).toBeTruthy();
    expect(container.querySelector('.ss')).toBeTruthy();
    rerender(<Panel {...panelProps({ payload: withSession(), settings: { ...defaultSettings(), sessionRecord: 'off' } })} />);
    expect(container.querySelector('.ss')).toBeNull();
    rerender(<Panel {...panelProps({ payload: withSession({ ...todayRecord(), games: 0, wins: 0, losses: 0, win_rate: null, play: { wins: 0, losses: 0 }, draw: { wins: 0, losses: 0 } }) })} />);
    expect(container.querySelector('.ss')).toBeNull();
    rerender(<Panel {...panelProps({ payload: offlinePayload(), link: 'offline' })} />);
    expect(container.querySelector('.ss')).toBeNull();
  });
});

describe('flood meter', () => {
  const withMeter = (floodMeter: 'off' | 'above' | 'below', payload = inGamePayload()) =>
    render(
      <Panel
        {...panelProps({
          payload: { ...payload, today: todayRecord(), draw_quality: drawQuality() },
          settings: { ...defaultSettings(), floodMeter },
        })}
      />,
    ).container;

  it('sits at the very bottom when set below today\'s record', () => {
    const container = withMeter('below');
    const meter = container.querySelector('.fm');
    expect(meter?.classList.contains('fm-flood')).toBe(true);
    expect(meter?.querySelector('.fm-status')?.textContent).toBe('Flooding');
    expect(meter?.querySelector('.fm-numbers')?.textContent).toBe('7 of 10 · exp 4.0 (+3.0)');
    expect(container.querySelector('.panel')?.lastElementChild).toBe(meter);
    expect(meter?.previousElementSibling?.classList.contains('ss')).toBe(true);
    // The gauge: gold screw zone from the left, blue flood zone to the right, the dot at 7 of 10.
    const style = (meter as HTMLElement).style;
    expect(style.getPropertyValue('--fm-now')).toBe('70%');
    expect(style.getPropertyValue('--fm-expected')).toBe('40%');
    expect(parseFloat(style.getPropertyValue('--fm-screw'))).toBeLessThan(40);
    expect(parseFloat(style.getPropertyValue('--fm-flood'))).toBeGreaterThan(40);
  });

  it('goes above today\'s record by default, or nowhere when off', () => {
    expect(defaultSettings().floodMeter).toBe('above');
    const above = withMeter('above');
    expect(above.querySelector('.fm')?.nextElementSibling?.classList.contains('ss')).toBe(true);
    cleanup();
    expect(withMeter('off').querySelector('.fm')).toBeNull();
  });

  it('shows only with a game on screen, and not before a card is seen', () => {
    expect(withMeter('below', idlePayload()).querySelector('.fm')).toBeNull();
    cleanup();
    const { container } = render(
      <Panel {...panelProps({ payload: { ...inGamePayload(), draw_quality: { ...drawQuality(), total_cards_seen: 0, lands_seen: 0 } } })} />,
    );
    expect(container.querySelector('.fm')).toBeNull();
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

describe('App with the deck panel off (opponent only)', () => {
  it('draws nothing of the deck panel, and still opens the settings when asked', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)));
    (window as { __TAPPS_SETTINGS__?: object }).__TAPPS_SETTINGS__ = { deckPanel: false };
    const { container } = render(<App />);
    await vi.waitFor(() => expect(container.querySelector('.root.deck-off')).toBeTruthy());
    expect(container.querySelector('.rail')).toBeNull();
    expect(container.querySelector('.panel')).toBeNull();
    expect(container.querySelector('.root')?.children.length).toBe(0);
    // The tracker's menu, or the opponent panel's gear, asks for the settings.
    window.dispatchEvent(new CustomEvent('tapps:overlay-open-settings'));
    await vi.waitFor(() => expect(screen.getByRole('dialog', { name: 'Overlay settings' })).toBeTruthy());
    expect(container.querySelector('.rail')).toBeNull();
    // The tracker turns the deck panel back on: the rail returns.
    window.dispatchEvent(new CustomEvent('tapps:overlay-settings', { detail: { ...defaultSettings(), deckPanel: true } }));
    await vi.waitFor(() => expect(container.querySelector('.rail')).toBeTruthy());
    delete (window as { __TAPPS_SETTINGS__?: object }).__TAPPS_SETTINGS__;
    vi.unstubAllGlobals();
  });
});

describe('App helpers', () => {
  it('flies the hover card toward the board', () => {
    expect(hoverSide('right')).toBe('left');
    expect(hoverSide('left')).toBe('right');
    expect(hoverSide('float')).toBe('left');
    // Level with the row, kept whole inside the window (card image 270 wide at
    // 488:680 = 376, plus the odds block = 488).
    expect(hoverCardTop(100, 118, 600)).toBe(100);
    expect(hoverCardTop(540, 558, 600)).toBe(600 - 488 - 2);
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

describe('Flyout', () => {
  it('orders the sliders Scale, Rail opacity, Panel opacity, Max panel height (in pixels)', () => {
    render(<Flyout settings={defaultSettings()} platform="windows" onChange={() => undefined} onClose={() => undefined} onQuit={() => undefined} />);
    const labels = Array.from(document.querySelectorAll('.fly label.r > span:first-child')).map((el) => el.textContent);
    expect(labels.slice(0, 4)).toEqual(['Scale', 'Rail opacity', 'Panel opacity', 'Max panel height']);
    expect(screen.getByText('850 px')).toBeTruthy();
  });

  it("switches today's record between off, one line and full", () => {
    const onChange = vi.fn();
    render(<Flyout settings={defaultSettings()} platform="windows" onChange={onChange} onClose={() => undefined} onQuit={() => undefined} />);
    const group = screen.getByRole('group', { name: "Today's record" });
    expect(group.querySelector('button.on')?.textContent).toBe('One line');
    fireEvent.click(within(group).getByText('Full'));
    expect(onChange.mock.calls[0][0].sessionRecord).toBe('split');
    fireEvent.click(within(group).getByText('Off'));
    expect(onChange.mock.calls[1][0].sessionRecord).toBe('off');
  });

  it('frames today\'s record and the flood meter together, under Rows', () => {
    const onChange = vi.fn();
    const { container } = render(<Flyout settings={defaultSettings()} platform="windows" onChange={onChange} onClose={() => undefined} onQuit={() => undefined} />);
    const box = screen.getByRole('group', { name: 'Bottom of the panel' });
    expect(box.previousElementSibling?.textContent).toMatch(/^Rows/);
    expect(Array.from(box.querySelectorAll('.r > span:first-child')).map((el) => el.textContent)).toEqual(['Flood meter', "Today's record"]);
    const flood = within(box).getByRole('group', { name: 'Flood meter' });
    expect(flood.querySelector('button.on')?.textContent).toBe('Above');
    fireEvent.click(within(flood).getByText('Below'));
    expect(onChange.mock.calls[0][0].floodMeter).toBe('below');
    fireEvent.click(within(flood).getByText('Off'));
    expect(onChange.mock.calls[1][0].floodMeter).toBe('off');
    expect(container.querySelectorAll('.box')).toHaveLength(1);
  });

  it('restores every preference but keeps the window and the panel state', () => {
    const current = {
      ...defaultSettings(),
      sessionRecord: 'off' as const,
      opacity: 0.2,
      scale: 150,
      panelMaxHeight: 400,
      dock: 'right' as const,
      hotkeysWindows: { toggle: 'Ctrl+Alt+T', visibility: 'Ctrl+Alt+H', opponent: 'Ctrl+Alt+O' },
      panelOpen: true,
      panelPinned: true,
      positions: { leftY: 120, rightY: null, floatX: 40, floatY: 50 },
      monitor: 'DELL U2723QE',
    };
    const onChange = vi.fn();
    render(<Flyout settings={current} platform="windows" onChange={onChange} onClose={() => undefined} onQuit={() => undefined} />);
    fireEvent.click(screen.getByText('Restore defaults'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0];
    expect(next.opacity).toBe(0.8);
    expect(next.railOpacity).toBe(0.9);
    expect(next.scale).toBe(100);
    expect(next.panelMaxHeight).toBe(850);
    expect(next.dock).toBe('left');
    expect(next.sessionRecord).toBe('scoreboard');
    expect(next.hotkeysWindows.toggle).toBe('Alt+Shift+T');
    expect(next.panelOpen).toBe(true);
    expect(next.panelPinned).toBe(true);
    expect(next.positions).toEqual(current.positions);
    expect(next.monitor).toBe('DELL U2723QE');
  });
});

describe('Panel hover', () => {
  it('highlights the row under the shell-reported cursor and reports it, and clears when the cursor leaves', () => {
    const onHover = vi.fn();
    const { rerender, container } = render(<Panel {...panelProps({ onHover })} />);
    const rows = container.querySelectorAll<HTMLElement>('.row[data-key]');
    expect(rows.length).toBeGreaterThan(0);
    const target = rows[1];
    // jsdom has no layout: point elementFromPoint at the row ourselves.
    const original = document.elementFromPoint;
    document.elementFromPoint = () => target;
    try {
      rerender(<Panel {...panelProps({ onHover, cursor: { x: 40, y: 120 } })} />);
      expect(target.classList.contains('hot')).toBe(true);
      const call = onHover.mock.calls.at(-1)!;
      expect(call[0].key).toBe(target.dataset.key);
      // Cursor off the window: highlight and card go at once.
      rerender(<Panel {...panelProps({ onHover, cursor: null })} />);
      expect(target.classList.contains('hot')).toBe(false);
      expect(onHover.mock.calls.at(-1)).toEqual([null, null]);
    } finally {
      document.elementFromPoint = original;
    }
  });

  it('clears the highlight when the cursor moves onto the board beside the panel', () => {
    // The gutter is still inside the window, so the shell keeps reporting a
    // point; it is just not on a row.
    const onHover = vi.fn();
    const { rerender, container } = render(<Panel {...panelProps({ onHover })} />);
    const target = container.querySelectorAll<HTMLElement>('.row[data-key]')[2];
    const gutter = document.createElement('div');
    const original = document.elementFromPoint;
    try {
      document.elementFromPoint = () => target;
      rerender(<Panel {...panelProps({ onHover, cursor: { x: 40, y: 140 } })} />);
      // (.pct.hot is an odds colour, not a highlight.)
      expect(container.querySelectorAll('.list [data-key].hot')).toHaveLength(1);
      document.elementFromPoint = () => gutter;
      rerender(<Panel {...panelProps({ onHover, cursor: { x: 450, y: 140 } })} />);
      expect(container.querySelectorAll('.list [data-key].hot')).toHaveLength(0);
      expect(onHover.mock.calls.at(-1)).toEqual([null, null]);
    } finally {
      document.elementFromPoint = original;
    }
  });

  it('highlights the Lands and Sideboard rows under the cursor without a card preview', () => {
    const onHover = vi.fn();
    const payload = inGamePayload();
    payload.state!.sideboard = [{ name: 'Obliterating Bolt', type_category: 'Sorcery', mana_cost: '{1}{R}', mana_value: 2, count: 3, land: false }];
    const { rerender, container } = render(<Panel {...panelProps({ payload, onHover })} />);
    const original = document.elementFromPoint;
    try {
      for (const selector of ['.land-row', '.side-row']) {
        const target = container.querySelector<HTMLElement>(selector)!;
        document.elementFromPoint = () => target;
        rerender(<Panel {...panelProps({ payload, onHover, cursor: { x: 40, y: Math.random() * 500 } })} />);
        expect(target.classList.contains('hot')).toBe(true);
        expect(onHover.mock.calls.at(-1)).toEqual([null, null]);
      }
    } finally {
      document.elementFromPoint = original;
    }
  });

  it('never highlights list rows with CSS :hover, which sticks once the window passes the mouse to Arena', async () => {
    // From disk: vitest hands CSS imports (?raw included) back empty.
    const fsModule = 'node:fs';
    const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as { readFileSync: (path: string, encoding: 'utf8') => string };
    // Relative to overlay/, where vitest runs (npm test).
    const css = readFileSync('src/styles.css', 'utf8');
    expect(css).toMatch(/\.row\.hot \{/);
    expect(css).not.toMatch(/\.row:hover/);
    expect(css).not.toMatch(/\.grp-toggle:hover/);
  });
});
