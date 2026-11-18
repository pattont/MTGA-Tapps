import type { OverlayRank, OverlayToday, Score, SessionRecord as Style } from '../types';

const decided = (score: Score) => score.wins + score.losses;

/** A win rate, green at 50% or better and red below (Deck Manager's rule); a dash without games. */
function Rate({ score }: { score: Score }) {
  if (!decided(score)) return <span class="ss-none">–</span>;
  const rate = Math.round((100 * score.wins) / decided(score));
  return <span class={rate >= 50 ? 'ss-up' : 'ss-down'}>{rate}%</span>;
}

function Record({ today }: { today: OverlayToday }) {
  return (
    <span class="ss-rec">
      <span class="ss-w">{today.wins}</span>
      <span class="ss-dash">–</span>
      <span class="ss-l">{today.losses}</span>
      {today.draws ? (
        <>
          <span class="ss-dash">–</span>
          <span>{today.draws}</span>
        </>
      ) : null}
    </span>
  );
}

/** "Platinum 2 · 3/6", or Mythic with its rank or percentile (the dashboard's `rankText`). */
export function rankText(rank: OverlayRank): string {
  if (rank.rank_class === 'Mythic') {
    if (rank.mythic_rank) return `Mythic #${rank.mythic_rank}`;
    if (rank.mythic_percentile != null) return `Mythic ${rank.mythic_percentile}%`;
    return 'Mythic';
  }
  return `${rank.rank_class} ${rank.rank_level} · ${rank.rank_step}/${rank.rank_steps}`;
}

/** Play or Draw beside the record: the win rate, with the record under it. */
function Column({ side, label, score }: { side: 'play' | 'draw'; label: string; score: Score }) {
  return (
    <div class={`ss-col ss-col-${side}`}>
      <span class="ss-tag">{label}</span>
      <span class="ss-col-big">{Math.round((100 * score.wins) / decided(score))}%</span>
      <span class="ss-col-rec">
        {score.wins}–{score.losses}
      </span>
    </div>
  );
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const said = (score: Score) => `${plural(score.wins, 'win', 'wins')}, ${plural(score.losses, 'loss', 'losses')}`;

/** Whether the footer has anything to show: the setting is on and today has a result. */
export function showsTodayRecord(style: Style, today: OverlayToday | null | undefined): today is OverlayToday {
  return style !== 'off' && !!today && today.wins + today.losses + today.draws > 0;
}

/**
 * Today's record (every game since local midnight) at the foot of the panel.
 * `scoreboard` is one line with the Play / Draw win rates on the right.
 * `split` is the Stream Kit record widget at the panel's width: the record
 * over a rank chip (ranked games only) and this deck's record today, with
 * Play and Draw columns on the right.
 */
export function TodayRecord({ today: record, style }: { today: OverlayToday; style: Exclude<Style, 'off'> }) {
  const label = [
    `Today: ${said(record)}${record.draws ? `, ${plural(record.draws, 'draw', 'draws')}` : ''}`,
    `on the play: ${decided(record.play) ? said(record.play) : 'no games'}`,
    `on the draw: ${decided(record.draw) ? said(record.draw) : 'no games'}`,
  ].join('; ');
  const rate = record.win_rate == null ? null : <span class="ss-rate">{Math.round(record.win_rate)}%</span>;
  const turnOrder = decided(record.play) + decided(record.draw) > 0;

  if (style === 'split') {
    const rank = record.rank ?? null;
    const deck = record.deck && decided(record.deck) > 0 ? record.deck : null;
    const full = [label, rank ? `rank: ${rankText(rank)}` : null, deck ? `with this deck: ${said(deck)}` : null].filter(Boolean).join('; ');
    return (
      <div class="ss ss-split" role="group" aria-label={full}>
        <div class="ss-left">
          <span class="ss-lab">Today</span>
          <div class="ss-main">
            <Record today={record} />
            {rate}
          </div>
          {rank || deck ? (
            <div class="ss-chips">
              {rank ? <span class="ss-chip ss-chip-rank">{rankText(rank)}</span> : null}
              {deck ? (
                <span class="ss-chip">
                  Deck {deck.wins}–{deck.losses}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        {turnOrder ? (
          <div class="ss-cols">
            {/* A side with no games yet is left out. */}
            {decided(record.play) > 0 ? <Column side="play" label="Play" score={record.play} /> : null}
            {decided(record.draw) > 0 ? <Column side="draw" label="Draw" score={record.draw} /> : null}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div class="ss ss-line" role="group" aria-label={label}>
      <div class="ss-main">
        <span class="ss-lab">Today</span>
        <Record today={record} />
        {rate}
      </div>
      {turnOrder ? (
        <div class="ss-pd">
          <span class="ss-lab">
            <span class="ss-play">Play</span> / <span class="ss-draw">Draw</span>
          </span>
          <span class="ss-pd-v">
            <Rate score={record.play} />
            <span class="ss-none">/</span>
            <Rate score={record.draw} />
          </span>
        </div>
      ) : null}
    </div>
  );
}
