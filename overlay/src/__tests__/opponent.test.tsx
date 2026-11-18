import { cleanup, fireEvent, render, screen } from '@testing-library/preact';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Flyout, restoredDefaults } from '../components/Flyout';
import { OpponentPanel, headLine } from '../components/OpponentPanel';
import { OpponentRail, recordCell } from '../components/OpponentRail';
import { opponentPanelHeight } from '../OpponentApp';
import { bandText, colorLetters, deckLine, freshPlays, groupSeen, landsText, nonlandSeen, opponentOf, railTitle } from '../opponentModel';
import { defaultSettings } from '../tauri';
import { idlePayload, offlinePayload, opponentBlock, opponentPayload } from './fixtures';

afterEach(cleanup);

const noop = () => undefined;

describe('opponent model', () => {
  it('groups by type, cheapest first, with lands apart, most played first', () => {
    const { groups, lands } = groupSeen(opponentBlock().seen);
    expect(groups.map((g) => g.label)).toEqual(['Creatures', 'Instants & sorceries', 'Artifacts & enchantments']);
    expect(groups[1].cards.map((c) => c.name)).toEqual(['Cut Down', 'Go for the Throat']);
    expect(lands.map((c) => c.name)).toEqual(['Swamp', 'Blood Crypt', 'Mountain']);
    expect(landsText(lands)).toBe('Swamp ×2 · Blood Crypt · Mountain');
    expect(nonlandSeen(opponentBlock().seen)).toBe(4);
  });

  it('words the deck line by where the name came from, a guess always as one', () => {
    const block = opponentBlock();
    expect(deckLine(block)).toEqual({ name: 'Rakdos Midrange', note: 'Likely · 3 cards match your history' });
    expect(deckLine({ ...block, deck: { label: 'Rakdos', source: 'colors', matched_cards: null } }).note).toBe('From the colours shown');
    expect(deckLine({ ...block, deck: { label: 'Kenrith', source: 'commander', matched_cards: null } }).note).toBe('Commander');
    expect(deckLine({ ...block, deck: { label: null, source: 'none', matched_cards: null } })).toEqual({ name: 'Not revealed yet', note: null });
    expect(deckLine(null).name).toBe('Not revealed yet');
    expect(railTitle(block)).toBe('Rakdos Midrange (likely · 3 cards match your history) · You 3–1');
  });

  it('keeps the band note short enough for one line', () => {
    const block = opponentBlock();
    expect(bandText(block)).toEqual({ label: 'Likely deck', note: '3 cards match history' });
    expect(bandText({ ...block, deck: { label: 'Kenrith', source: 'commander', matched_cards: null } }).note).toBe('Their commander');
    expect(bandText({ ...block, deck: { label: 'Rakdos', source: 'colors', matched_cards: null } }).note).toBe('From their colours');
    expect(bandText(null)).toEqual({ label: 'Their deck', note: 'Nothing revealed yet' });
  });

  it('orders colours WUBRG and ignores anything else', () => {
    expect(colorLetters('RBx')).toEqual(['B', 'R']);
    expect(colorLetters('')).toEqual([]);
    expect(colorLetters(null)).toEqual([]);
  });

  it('finds new plays, and treats the first look at a game as nothing new', () => {
    const before = opponentBlock().seen;
    const after = before.map((c) => (c.name === 'Cut Down' ? { ...c, count: 2 } : c)).concat([{ name: 'Duress', type: 'Sorcery', mana_cost: '{B}', mana_value: 1, count: 1 }]);
    expect(freshPlays(before, after)).toEqual(['Cut Down', 'Duress']);
    expect(freshPlays(null, after)).toEqual([]);
  });

  it('shows the block only while the tracker answers with one', () => {
    expect(opponentOf(opponentPayload())?.colors).toBe('BR');
    expect(opponentOf(idlePayload())).toBeNull();
    expect(opponentOf({ ...offlinePayload(), opponent: opponentBlock() })).toBeNull();
    expect(opponentOf(null)).toBeNull();
  });
});

describe('OpponentRail', () => {
  it('shows the colours, cards seen and your record, and names the deck in its tooltip', () => {
    const { container } = render(<OpponentRail opponent={opponentBlock()} dock="right" pulse={false} onOpenPanel={noop} onDragStart={noop} />);
    expect(Array.from(container.querySelectorAll('.opp-pips img')).map((img) => img.getAttribute('alt'))).toEqual(['B', 'R']);
    expect(screen.getByLabelText('4 nonland cards seen').textContent).toContain('4');
    expect(container.querySelector('.opp-vs')?.textContent).toBe('3–1');
    expect(container.querySelector('.opp-rail')?.getAttribute('title')).toMatch(/^Rakdos Midrange/);
    expect(container.querySelector('.cell.pulse')).toBeNull();
  });

  it('pulses the Seen cell, and shows an empty ring and dashes before anything is known', () => {
    const pulsing = render(<OpponentRail opponent={opponentBlock()} dock="right" pulse onOpenPanel={noop} onDragStart={noop} />);
    expect(pulsing.container.querySelector('.cell.pulse')).toBeTruthy();
    cleanup();
    const { container } = render(<OpponentRail opponent={{ ...opponentBlock(), colors: '', record: null, seen: [] }} dock="left" pulse={false} onOpenPanel={noop} onDragStart={noop} />);
    expect(container.querySelector('.opp-ring')).toBeTruthy();
    expect(container.querySelector('.opp-vs')?.textContent).toBe('—');
  });

  it('keeps the record inside the hairlines: a notch smaller at three digits, a win rate from four', () => {
    expect(recordCell({ wins: 3, losses: 1 })).toEqual({ kind: 'record', wide: false, rate: 0 });
    expect(recordCell({ wins: 12, losses: 1 })).toEqual({ kind: 'record', wide: true, rate: 0 });
    expect(recordCell({ wins: 12, losses: 10 })).toEqual({ kind: 'rate', wide: false, rate: 55 });
    expect(recordCell(null).kind).toBe('none');
    const { container } = render(<OpponentRail opponent={{ ...opponentBlock(), record: { wins: 108, losses: 99 } }} dock="right" pulse={false} onOpenPanel={noop} onDragStart={noop} />);
    const cell = container.querySelector('.opp-vs')!;
    expect(cell.textContent).toBe('52%');
    expect(cell.getAttribute('title')).toBe('108–99');
  });

  it('opens the panel from its arrow', () => {
    const open = vi.fn();
    render(<OpponentRail opponent={opponentBlock()} dock="right" pulse={false} onOpenPanel={open} onDragStart={noop} />);
    fireEvent.click(screen.getByRole('button', { name: /open the opponent panel/i }));
    expect(open).toHaveBeenCalled();
  });
});

function panelProps(overrides: Partial<Parameters<typeof OpponentPanel>[0]> = {}) {
  const payload = opponentPayload();
  return {
    payload,
    opponent: payload.opponent ?? null,
    settings: defaultSettings(),
    pinned: true,
    dock: 'right' as const,
    fresh: new Set<string>(),
    onCollapse: noop,
    onTogglePin: noop,
    onDragStart: noop,
    onHover: noop,
    cursor: null,
    ...overrides,
  };
}

describe('OpponentPanel', () => {
  it('is laid out like the deck panel: deck name in the header, the band with three boxes, rows by type, lands folded', () => {
    const { container } = render(<OpponentPanel {...panelProps()} />);
    expect(container.querySelector('.head .deck b')?.textContent).toBe('Rakdos Midrange');
    expect(screen.getByText('Std. BO1 Ranked · vs sansastark (1–2)')).toBeTruthy();
    // The deck panel's land-drop band, reused: label, note and three boxes.
    expect(container.querySelector('.lands.opp-band .t')?.textContent).toBe('Likely deck3 cards match history');
    expect(Array.from(container.querySelectorAll('.opp-band .odd')).map((box) => box.textContent)).toEqual(['SEEN4', 'LANDS4', 'YOU3–1']);
    expect(Array.from(container.querySelectorAll('.list .grp')).map((g) => g.textContent)).toEqual([
      'Creatures (1)',
      'Instants & sorceries (3)',
      'Artifacts & enchantments (1)',
    ]);
    // The deck panel's row: name over cost, the count in the number column.
    const row = container.querySelector('.row[data-key="Go for the Throat"]')!;
    expect(row.querySelector('.body .nm')?.textContent).toBe('Go for the Throat');
    expect(row.querySelector('.body .mana')).toBeTruthy();
    expect(row.querySelector('.right .cnt')?.textContent).toBe('×2');
    expect(screen.getByText('Fable of the Mirror-Breaker')).toBeTruthy();
    // Lands fold into one row, like the deck panel's, and open on click.
    const landsRow = container.querySelector<HTMLButtonElement>('.row.land-row')!;
    expect(landsRow.querySelector('.cnt')?.textContent).toBe('×4');
    expect(container.querySelector('.row[data-key="Blood Crypt"]')).toBeNull();
    fireEvent.click(landsRow);
    expect(container.querySelector('.row.sub[data-key="Blood Crypt"]')).toBeTruthy();
  });

  it('highlights new plays and says when nothing is played yet', () => {
    const { container } = render(<OpponentPanel {...panelProps({ fresh: new Set(['Cut Down']) })} />);
    expect(container.querySelector('.row.fresh')?.getAttribute('data-key')).toBe('Cut Down');
    cleanup();
    const empty = render(<OpponentPanel {...panelProps({ opponent: { ...opponentBlock(), seen: [], lands: 0, deck: { label: null, source: 'none', matched_cards: null }, record: null } })} />);
    expect(empty.getByText('Nothing played yet')).toBeTruthy();
    expect(empty.container.querySelector('.list-body.bare')).toBeTruthy();
    expect(empty.container.querySelector('.head .deck b')?.textContent).toBe('Opponent');
    expect(empty.container.querySelector('.opp-band .t small')?.textContent).toBe('Nothing revealed yet');
    expect(empty.container.querySelector('.opp-band .odd.you')?.textContent).toBe('YOU—');
  });

  it('reports the row under the shell-reported cursor for the hover card', () => {
    const onHover = vi.fn();
    const { container, rerender } = render(<OpponentPanel {...panelProps({ onHover })} />);
    const row = container.querySelector<HTMLElement>('.row[data-key="Cut Down"]')!;
    const original = document.elementFromPoint;
    document.elementFromPoint = () => row;
    try {
      rerender(<OpponentPanel {...panelProps({ onHover, cursor: { x: 10, y: 10 } })} />);
      expect(onHover).toHaveBeenLastCalledWith(expect.objectContaining({ name: 'Cut Down' }), expect.anything());
      expect(container.querySelector('.row.hot')?.getAttribute('data-key')).toBe('Cut Down');
      // The Lands row highlights but has no card to show.
      const lands = container.querySelector<HTMLElement>('.row.land-row')!;
      document.elementFromPoint = () => lands;
      rerender(<OpponentPanel {...panelProps({ onHover, cursor: { x: 10, y: 300 } })} />);
      expect(lands.classList.contains('hot')).toBe(true);
      expect(onHover).toHaveBeenLastCalledWith(null, null);
    } finally {
      document.elementFromPoint = original;
    }
    rerender(<OpponentPanel {...panelProps({ onHover, cursor: null })} />);
    expect(onHover).toHaveBeenLastCalledWith(null, null);
    expect(container.querySelector('.list [data-key].hot')).toBeNull();
  });

  it('words the header line like the deck panel', () => {
    expect(headLine(false, 'Standard Best-of-1 (Ranked)', 'sansastark', { wins: 1, losses: 2 })).toBe('Std. BO1 Ranked · vs sansastark (1–2)');
    expect(headLine(true, 'Standard Best-of-1 (Ranked)', 'sansastark', null)).toBe('Game over · Std. BO1 Ranked · vs sansastark');
    expect(headLine(false, null, null, null)).toBe('');
  });

  it('measures its natural height from its blocks, so a short list shrinks the window', () => {
    const panel = document.createElement('div');
    const block = (cls: string, height: number) => {
      const el = document.createElement('div');
      el.className = cls;
      Object.defineProperty(el, 'offsetHeight', { value: height });
      return el;
    };
    const list = document.createElement('div');
    list.className = 'list';
    list.appendChild(block('list-body', 120));
    panel.append(block('head', 40), block('lands opp-band', 40), list);
    expect(opponentPanelHeight(panel)).toBe(200);
  });
});

describe('Flyout: opponent panel', () => {
  it('has no switch for the panels (the tracker\'s Settings owns them); a panel that is off has no hotkey', () => {
    const onChange = vi.fn();
    render(<Flyout settings={defaultSettings()} platform="windows" onChange={onChange} onClose={noop} onQuit={noop} />);
    expect(screen.queryByLabelText('Opponent panel')).toBeNull();
    expect((screen.getByText('Alt+Shift+O') as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByText('Alt+Shift+T') as HTMLButtonElement).disabled).toBe(false);
    cleanup();
    render(<Flyout settings={{ ...defaultSettings(), opponentPanel: false }} platform="windows" onChange={onChange} onClose={noop} onQuit={noop} />);
    const hotkey = screen.getByText('Alt+Shift+O') as HTMLButtonElement;
    expect(hotkey.disabled).toBe(true);
    expect(hotkey.closest('.r')?.classList.contains('off')).toBe(true);
    cleanup();
    // Opponent only: the deck panel's toggle is the one without a use.
    render(<Flyout settings={{ ...defaultSettings(), deckPanel: false }} platform="windows" onChange={onChange} onClose={noop} onQuit={noop} />);
    expect((screen.getByText('Alt+Shift+T') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText('Alt+Shift+O') as HTMLButtonElement).disabled).toBe(false);
  });

  it('Restore defaults leaves which panels are on, and their open and pin state, alone', () => {
    const current = { ...defaultSettings(), deckPanel: false, opponentPanel: true, opponentOpen: true, opponentPinned: false };
    const next = restoredDefaults(current);
    expect(next.deckPanel).toBe(false);
    expect(next.opponentPanel).toBe(true);
    expect(next.opponentOpen).toBe(true);
    expect(next.opponentPinned).toBe(false);
  });

  it('shows the settings gear on the opponent panel only when asked to (the deck panel is off)', () => {
    render(<OpponentPanel {...panelProps()} />);
    expect(screen.queryByLabelText('Settings')).toBeNull();
    cleanup();
    const onOpenSettings = vi.fn();
    render(<OpponentPanel {...panelProps({ onOpenSettings })} />);
    fireEvent.click(screen.getByLabelText('Settings'));
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });
});
