import { render, screen, within } from '@testing-library/react';
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
