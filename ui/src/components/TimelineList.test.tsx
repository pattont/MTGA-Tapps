import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { GameTimelineRow } from '../api';
import { TimelineList } from './TimelineList';

const timelineRows: GameTimelineRow[] = [
  {
    turn_number: 1,
    phase: 'main',
    step: null,
    event_type: 'land',
    actor_role: 'opponent',
    text: '[1:14] Opponent: played [Island (Land)]',
    text_segments: [
      { kind: 'text', text: '[1:14] Opponent: played [' },
      { kind: 'card', text: 'Island', card_name: 'Island', card_type: 'Land' },
      { kind: 'text', text: ' (Land)]' },
    ],
    player_life: 20,
    opponent_life: 20,
  },
  {
    turn_number: 2,
    phase: 'main',
    step: null,
    event_type: 'cast',
    actor_role: 'player',
    text: '[0:25] You: cast [Case of the Stashed Skeleton (Enchantment)]',
    text_segments: [
      { kind: 'text', text: '[0:25] You: cast [' },
      {
        kind: 'card',
        text: 'Case of the Stashed Skeleton',
        card_name: 'Case of the Stashed Skeleton',
      },
      { kind: 'text', text: ' (Enchantment)]' },
    ],
    player_life: 20,
    opponent_life: 20,
  },
  {
    turn_number: 2,
    phase: 'combat',
    step: 'attack',
    event_type: 'attack',
    actor_role: 'player',
    text: '[0:30] [Forsaken Miner (Creature 2/2)] attacked [Sheltered by Ghosts (Enchantment)]',
    text_segments: [
      { kind: 'text', text: '[0:30] [' },
      {
        kind: 'card',
        text: 'Forsaken Miner',
        card_name: 'Forsaken Miner',
        card_type: 'Creature',
      },
      { kind: 'text', text: ' (Creature 2/2)] attacked [' },
      {
        kind: 'card',
        text: 'Sheltered by Ghosts',
        card_name: 'Sheltered by Ghosts',
        card_type: 'Enchantment',
      },
      { kind: 'text', text: ' (Enchantment)]' },
    ],
    player_life: 20,
    opponent_life: 20,
  },
];

describe('TimelineList card references', () => {
  it('links yellow brackets with the card and renders compact type chips inline', () => {
    render(
      <TimelineList
        rows={timelineRows}
        cardReturnHash="#/game/game-1?focus=game-timeline"
      />,
    );

    const caseLink = screen.getByRole('link', { name: '[Case of the Stashed Skeleton]' });
    expect(caseLink).toHaveClass('timeline-card-reference');
    expect(caseLink).toHaveAttribute(
      'href',
      '#/card/Case%20of%20the%20Stashed%20Skeleton?return=%23%2Fgame%2Fgame-1%3Ffocus%3Dgame-timeline',
    );
    const brackets = caseLink.querySelectorAll('.timeline-card-bracket');
    expect(brackets).toHaveLength(2);
    expect(Array.from(brackets).map((bracket) => bracket.textContent)).toEqual(['[', ']']);

    const timeline = caseLink.closest('ol');
    expect(timeline).not.toBeNull();
    expect(within(timeline as HTMLElement).getAllByText('Enchantment')).toHaveLength(2);
    within(timeline as HTMLElement).getAllByText('Enchantment').forEach((chip) => {
      expect(chip).toHaveClass('type-chip', 'type-chip-enchantment', 'type-chip-compact');
    });
    expect(within(timeline as HTMLElement).getByText('Creature')).toHaveClass(
      'type-chip',
      'type-chip-creature',
      'type-chip-compact',
    );
    expect(within(timeline as HTMLElement).getByText('2/2')).toHaveClass('timeline-card-metadata');
    const islandLink = within(timeline as HTMLElement).getByRole('link', { name: '[Island]' });
    const islandEvent = islandLink.closest('.timeline-event');
    expect(islandEvent).not.toBeNull();
    const islandChip = (islandEvent as HTMLElement).querySelector('.timeline-chip');
    expect(islandChip).toHaveTextContent('Land');
    expect(islandChip).toHaveClass('timeline-chip-land');
    // The compact TypeChip stays suppressed for land cards on land events.
    expect((islandEvent as HTMLElement).querySelector('.type-chip')).toBeNull();
    expect(within(timeline as HTMLElement).queryByText('(Enchantment)')).not.toBeInTheDocument();
    expect(within(timeline as HTMLElement).queryByText('(Creature 2/2)')).not.toBeInTheDocument();
    expect(within(timeline as HTMLElement).getByText('[0:25] You: cast')).toBeInTheDocument();
  });

  it('searches the lines by card name or any other words, and with the other filters', () => {
    const { container } = render(<TimelineList rows={timelineRows} />);
    const lines = () => Array.from(container.querySelectorAll('.timeline-event .timeline-text')).map((el) => el.textContent);
    const total = lines().length;
    const search = screen.getByLabelText('Search');
    fireEvent.change(search, { target: { value: 'stashed SKELETON' } });
    expect(lines()).toHaveLength(1);
    expect(lines()[0]).toContain('Case of the Stashed Skeleton');
    expect(screen.getByRole('status').textContent).toBe(`1 of ${total} events`);
    // Words that are not a card name match too.
    fireEvent.change(search, { target: { value: 'played' } });
    expect(lines()[0]).toContain('Island');
    // Narrowed by the actor filter as well.
    fireEvent.change(screen.getByLabelText('Actor'), { target: { value: 'player' } });
    expect(screen.getByText('No events match the current filters.')).toBeTruthy();
    fireEvent.change(search, { target: { value: '   ' } });
    expect(lines().length).toBeGreaterThan(0);
  });

  it('displays a single slash while retaining the canonical card route', () => {
    render(
      <TimelineList
        rows={[
          {
            turn_number: 3,
            phase: 'main',
            step: null,
            event_type: 'cast',
            actor_role: 'player',
            text: '[0:42] You: cast [Unholy Annex // Ritual Chamber (Enchantment)]',
            text_segments: [
              { kind: 'text', text: '[0:42] You: cast [' },
              {
                kind: 'card',
                text: 'Unholy Annex // Ritual Chamber',
                card_name: 'Unholy Annex // Ritual Chamber',
                card_type: 'Enchantment',
              },
              { kind: 'text', text: ' (Enchantment)]' },
            ],
            player_life: 20,
            opponent_life: 20,
          },
        ]}
      />,
    );

    const link = screen.getByRole('link', { name: '[Unholy Annex / Ritual Chamber]' });
    expect(link).toHaveAttribute(
      'href',
      '#/card/Unholy%20Annex%20%2F%2F%20Ritual%20Chamber',
    );
    expect(screen.queryByText('Unholy Annex // Ritual Chamber')).not.toBeInTheDocument();
  });
});

describe('scry lines', () => {
  it('badge scry events as Scry rather than a generic ability', () => {
    const rows: GameTimelineRow[] = [
      {
        turn_number: 2,
        phase: 'main',
        step: null,
        event_type: 'scry',
        actor_role: 'player',
        text: '[2:00] You: scried 2 — kept [Opt] on top, bottomed [Plains]',
        text_segments: [
          { kind: 'text', text: '[2:00] You: scried 2 — kept [' },
          { kind: 'card', text: 'Opt', card_name: 'Opt' },
          { kind: 'text', text: '] on top, bottomed [' },
          { kind: 'card', text: 'Plains', card_name: 'Plains', card_type: 'Land' },
          { kind: 'text', text: ']' },
        ],
        player_life: 20,
        opponent_life: 20,
      },
    ];
    render(<TimelineList rows={rows} showFilters={false} />);
    const badge = screen.getByText('Scry');
    expect(badge.className).toContain('timeline-chip-scry');
    expect(screen.getByText(/scried 2/)).toBeTruthy();
  });
});

describe('TimelineList replay deep links', () => {
  const rows: GameTimelineRow[] = timelineRows.map((row, index) => ({ ...row, id: 700 + index }));

  it('turns each row elapsed time into a replay link when given an href builder', () => {
    render(<TimelineList rows={rows} replayHref={(row) => (row.id ? `#/replay/g?row=${row.id}` : null)} />);
    const link = screen.getByRole('link', { name: 'Watch the replay from 1:14' });
    expect(link).toHaveAttribute('href', '#/replay/g?row=700');
    expect(link).toHaveClass('timeline-replay-link', 'replay-wide-only');
    expect(link.querySelector('svg')).not.toBeNull();
    expect(link).toHaveTextContent('1:14');
    // The time is not repeated in the text; narrow screens get a plain fallback.
    const item = link.closest('li') as HTMLElement;
    expect(within(item).getByText('[1:14]', { exact: false })).toHaveClass('replay-narrow-only');
    expect(item.querySelector('.timeline-text')?.textContent).toBe('1:14[1:14] Opponent: played [Island]');
    expect(screen.getByRole('link', { name: 'Watch the replay from 0:25' })).toHaveAttribute('href', '#/replay/g?row=701');
  });

  it('renders no replay links without an href builder or for rows without an id', () => {
    const { unmount } = render(<TimelineList rows={rows} />);
    expect(screen.queryByRole('link', { name: /Watch the replay/ })).not.toBeInTheDocument();
    unmount();
    render(<TimelineList rows={timelineRows} replayHref={(row) => (row.id ? `#/replay/g?row=${row.id}` : null)} />);
    expect(screen.queryByRole('link', { name: /Watch the replay/ })).not.toBeInTheDocument();
    expect(screen.getAllByText(/\[1:14\] Opponent: played/).length).toBeGreaterThan(0);
  });

  it('links the time of indented stack lines too', () => {
    const stackRow: GameTimelineRow = {
      ...rows[0],
      id: 12,
      event_type: 'stack_resolve',
      text: '\t[0:37] Stack: [Opt (Instant)] [resolved]',
      text_segments: [
        { kind: 'text', text: '\t[0:37] Stack: [' },
        { kind: 'card', text: 'Opt', card_name: 'Opt', card_type: 'Instant' },
        { kind: 'text', text: ' (Instant)] [resolved]' },
      ],
    };
    render(<TimelineList rows={[stackRow]} replayHref={() => '#/replay/g?row=12'} />);
    const link = screen.getByRole('link', { name: 'Watch the replay from 0:37' });
    expect(link.closest('li')?.querySelector('.timeline-text')?.textContent).toBe('0:37[0:37] Stack: [Opt]Instant');
  });

  it('puts an icon link at the end of rows that have no elapsed time', () => {
    const untimed: GameTimelineRow = { ...rows[0], id: 9, text: 'Opponent conceded', text_segments: [{ kind: 'text', text: 'Opponent conceded' }] };
    render(<TimelineList rows={[untimed]} replayHref={() => '#/replay/g?row=9'} />);
    expect(screen.getByRole('link', { name: 'Watch the replay from this event' })).toHaveClass('timeline-replay-link-icon');
  });
});
