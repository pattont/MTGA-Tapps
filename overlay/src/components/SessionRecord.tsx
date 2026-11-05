import type { OverlaySession, Score, SessionRecord as Style } from '../types';

const decided = (score: Score) => score.wins + score.losses;

/** A win rate, green at 50% or better and red below (Deck Manager's rule); a dash without games. */
function Rate({ score }: { score: Score }) {
  if (!decided(score)) return <span class="ss-none">–</span>;
  const rate = Math.round((100 * score.wins) / decided(score));
  return <span class={rate >= 50 ? 'ss-up' : 'ss-down'}>{rate}%</span>;
}

function Record({ session }: { session: OverlaySession }) {
  return (
    <span class="ss-rec">
      <span class="ss-w">{session.wins}</span>
      <span class="ss-dash">–</span>
      <span class="ss-l">{session.losses}</span>
      {session.draws ? (
        <>
          <span class="ss-dash">–</span>
          <span>{session.draws}</span>
        </>
      ) : null}
    </span>
  );
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const said = (score: Score) => `${plural(score.wins, 'win', 'wins')}, ${plural(score.losses, 'loss', 'losses')}`;

/** Whether the footer has anything to show: the setting is on and the session has a result. */
export function showsSessionRecord(style: Style, session: OverlaySession | null | undefined): session is OverlaySession {
  return style !== 'off' && !!session && session.wins + session.losses + session.draws > 0;
}

/**
 * This session's record at the foot of the panel, in the Stream Kit record
 * widget's colours but sized to the overlay's rows. `scoreboard` is one line
 * with the Play / Draw win rates on the right; `split` puts a win/loss bar
 * under the record and the Play and Draw records under that.
 */
export function SessionRecord({ session, style }: { session: OverlaySession; style: Exclude<Style, 'off'> }) {
  const label = [
    `Session: ${said(session)}${session.draws ? `, ${plural(session.draws, 'draw', 'draws')}` : ''}`,
    `on the play: ${decided(session.play) ? said(session.play) : 'no games'}`,
    `on the draw: ${decided(session.draw) ? said(session.draw) : 'no games'}`,
  ].join('; ');
  const rate = session.win_rate == null ? null : <span class="ss-rate">{Math.round(session.win_rate)}%</span>;
  const turnOrder = decided(session.play) + decided(session.draw) > 0;

  if (style === 'split') {
    const total = decided(session);
    return (
      <div class="ss ss-split" role="group" aria-label={label}>
        <div class="ss-main">
          <span class="ss-lab">Session</span>
          <Record session={session} />
          {rate}
        </div>
        {total > 0 ? (
          <div class="ss-bar" aria-hidden="true">
            <i style={{ width: `${(100 * session.wins) / total}%` }} />
          </div>
        ) : null}
        {turnOrder ? (
          <div class="ss-sides">
            <span>
              <span class="ss-tag ss-play">Play</span>
              <span class="ss-score">
                {session.play.wins}–{session.play.losses}
              </span>
              <Rate score={session.play} />
            </span>
            <span>
              <span class="ss-tag ss-draw">Draw</span>
              <span class="ss-score">
                {session.draw.wins}–{session.draw.losses}
              </span>
              <Rate score={session.draw} />
            </span>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div class="ss ss-line" role="group" aria-label={label}>
      <div class="ss-main">
        <span class="ss-lab">Session</span>
        <Record session={session} />
        {rate}
      </div>
      {turnOrder ? (
        <div class="ss-pd">
          <span class="ss-lab">
            <span class="ss-play">Play</span> / <span class="ss-draw">Draw</span>
          </span>
          <span class="ss-pd-v">
            <Rate score={session.play} />
            <span class="ss-none">/</span>
            <Rate score={session.draw} />
          </span>
        </div>
      ) : null}
    </div>
  );
}
