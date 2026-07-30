import { useEffect, useState } from 'react';
import {
  fetchGameDetail,
  type GameDetail,
  type GameDrawnCardRow,
  type GameOpeningHandRow,
  type OpponentVisibleCardRow,
  type GamePlayedCardRow,
} from '../api';
import { saveGameAnnotation } from '../api';
import { pageTitle } from '../branding';
import { formatPercent } from '../dashboardData';
import { formatDateTime, formatDuration, formatNumber, formatTurnDuration, outcomeLabel, outcomeTone } from '../format';
import { gameRouteHash } from '../routes';
import { DeckLink } from './DeckLink';
import { Badge } from './Badge';
import { CardLink } from './CardLink';
import { Section } from './Section';
import { LifeChart } from './LifeChart';
import { MetricCard } from './MetricCard';
import { OpponentLink } from './OpponentLink';
import { SortableTable, type Column } from './SortableTable';
import { TimelineList } from './TimelineList';
import { typeToneClass } from '../cardTypes';
import { TypeChip } from './TypeChip';

const DETAIL_REFRESH_MS = 20_000;

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; detail: GameDetail; refreshError?: string }
  | { status: 'error'; message: string };

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}


const openingColumns: Column<GameOpeningHandRow>[] = [
  { key: 'hand_position', header: '#', numeric: true },
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => <TypeChip type={row.type_category} />,
    sortValue: (row) => row.type_category,
  },
  { key: 'copy_number', header: 'Copy', numeric: true },
];

const drawnColumns: Column<GameDrawnCardRow>[] = [
  {
    key: 'turn_number',
    header: 'Turn',
    render: (row) => formatNumber(row.turn_number),
    sortValue: (row) => row.turn_number,
    numeric: true,
  },
  { key: 'draw_position', header: '#', numeric: true },
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => <TypeChip type={row.type_category} />,
    sortValue: (row) => row.type_category,
  },
];

const playedColumns: Column<GamePlayedCardRow>[] = [
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => <TypeChip type={row.type_category} />,
    sortValue: (row) => row.type_category,
  },
  { key: 'played_count', header: 'Played', numeric: true },
];

const opponentCardColumns: Column<OpponentVisibleCardRow>[] = [
  {
    key: 'display_name',
    header: 'Card',
    render: (row) => <CardLink cardName={row.display_name} />,
    sortValue: (row) => row.display_name,
  },
  {
    key: 'type_category',
    header: 'Type',
    render: (row) => <TypeChip type={row.type_category} />,
    sortValue: (row) => row.type_category,
  },
  { key: 'played_count', header: 'Played', numeric: true },
  { key: 'drawn_count', header: 'Revealed Draws', numeric: true },
  { key: 'discarded_count', header: 'Discarded', numeric: true },
  { key: 'milled_count', header: 'Milled', numeric: true },
  { key: 'exiled_count', header: 'Exiled', numeric: true },
];

function isLandCard(card: { display_name: string; type_category: string }): boolean {
  return card.type_category.toLocaleLowerCase() === 'land' || card.display_name.trimEnd().endsWith('(Land)');
}

function longestLandRun(flags: boolean[]): number {
  let longest = 0;
  let current = 0;
  flags.forEach((isLand) => {
    current = isLand ? current + 1 : 0;
    longest = Math.max(longest, current);
  });
  return longest;
}

function maxLandsInEight(flags: boolean[]): number | null {
  if (flags.length < 8) {
    return null;
  }
  let maximum = 0;
  for (let index = 0; index <= flags.length - 8; index += 1) {
    maximum = Math.max(maximum, flags.slice(index, index + 8).filter(Boolean).length);
  }
  return maximum;
}

function calculateLowLandDrought(
  flags: Array<boolean | null>,
  openingLands: number,
): { draws: number; lands: number | null } {
  let landsSeen = openingLands;
  let current = 0;
  let longest = 0;
  let landsAtLongest: number | null = null;
  flags.forEach((isLand) => {
    if (isLand === true) {
      landsSeen += 1;
      current = 0;
    } else if (isLand === false && landsSeen <= 2) {
      current += 1;
      if (current > longest) {
        longest = current;
        landsAtLongest = landsSeen;
      }
    } else {
      current = 0;
    }
  });
  return { draws: longest, lands: landsAtLongest };
}

function formatWholePercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value)}%`;
}

export function GameDetailPage({
  gameId,
  backHref = '#overview',
  focusId,
}: {
  gameId: string;
  backHref?: string;
  focusId?: 'game-timeline' | null;
}) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [noteDraft, setNoteDraft] = useState('');
  const [tagsDraft, setTagsDraft] = useState('');
  const [noteStatus, setNoteStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [noteError, setNoteError] = useState<string | null>(null);
  const [, setAnnotationLoaded] = useState(false);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [gameId]);

  useEffect(() => {
    if (loadState.status === 'loaded') {
      document.title = pageTitle(`Game ${formatDateTime(loadState.detail.game.started_at)}`);
    }
  }, [loadState]);

  useEffect(() => {
    if (loadState.status === 'loaded' && focusId === 'game-timeline') {
      document.getElementById(focusId)?.scrollIntoView?.({ block: 'start' });
    }
  }, [focusId, loadState.status]);

  useEffect(() => {
    let ignore = false;
    let activeController: AbortController | null = null;

    async function loadDetail() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const detail = await fetchGameDetail(gameId, controller.signal);
        if (!ignore) {
          setLoadState({ status: 'loaded', detail });
          setAnnotationLoaded((alreadyLoaded) => {
            if (!alreadyLoaded) {
              setNoteDraft(detail.annotation?.note ?? '');
              setTagsDraft((detail.annotation?.tags ?? []).join(', '));
            }
            return true;
          });
        }
      } catch (error: unknown) {
        if (!ignore && !isAbortError(error)) {
          const message = error instanceof Error ? error.message : 'Dashboard API failed';
          setLoadState((current) =>
            current.status === 'loaded'
              ? { ...current, refreshError: message }
              : { status: 'error', message },
          );
        }
      }
    }

    void loadDetail();
    const refreshId = window.setInterval(() => {
      if (!document.hidden) {
        void loadDetail();
      }
    }, DETAIL_REFRESH_MS);

    return () => {
      ignore = true;
      activeController?.abort();
      window.clearInterval(refreshId);
    };
  }, [gameId]);

  if (loadState.status === 'loading') {
    return (
      <p className="state-panel" role="status" aria-busy="true">
        Loading game details...
      </p>
    );
  }
  if (loadState.status === 'error') {
    return (
      <div className="state-panel error-state" role="alert">
        <p>{loadState.message}</p>
        <a className="back-link" href={backHref}>
          ← Back to dashboard
        </a>
      </div>
    );
  }

  const { detail, refreshError } = loadState;
  const playDraw = detail.player.went_first === 1 ? 'On the play' : detail.player.went_first === 0 ? 'On the draw' : 'Unknown';
  const landByPosition = new Map(detail.drawn.map((card) => [card.draw_position, isLandCard(card)]));
  const drawLandFlags = Array.from(
    { length: detail.draw_quality.total_draws },
    (_, index) => landByPosition.get(index + 1) ?? false,
  );
  const knownDrawLandFlags = Array.from(
    { length: detail.draw_quality.total_draws },
    (_, index) => landByPosition.get(index + 1) ?? null,
  );
  const longestLandStreak = detail.draw_quality.longest_land_streak ?? longestLandRun(drawLandFlags);
  const maxLandsInEightDraws = detail.draw_quality.max_lands_in_eight ?? maxLandsInEight(drawLandFlags);
  const openingLands = detail.draw_quality.opening_lands ?? detail.opening_hand.filter(isLandCard).length;
  const lowLandDroughtFallback = calculateLowLandDrought(knownDrawLandFlags, openingLands);
  const longestLowLandDrought =
    detail.draw_quality.longest_low_land_drought ?? lowLandDroughtFallback.draws;
  const lowLandDroughtLands =
    detail.draw_quality.low_land_drought_lands ?? lowLandDroughtFallback.lands;
  const totalCardsSeen =
    detail.draw_quality.total_cards_seen ?? detail.opening_hand.length + detail.draw_quality.total_draws;
  const landsSeen = detail.draw_quality.lands_seen ?? openingLands + detail.draw_quality.land_draws;
  const landSeenPct =
    detail.draw_quality.land_seen_pct ?? (totalCardsSeen ? (100 * landsSeen) / totalCardsSeen : null);
  const expectedLandRate = detail.draw_quality.expected_land_rate ?? 40;
  const expectedLandsSeen =
    detail.draw_quality.expected_lands_seen ?? (totalCardsSeen * expectedLandRate) / 100;
  const isFlood =
    detail.draw_quality.is_flood ||
    longestLandStreak >= 4 ||
    (maxLandsInEightDraws !== null && maxLandsInEightDraws >= 6);
  const fallbackFloodReasons = [
    ...(detail.draw_quality.land_draw_pct !== null &&
    detail.draw_quality.land_draw_pct > 50 &&
    detail.draw_quality.total_draws >= 6
      ? [
          `${detail.draw_quality.land_draws} of ${detail.draw_quality.total_draws} post-opening draws were lands`,
        ]
      : []),
    ...(longestLandStreak >= 4 ? [`${longestLandStreak} consecutive land draws`] : []),
    ...(maxLandsInEightDraws !== null && maxLandsInEightDraws >= 6
      ? [`${maxLandsInEightDraws} lands in an 8-draw window`]
      : []),
  ];
  const floodReasons =
    detail.draw_quality.flood_reasons && detail.draw_quality.flood_reasons.length > 0
      ? detail.draw_quality.flood_reasons
      : fallbackFloodReasons;
  const isScrew = Boolean(detail.draw_quality.is_screw) || longestLowLandDrought >= 3;
  const fallbackScrewReasons =
    longestLowLandDrought >= 3 && lowLandDroughtLands !== null
      ? [
          `${longestLowLandDrought} consecutive nonland draws while stuck on ${lowLandDroughtLands} ${
            lowLandDroughtLands === 1 ? 'land' : 'lands'
          }`,
        ]
      : [];
  const screwReasons =
    detail.draw_quality.screw_reasons && detail.draw_quality.screw_reasons.length > 0
      ? detail.draw_quality.screw_reasons
      : fallbackScrewReasons;
  const drawStatus =
    detail.draw_quality.total_draws === 0
      ? 'No Draws'
      : isFlood
        ? 'Flood'
        : isScrew
          ? 'Mana Screw'
          : 'Normal';
  const playerStats = detail.participant_stats.find((row) => row.role === 'player');
  const opponentStats = detail.participant_stats.find((row) => row.role === 'opponent');
  const combatGroups = [
    {
      title: 'Attack',
      rows: [
        ['Attack steps', 'attack_steps'],
        ['Attacking creatures', 'attacking_creatures'],
        ['Attackers lost', 'attackers_lost'],
      ],
    },
    {
      title: 'Block',
      rows: [
        ['Blocking creatures', 'blocking_creatures'],
        ['Blockers lost', 'blockers_lost'],
      ],
    },
    {
      title: 'Life',
      rows: [
        ['Damage dealt', 'damage_dealt'],
        ['Damage taken', 'damage_taken'],
        ['Life lost', 'life_lost'],
        ['Self damage', 'self_damage'],
        ['Life gained', 'life_gained'],
      ],
    },
    {
      title: 'Cards',
      rows: [
        ['Played', 'cards_played'],
        ['Drawn', 'cards_drawn'],
        ['Discarded', 'cards_discarded'],
        ['Milled', 'cards_milled'],
        ['Exiled', 'cards_exiled'],
      ],
    },
  ] as const;
  const mulliganHands = detail.mulligan_hands ?? [];
  async function saveAnnotation() {
    setNoteStatus('saving');
    try {
      const tags = tagsDraft
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean);
      const saved = await saveGameAnnotation(gameId, noteDraft.trim(), tags);
      setNoteDraft(saved.note);
      setTagsDraft(saved.tags.join(', '));
      setNoteStatus('saved');
      setNoteError(null);
    } catch (error: unknown) {
      setNoteError(error instanceof Error ? error.message : null);
      setNoteStatus('error');
    }
  }

  const drawsByTurnMap = new Map<number, { lands: number; nonlands: number }>();
  for (const row of detail.drawn) {
    if (row.turn_number === null || row.turn_number === undefined) {
      continue;
    }
    const bucket = drawsByTurnMap.get(row.turn_number) ?? { lands: 0, nonlands: 0 };
    if ((row.type_category ?? '').toLowerCase() === 'land' || row.display_name.endsWith('(Land)')) {
      bucket.lands += 1;
    } else {
      bucket.nonlands += 1;
    }
    drawsByTurnMap.set(row.turn_number, bucket);
  }
  const drawsByTurn = Array.from(drawsByTurnMap.entries())
    .sort(([a], [b]) => a - b)
    .map(([turn, counts]) => ({ turn, ...counts }));
  const timelineReturnHash = gameRouteHash(gameId, backHref, 'game-timeline');
  const metricCards = [
    { label: 'Play / Draw', value: playDraw },
    { label: 'Mulligans', value: formatNumber(detail.player.mulligans) },
    { label: 'Turns', value: formatNumber(detail.game.total_turns) },
    { label: 'Duration', value: formatDuration(detail.game.duration_seconds) },
    { label: 'Final Life', value: `${formatNumber(detail.player.ending_life)} / ${formatNumber(detail.opponent.ending_life)}` },
  ];
  return (
    <>
      {refreshError ? (
        <p className="refresh-status refresh-status-error" role="alert">
          Refresh failed: {refreshError} — showing the last loaded data.
        </p>
      ) : null}
      <div className="deck-detail-header" id="game-summary">
        <a className="back-link" href={backHref}>
          ← Back to dashboard
        </a>
        <div className="deck-detail-title">
          <div className={`game-outcome-mark game-outcome-${outcomeTone(detail.game.outcome)}`}>
            {outcomeLabel(detail.game.outcome)}
          </div>
          <div>
            <div className="game-title-row">
              <h2>Game {formatDateTime(detail.game.started_at)}</h2>
              {isFlood ? <Badge tone="draw">Flood</Badge> : null}
              {!isFlood && isScrew ? <Badge tone="screw">Mana Screw</Badge> : null}
            </div>
            <p>
              {detail.player.deck_name ? <DeckLink deckName={detail.player.deck_name} /> : 'Unknown deck'} ·{' '}
              {detail.game.format_label}
              {detail.game.best_of ? ` · Best-of-${detail.game.best_of}` : ''}
            </p>
            {detail.opponent.display_name ? (
              <p>
                vs. <OpponentLink opponentName={detail.opponent.display_name} />
              </p>
            ) : null}
          </div>
        </div>
      </div>

      <section className="metric-grid metric-grid-deck" aria-label="Game metrics">
        {metricCards.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={metric.value} />
        ))}
      </section>

      <Section
        id="game-turn-timing"
        title="Turn Timing"
        description="Average pace stays here. Individual turn durations are shown with each turn in the Timeline; estimated values come from historical turn headers."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Turn timing summary">
          <MetricCard label="Your Turn Time" value={formatTurnDuration(detail.turn_timing.player.total_seconds)} />
          <MetricCard label="Your Avg Turn" value={formatTurnDuration(detail.turn_timing.player.avg_seconds)} />
          <MetricCard label="Opponent Turn Time" value={formatTurnDuration(detail.turn_timing.opponent.total_seconds)} />
          <MetricCard label="Opponent Avg Turn" value={formatTurnDuration(detail.turn_timing.opponent.avg_seconds)} />
        </section>
      </Section>

      <Section
        id="game-draw-quality"
        title="Draw Quality"
        description="Flood tracks excess lands and concentrated land streaks. Mana screw tracks statistically low land access and three or more known nonland draws while stuck on one or two lands."
      >
        <section className="metric-grid metric-grid-deck" aria-label="Game draw quality">
          <MetricCard label="Total Cards Seen" value={formatNumber(totalCardsSeen)} />
          <MetricCard label="Lands Seen" value={`${landsSeen} (${formatWholePercent(landSeenPct)})`} />
          <MetricCard label="Total Cards Drawn" value={formatNumber(detail.draw_quality.total_draws)} />
          <MetricCard
            label="Lands Drawn"
            value={`${detail.draw_quality.land_draws} (${formatWholePercent(detail.draw_quality.land_draw_pct)})`}
          />
          <MetricCard label={`Expected Lands (${formatPercent(expectedLandRate)})`} value={expectedLandsSeen.toFixed(1)} />
          <MetricCard label="Longest Land Streak" value={formatNumber(longestLandStreak)} />
          <MetricCard
            label="Worst 8-Draw Window"
            value={maxLandsInEightDraws === null ? '—' : `${maxLandsInEightDraws} lands`}
          />
          <MetricCard
            label="Low-Land Drought"
            value={longestLowLandDrought ? `${longestLowLandDrought} draws` : '—'}
          />
          <MetricCard
            label="Draw Status"
            value={drawStatus}
            tone={isFlood ? 'info' : isScrew ? 'warning' : 'default'}
          />
        </section>
        {isFlood && floodReasons.length > 0 ? (
          <p className="draw-quality-reason">
            <Badge tone="draw">Flood evidence</Badge>
            <span>{floodReasons.join(' · ')}</span>
          </p>
        ) : null}
        {!isFlood && isScrew && screwReasons.length > 0 ? (
          <p className="draw-quality-reason">
            <Badge tone="screw">Mana Screw Evidence</Badge>
            <span>{screwReasons.join(' · ')}</span>
          </p>
        ) : null}
      </Section>

      <Section
        id="game-combat"
        title="Combat & Resources"
        description="Per-seat combat, damage, and resource totals recorded for this game."
      >
        {detail.participant_stats.length > 0 ? (
          <div className="combat-groups">
            {combatGroups.map((group) => (
              <div key={group.title} className="combat-group">
                <table className="combat-group-table">
                  <caption className="visually-hidden">{group.title} stats by seat</caption>
                  <thead>
                    <tr>
                      <th scope="col">{group.title}</th>
                      <th scope="col" className="numeric">You</th>
                      <th scope="col" className="numeric">Opp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.rows.map(([label, key]) => (
                      <tr key={key}>
                        <td>{label}</td>
                        <td className="numeric">{formatNumber(playerStats ? playerStats[key] : null)}</td>
                        <td className="numeric">{formatNumber(opponentStats ? opponentStats[key] : null)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        ) : (
          <p className="empty-state">No combat telemetry recorded for this game.</p>
        )}
      </Section>

      <Section id="game-life" title="Life Totals" description="Life-total changes captured from the game timeline.">
        <div className="trend-wrap">
          <LifeChart points={detail.life_curve} />
        </div>
      </Section>

      <Section
        id="game-opening-hand"
        title="Opening Hand"
        description={
          mulliganHands.length > 0
            ? 'Every hand seen before keeping: mulliganed hands go back whole, and the final hand bottoms one card per mulligan.'
            : undefined
        }
      >
        {mulliganHands.length > 0 ? (
          <div className="mulligan-history">
            {mulliganHands.map((hand) => {
              const bottomedCount = hand.cards.filter((card) => card.bottomed).length;
              const kept = bottomedCount > 0;
              return (
                <div key={hand.hand_number} className="mulligan-hand">
                  <div className="mulligan-hand-head">
                    <span className="mulligan-hand-title">
                      {hand.hand_number === 1
                        ? 'Hand 1 — first seven'
                        : `Hand ${hand.hand_number} — after mulligan ${hand.hand_number - 1}`}
                    </span>
                    <span className={kept ? 'mulligan-hand-verdict mulligan-hand-kept' : 'mulligan-hand-verdict'}>
                      {kept
                        ? `Kept · bottomed ${bottomedCount} ${bottomedCount === 1 ? 'card' : 'cards'}`
                        : 'Mulliganed away'}
                    </span>
                  </div>
                  <ul className="mulligan-cards">
                    {hand.cards.map((card) => (
                      <li
                        key={`${hand.hand_number}-${card.hand_position}`}
                        className={`mulligan-card ${typeToneClass(card.type_category)}${
                          card.bottomed ? ' mulligan-card-bottomed' : ''
                        }`}
                      >
                        <CardLink cardName={card.display_name} />
                        {card.bottomed ? <span className="mulligan-card-note">bottomed</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
            <h4 className="mulligan-kept-title">Kept hand</h4>
          </div>
        ) : (detail.player.mulligans ?? 0) > 0 ? (
          <p className="mulligan-history-missing">
            This game was recorded before mulligan-history support, so only the kept hand below was saved.
          </p>
        ) : null}
        <SortableTable
          caption={mulliganHands.length > 0 ? 'Kept hand' : 'Opening hand'}
          columns={openingColumns}
          getRowKey={(row) => `${row.hand_position}-${row.display_name}`}
          rows={detail.opening_hand}
        />
      </Section>

      <Section id="game-draws" title="Drawn Cards">
        {drawsByTurn.length > 0 ? (
          <div className="draws-by-turn" aria-label="Draws by turn">
            {drawsByTurn.map(({ turn, lands, nonlands }) => (
              <div key={turn} className="draws-by-turn-cell">
                <span className="draws-by-turn-turn">T{turn}</span>
                <span className="draws-by-turn-counts">
                  {lands > 0 ? <span className="draws-by-turn-lands">{lands}L</span> : null}
                  {nonlands > 0 ? <span className="draws-by-turn-spells">{nonlands}S</span> : null}
                </span>
              </div>
            ))}
          </div>
        ) : null}
        <SortableTable
          caption="Drawn cards"
          columns={drawnColumns}
          getRowKey={(row) => `${row.draw_position}-${row.display_name}`}
          rows={detail.drawn}
        />
      </Section>

      <Section id="game-played" title="Cards Played">
        <SortableTable
          caption="Cards played"
          columns={playedColumns}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          rows={detail.cards_played}
        />
      </Section>

      <Section
        id="game-opponent-cards"
        title="Opponent Revealed Cards"
        description="Every identified opponent card exposed through play, a visible draw, discard, mill, or exile."
      >
        <SortableTable
          caption="Opponent revealed cards"
          columns={opponentCardColumns}
          getRowKey={(row) => `${row.display_name}-${row.type_category}`}
          initialSort={{ key: 'played_count', direction: 'desc' }}
          rows={detail.opponent_cards ?? []}
        />
      </Section>

      <Section
        id="game-notes"
        title="Notes & Tags"
        description="Your own notes for this game. Tags are comma-separated (e.g. misplay, flood, great game)."
      >
        <div className="annotation-editor">
          <label className="annotation-label">
            <span>Note</span>
            <textarea
              className="annotation-note"
              maxLength={4000}
              rows={3}
              value={noteDraft}
              onChange={(event) => {
                setNoteDraft(event.target.value);
                setNoteStatus('idle');
              }}
            />
          </label>
          <label className="annotation-label">
            <span>Tags</span>
            <input
              className="annotation-tags"
              placeholder="misplay, flood, great game"
              type="text"
              value={tagsDraft}
              onChange={(event) => {
                setTagsDraft(event.target.value);
                setNoteStatus('idle');
              }}
            />
          </label>
          <div className="annotation-actions">
            <button
              className="deck-export-button"
              disabled={noteStatus === 'saving'}
              type="button"
              onClick={() => void saveAnnotation()}
            >
              {noteStatus === 'saving' ? 'Saving…' : 'Save Notes'}
            </button>
            {noteStatus === 'saved' ? (
              <span className="annotation-status" role="status">
                Saved
              </span>
            ) : null}
            {noteStatus === 'error' ? (
              <span className="annotation-status annotation-status-error" role="alert">
                Save failed — {noteError || 'is the dashboard server running?'}
              </span>
            ) : null}
          </div>
        </div>
      </Section>

      <Section
        id="game-timeline"
        title="Timeline"
        description="Turn-by-turn play history captured from the tracker log."
      >
        <TimelineList
          cardReturnHash={timelineReturnHash}
          rows={detail.timeline}
          timings={detail.turns}
        />
      </Section>
    </>
  );
}
