/** Transport bar: scrub bar, turn/step/play buttons, speed, pacing, go-to-turn and counters. */
import { useState } from 'react';
import type { FormEvent, RefObject } from 'react';
import { formatClock } from '../logText';
import { PLAYBACK_SPEEDS } from '../player';
import type { PlaybackClock, PlaybackSnapshot, PlaybackSpeed } from '../player';
import { savePrefs } from '../prefs';
import { openingEndIndex } from '../scrub';
import type { ReplayStream } from '../types';
import { ScrubBar } from './ScrubBar';

interface ReplayControlsProps {
  stream: ReplayStream;
  clock: PlaybackClock;
  snapshot: PlaybackSnapshot;
  goToTurnRef: RefObject<HTMLInputElement | null>;
}

export function ReplayControls({ stream, clock, snapshot, goToTurnRef }: ReplayControlsProps) {
  const [turnInput, setTurnInput] = useState('');
  const events = stream.events;
  // Counted from the first turn header: the opening deal is not part of playback.
  const first = openingEndIndex(events);
  const total = events.length - first;
  const current = events[snapshot.index];
  const duration = events[total - 1]?.t ?? 0;
  const turns = stream.turns;
  const maxTurn = turns.length ? turns[turns.length - 1].turn : 0;

  const goToTurn = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const turn = Number(turnInput);
    if (!Number.isFinite(turn) || !turns.length) return;
    const clamped = Math.max(turns[0].turn, Math.min(maxTurn, Math.round(turn)));
    clock.seekTurn(clamped);
    setTurnInput('');
    goToTurnRef.current?.blur();
  };

  return (
    <div className="replay-controls">
      <ScrubBar stream={stream} clock={clock} snapshot={snapshot} />
      <div className="replay-controls-row">
        <div className="replay-transport" role="group" aria-label="Playback">
          <button type="button" className="replay-btn" onClick={() => clock.prevTurn()} title="Previous turn (J)">
            <span className="replay-btn-icon" aria-hidden="true">⏮</span>
            Turn
          </button>
          <button type="button" className="replay-btn" onClick={() => clock.step(-1)} title="Step back (←)">
            <span className="replay-btn-icon" aria-hidden="true">◀</span>
            Step
          </button>
          <button
            type="button"
            className="replay-btn replay-btn-play"
            onClick={() => clock.toggle()}
            aria-pressed={snapshot.playing}
            title="Play / pause (Space)"
          >
            <span className="replay-btn-icon" aria-hidden="true">{snapshot.playing ? '❚❚' : '▶'}</span>
            {snapshot.playing ? 'Pause' : 'Play'}
          </button>
          <button type="button" className="replay-btn" onClick={() => clock.step(1)} title="Step forward (→)">
            Step
            <span className="replay-btn-icon" aria-hidden="true">▶</span>
          </button>
          <button type="button" className="replay-btn" onClick={() => clock.nextTurn()} title="Next turn (K)">
            Turn
            <span className="replay-btn-icon" aria-hidden="true">⏭</span>
          </button>
          <label className="replay-speed" title="Speed ([ and ])">
            <span className="visually-hidden">Speed</span>
            <select
              value={snapshot.speed}
              onChange={(event) => savePrefs({ speed: Number(event.target.value) as PlaybackSpeed })}
            >
              {PLAYBACK_SPEEDS.map((speed) => (
                <option key={speed} value={speed}>
                  {speed}×
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="replay-btn"
            aria-pressed={snapshot.pacing === 'realtime'}
            onClick={() => savePrefs({ pacing: snapshot.pacing === 'paced' ? 'realtime' : 'paced' })}
            title="Paced holds every action for a readable moment; real time keeps the game's own gaps"
          >
            {snapshot.pacing === 'paced' ? 'Paced' : 'Real time'}
          </button>
          <form className="replay-goto" onSubmit={goToTurn}>
            <label>
              <span className="visually-hidden">Go to turn</span>
              <input
                ref={goToTurnRef}
                type="number"
                inputMode="numeric"
                min={turns[0]?.turn ?? 1}
                max={maxTurn || undefined}
                placeholder="Go to turn…"
                value={turnInput}
                onChange={(event) => setTurnInput(event.target.value)}
                title="Go to turn (G)"
              />
            </label>
          </form>
        </div>
        <div className="replay-counters" aria-live="off">
          <span>
            Event {total ? snapshot.index - first + 1 : 0} / {total}
          </span>
          <span>
            {formatClock(current?.t ?? 0)} / {formatClock(duration)}
          </span>
          <span className="replay-shortcuts">Space play · ←/→ step · J/K turn · [ ] speed · Wheel zoom · T options</span>
        </div>
      </div>
    </div>
  );
}
