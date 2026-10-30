/**
 * The ending screen: once the `game_end` event has been applied, a card over
 * the table announces Victory / Defeat / Draw with the reason, final life
 * totals and length, plus "Watch again" and the way back. Scrubbing backwards
 * removes it; "Show table" hides it until the position changes again.
 */
import { useState } from 'react';
import { describeGameEnd, gameEndScore } from '../gameEnd';
import type { PlaybackClock } from '../player';
import type { BoardState } from '../reducer';
import type { ReplayStream } from '../types';

interface GameEndOverlayProps {
  stream: ReplayStream;
  state: BoardState;
  clock: PlaybackClock;
  /** Where "Back" leads (the Game Detail page or the replay list). */
  backHash: string;
}

export function GameEndOverlay({ stream, state, clock, backHash }: GameEndOverlayProps) {
  const [hiddenAt, setHiddenAt] = useState<number | null>(null);
  // Hiding is per position: scrubbing away (and back) brings the screen back.
  if (!state.ended && hiddenAt !== null) setHiddenAt(null);
  if (!state.ended || hiddenAt === state.seq) return null;

  const end = describeGameEnd(stream, state);
  const { yourLife, opponentName, theirLife, facts } = gameEndScore(stream, state);

  return (
    <div className={`replay-end replay-end-${end.result}`} role="dialog" aria-modal="false" aria-label="Game result">
      <div className="replay-end-card">
        <div className="replay-end-eyebrow">Game over</div>
        <h2 className="replay-end-headline">{end.headline}</h2>
        {end.reason ? <p className="replay-end-reason">{end.reason}</p> : null}
        <div className="replay-end-score" aria-label="Final life totals">
          <div className={`replay-end-seat${end.result === 'win' ? ' replay-end-seat-winner' : ''}`}>
            <span className="replay-end-seat-name">You</span>
            <span className="replay-end-life">{yourLife}</span>
          </div>
          <span className="replay-end-dash" aria-hidden="true">
            –
          </span>
          <div className={`replay-end-seat${end.result === 'loss' ? ' replay-end-seat-winner' : ''}`}>
            <span className="replay-end-seat-name">{opponentName}</span>
            <span className="replay-end-life">{theirLife ?? '—'}</span>
          </div>
        </div>
        {facts.length ? <p className="replay-end-facts">{facts.join(' · ')}</p> : null}
        <div className="replay-end-actions">
          <button
            type="button"
            className="replay-btn replay-btn-primary"
            onClick={() => {
              clock.seek(clock.startSeq);
              clock.play();
            }}
          >
            Watch again
          </button>
          <button type="button" className="replay-btn" onClick={() => setHiddenAt(state.seq)}>
            Show table
          </button>
          <a className="replay-btn" href={backHash}>
            Back
          </a>
        </div>
      </div>
    </div>
  );
}
