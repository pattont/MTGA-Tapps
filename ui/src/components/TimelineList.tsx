import { useMemo, useState } from 'react';
import type { GameTimelineRow, GameTurnTimingRow, TimelineTextSegment } from '../api';
import { formatCardName, formatTurnDuration } from '../format';
import { CardLink } from './CardLink';
import { TypeChip } from './TypeChip';

interface TurnGroup {
  turnNumber: number | null;
  turnLabel: string;
  events: GameTimelineRow[];
  timing: GameTurnTimingRow | null;
}

function groupByTurn(rows: GameTimelineRow[], timings: GameTurnTimingRow[]): TurnGroup[] {
  const timingByTurn = new Map(timings.map((timing) => [timing.turn_number, timing]));
  const turnNumbers = new Set<number>();
  const pregameEvents: GameTimelineRow[] = [];

  rows.forEach((row) => {
    if (row.turn_number === null || row.turn_number === undefined) {
      pregameEvents.push(row);
    } else {
      turnNumbers.add(row.turn_number);
    }
  });
  timings.forEach((timing) => turnNumbers.add(timing.turn_number));

  const groups: TurnGroup[] = [];
  if (pregameEvents.length > 0) {
    groups.push({ turnNumber: null, turnLabel: 'Pre-game', events: pregameEvents, timing: null });
  }
  Array.from(turnNumbers)
    .sort((left, right) => left - right)
    .forEach((turnNumber) => {
      groups.push({
        turnNumber,
        turnLabel: `Turn ${turnNumber}`,
        events: rows.filter((row) => row.turn_number === turnNumber),
        timing: timingByTurn.get(turnNumber) ?? null,
      });
    });
  return groups;
}

function lastLife(events: GameTimelineRow[]): string | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const { player_life, opponent_life } = events[i];
    if (player_life !== null && opponent_life !== null) {
      return `${player_life} – ${opponent_life}`;
    }
  }
  return null;
}

function actorClass(actorRole: string | null): string {
  if (actorRole === 'player') {
    return 'timeline-event timeline-event-player';
  }
  if (actorRole === 'opponent') {
    return 'timeline-event timeline-event-opponent';
  }
  return 'timeline-event timeline-event-system';
}

function actorLabel(actorRole: string | null): string | null {
  if (actorRole === 'player') {
    return 'You';
  }
  if (actorRole === 'opponent') {
    return 'Opp';
  }
  return null;
}

function timingRoleLabel(role: GameTurnTimingRow['role']): string {
  if (role === 'player') {
    return 'You';
  }
  if (role === 'opponent') {
    return 'Opponent';
  }
  return 'Unknown';
}

function cardMetadata(typeSuffix: string | null, cardType: string | null | undefined): string | null {
  if (!typeSuffix) {
    return null;
  }
  let metadata = typeSuffix.trim();
  if (cardType) {
    const escapedType = cardType.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    metadata = metadata.replace(new RegExp(`\\b${escapedType}\\b`, 'i'), '').trim();
  }
  return metadata || null;
}

const TIMELINE_CARD_TYPES = [
  'Planeswalker',
  'Enchantment',
  'Artifact',
  'Creature',
  'Sorcery',
  'Instant',
  'Battle',
  'Land',
];

function inferredCardType(typeSuffix: string | null): string | null {
  if (!typeSuffix) {
    return null;
  }
  return (
    TIMELINE_CARD_TYPES.find((type) =>
      new RegExp(`\\b${type}\\b`, 'i').test(typeSuffix),
    ) ?? null
  );
}

interface TimelineCardDecoration {
  bracketed: boolean;
  cardType: string | null;
  metadata: string | null;
}

function decorateCardSegments(segments: TimelineTextSegment[]): {
  segments: TimelineTextSegment[];
  decorations: Map<number, TimelineCardDecoration>;
} {
  const mutableSegments = segments.map((segment) => ({ ...segment }));
  const decorations = new Map<number, TimelineCardDecoration>();

  mutableSegments.forEach((segment, index) => {
    if (segment.kind !== 'card') {
      return;
    }
    const previous = mutableSegments[index - 1];
    const next = mutableSegments[index + 1];
    if (
      previous?.kind !== 'text'
      || next?.kind !== 'text'
      || !previous.text.endsWith('[')
    ) {
      decorations.set(index, { bracketed: false, cardType: null, metadata: null });
      return;
    }
    const closing = next.text.match(/^\s*(?:\(([^()]*)\))?\]/);
    if (!closing) {
      decorations.set(index, { bracketed: false, cardType: null, metadata: null });
      return;
    }
    const typeSuffix = closing[1] ?? null;
    const cardType = segment.card_type ?? inferredCardType(typeSuffix);
    previous.text = previous.text.slice(0, -1);
    next.text = next.text.slice(closing[0].length);
    decorations.set(index, {
      bracketed: true,
      cardType,
      metadata: cardMetadata(typeSuffix, cardType),
    });
  });

  return { segments: mutableSegments, decorations };
}

function TimelineText({ event, returnHash }: { event: GameTimelineRow; returnHash?: string }) {
  const sourceSegments = event.text_segments?.length
    ? event.text_segments
    : [{ kind: 'text' as const, text: event.text }];
  const { decorations, segments } = decorateCardSegments(sourceSegments);
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === 'text') {
          return segment.text ? <span key={`text-${index}`}>{segment.text}</span> : null;
        }
        const decoration = decorations.get(index);
        if (!decoration?.bracketed) {
          return (
            <CardLink key={`${segment.card_name}-${index}`} cardName={segment.card_name} returnHash={returnHash}>
              {formatCardName(segment.text)}
            </CardLink>
          );
        }
        const showCardType = !(
          event.event_type?.toLocaleLowerCase() === 'land'
          && decoration.cardType?.toLocaleLowerCase() === 'land'
        );
        return (
          <span key={`${segment.card_name}-${index}`} className="timeline-card-entry">
            <CardLink
              className="timeline-card-reference"
              cardName={segment.card_name}
              returnHash={returnHash}
            >
              <span className="timeline-card-bracket">[</span>
              {formatCardName(segment.text)}
              <span className="timeline-card-bracket">]</span>
            </CardLink>
            {decoration.cardType && showCardType ? (
              <TypeChip compact type={decoration.cardType} />
            ) : null}
            {decoration.metadata ? (
              <span className="timeline-card-metadata">{decoration.metadata}</span>
            ) : null}
          </span>
        );
      })}
    </>
  );
}

export function TimelineList({
  rows,
  timings = [],
  cardReturnHash,
}: {
  rows: GameTimelineRow[];
  timings?: GameTurnTimingRow[];
  cardReturnHash?: string;
}) {
  const [eventType, setEventType] = useState('');
  const [actor, setActor] = useState('');

  const visibleRows = useMemo(
    () => rows.filter((row) => row.event_type !== 'turn'),
    [rows],
  );
  const eventTypes = useMemo(
    () =>
      Array.from(
        new Set(visibleRows.map((row) => row.event_type).filter((value): value is string => Boolean(value))),
      ).sort(),
    [visibleRows],
  );

  const filtered = useMemo(
    () =>
      visibleRows.filter(
        (row) =>
          (!eventType || row.event_type === eventType) &&
          (!actor || (row.actor_role ?? 'system') === actor),
      ),
    [visibleRows, eventType, actor],
  );
  const groups = useMemo(
    () => groupByTurn(filtered, eventType || actor ? [] : timings),
    [actor, eventType, filtered, timings],
  );

  if (visibleRows.length === 0 && timings.length === 0) {
    return <p className="empty-state">No timeline events were captured for this game.</p>;
  }

  return (
    <div className="timeline-wrap">
      <div className="timeline-filter" role="group" aria-label="Timeline filters">
        <label>
          <span>Event Type</span>
          <select value={eventType} onChange={(event) => setEventType(event.target.value)}>
            <option value="">All events</option>
            {eventTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Actor</span>
          <select value={actor} onChange={(event) => setActor(event.target.value)}>
            <option value="">Everyone</option>
            <option value="player">You</option>
            <option value="opponent">Opponent</option>
            <option value="system">Game</option>
          </select>
        </label>
        <span className="timeline-count" role="status">
          {filtered.length} of {visibleRows.length} events
        </span>
      </div>
      {groups.length === 0 ? (
        <p className="empty-state">No events match the current filters.</p>
      ) : (
        <ol className="timeline">
          {groups.map((group, groupIndex) => {
            const life = lastLife(group.events);
            return (
              <li key={`${group.turnLabel}-${groupIndex}`} className="timeline-turn">
                <div className="timeline-turn-header">
                  <strong>{group.turnLabel}</strong>
                  <div className="timeline-turn-meta">
                    {group.timing ? (
                      <span
                        className="timeline-turn-duration"
                        title={`${
                          group.timing.timing_source === 'estimated_header_events' ? 'Estimated' : 'Live'
                        } turn timing`}
                      >
                        {timingRoleLabel(group.timing.role)} · {formatTurnDuration(group.timing.duration_seconds)}
                        {group.timing.timing_source === 'estimated_header_events' ? ' · Estimated' : ''}
                      </span>
                    ) : null}
                    {life ? (
                      <span className="timeline-life" title="Life totals (you – opponent)">
                        ♥ {life}
                      </span>
                    ) : null}
                  </div>
                </div>
                <ul>
                  {group.events.map((event, eventIndex) => (
                    <li key={eventIndex} className={actorClass(event.actor_role)}>
                      {actorLabel(event.actor_role) ? (
                        <span className="timeline-actor">{actorLabel(event.actor_role)}</span>
                      ) : null}
                      <span className={`timeline-chip timeline-chip-${event.event_type ?? 'other'}`}>
                        {event.event_type ?? 'event'}
                      </span>
                      <span className="timeline-text">
                        <TimelineText event={event} returnHash={cardReturnHash} />
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
