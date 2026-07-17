import { useMemo, useState } from 'react';
import type { GameTimelineRow } from '../api';

interface TurnGroup {
  turnLabel: string;
  events: GameTimelineRow[];
}

function groupByTurn(rows: GameTimelineRow[]): TurnGroup[] {
  const groups: TurnGroup[] = [];
  let current: TurnGroup | null = null;
  for (const row of rows) {
    const turnLabel = row.turn_number === null || row.turn_number === undefined ? 'Pre-game' : `Turn ${row.turn_number}`;
    if (!current || current.turnLabel !== turnLabel) {
      current = { turnLabel, events: [] };
      groups.push(current);
    }
    current.events.push(row);
  }
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

export function TimelineList({ rows }: { rows: GameTimelineRow[] }) {
  const [eventType, setEventType] = useState('');
  const [actor, setActor] = useState('');

  const eventTypes = useMemo(
    () =>
      Array.from(
        new Set(rows.map((row) => row.event_type).filter((value): value is string => Boolean(value))),
      ).sort(),
    [rows],
  );

  const filtered = useMemo(
    () =>
      rows.filter(
        (row) =>
          (!eventType || row.event_type === eventType) &&
          (!actor || (row.actor_role ?? 'system') === actor),
      ),
    [rows, eventType, actor],
  );
  const groups = useMemo(() => groupByTurn(filtered), [filtered]);

  if (rows.length === 0) {
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
          {filtered.length} of {rows.length} events
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
                  {life ? <span className="timeline-life" title="Life totals (you – opponent)">♥ {life}</span> : null}
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
                      <span className="timeline-text">{event.text}</span>
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
