/** Turn/phase chip, life totals (pulsing on change) and hand/library counts per seat. */
import { Fragment, memo, useState } from 'react';
import { describeGameEnd } from '../gameEnd';
import { formatClock, phaseLabel } from '../logText';
import type { BoardState } from '../reducer';
import { seatNumber } from '../scene/labels';
import type { ReplayStream } from '../types';

function LifeValue({ life }: { life: number }) {
  const [shown, setShown] = useState({ life, pulse: 0, up: false });
  if (shown.life !== life) {
    setShown({ life, pulse: shown.pulse + 1, up: life > shown.life });
  }
  const className = shown.pulse
    ? `replay-life-value ${shown.up ? 'replay-life-up' : 'replay-life-down'}`
    : 'replay-life-value';
  return (
    <strong key={shown.pulse} className={className}>
      {life}
    </strong>
  );
}

/** This action's life change for a seat ("−3", "+3"), beside its life total while the action lasts. */
function LifeChange({ state, seat }: { state: BoardState; seat: number }) {
  const marks = state.effects.seats.get(seat);
  const number = marks ? seatNumber(marks) : null;
  if (!number) return null;
  return (
    <span key={`${state.effects.seats.size}:${number.text}`} className={`replay-life-change replay-life-change-${number.tone}`}>
      {number.text}
    </span>
  );
}

export function FidelityBadge({ stream }: { stream: ReplayStream }) {
  const recorded = stream.fidelity === 'recorded';
  const title = recorded
    ? 'Recorded with full detail while the game was played.'
    : ['Reconstructed from the event log. Approximate:', ...stream.limitations.map((line) => `• ${line}`)].join('\n');
  return (
    <span
      className={`replay-fidelity ${recorded ? 'replay-fidelity-recorded' : 'replay-fidelity-reconstructed'}`}
      title={title}
      tabIndex={0}
      aria-label={title}
    >
      {recorded ? 'Recorded' : 'Reconstructed'}
    </span>
  );
}

interface ReplayHudProps {
  stream: ReplayStream;
  state: BoardState;
  elapsed: number;
}

function ReplayHudImpl({ stream, state, elapsed }: ReplayHudProps) {
  const playerSeat = stream.player_seat;
  const seats = Object.keys(stream.seats)
    .map(Number)
    .sort((a, b) => (a === playerSeat ? -1 : b === playerSeat ? 1 : a - b));
  const active = state.activeSeat;
  const whose = active === null ? null : active === playerSeat ? 'Your turn' : "Opponent's turn";
  const phase = phaseLabel(state.step) && phaseLabel(state.phase)
    ? `${phaseLabel(state.phase)} – ${phaseLabel(state.step)}`
    : phaseLabel(state.phase);
  return (
    <div className="replay-hud" aria-label="Game state">
      <div className="replay-hud-turn" aria-live="polite">
        {state.turn > 0 ? (
          <>
            <strong>Turn {state.turn}</strong>
            {whose ? <span className={active === playerSeat ? 'replay-you' : 'replay-opp'}>{whose}</span> : null}
            {phase ? <span>{phase}</span> : null}
          </>
        ) : (
          <strong>Pre-game</strong>
        )}
        {state.ended ? (
          <span className={`replay-hud-over replay-hud-over-${describeGameEnd(stream, state).result}`}>
            {describeGameEnd(stream, state).headline}
          </span>
        ) : null}
        <span className="replay-hud-clock">{formatClock(elapsed)} elapsed</span>
      </div>
      <div className="replay-hud-seats">
        {seats.map((seatId, index) => {
          const seat = stream.seats[String(seatId)];
          const counts = state.seats[seatId];
          const mine = seatId === playerSeat;
          return (
            <Fragment key={seatId}>
              {index > 0 ? <span className="replay-hud-sep" aria-hidden="true" /> : null}
              <div
                className={`replay-hud-seat ${mine ? 'replay-hud-seat-you' : 'replay-hud-seat-opp'}${active === seatId ? ' replay-hud-seat-active' : ''}`}
              >
                <span className="replay-hud-name" title={seat?.deck_name ?? undefined}>
                  {mine ? 'You' : seat?.name || 'Opponent'}
                </span>
                <span className="replay-life" aria-label={`${mine ? 'Your' : 'Opponent'} life`}>
                  <LifeValue life={state.life[seatId] ?? seat?.starting_life ?? 20} />
                </span>
                <LifeChange state={state} seat={seatId} />
                <span className="replay-hud-counts">
                  Hand {counts?.handSize ?? 0} · Library {counts?.librarySize ?? 0}
                </span>
              </div>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

export const ReplayHud = memo(ReplayHudImpl);
