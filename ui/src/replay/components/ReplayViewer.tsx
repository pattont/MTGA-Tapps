/**
 * The loaded replay page: header strip, HUD + 3D table (or a notice below
 * 900 px), action log, transport bar, shortcuts and shareable `?at=` links.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatDateTime, outcomeLabel, outcomeTone } from '../../format';
import { REPLAY_ROUTE_HASH, cardRouteHash, parseReplayRoute, replayRouteHash } from '../../routes';
import { Badge } from '../../components/Badge';
import { CollapseToggle } from '../../components/CollapseToggle';
import { DEFAULT_TABLE_WIDTH, HAND_SCALE_MIN, OPPONENT_HAND_SCALE } from '../layout';
import type { TableFit } from '../scene/cameraFit';
import { savePrefs } from '../prefs';
import { usePrefs, useReplayPlayback } from '../hooks/useReplayPlayback';
import { useReplayKeyboard } from '../hooks/useReplayKeyboard';
import { useTexturePriorities, useTextureStore } from '../hooks/useTextures';
import { useNarrowViewport } from '../hooks/useViewport';
import { HoverStore } from '../scene/hoverStore';
import { KEY_ZOOM_STEP, ViewZoom } from '../scene/viewZoom';
import type { CardKey, ReplayStream } from '../types';
import { CardPreview } from './CardPreview';
import { ReplayControls } from './ReplayControls';
import { GameEndOverlay } from './GameEndOverlay';
import { FidelityBadge, ReplayHud } from './ReplayHud';
import { ReplayLog } from './ReplayLog';
import { ReplayScene } from './ReplayScene';
import { TablePopover } from './TablePopover';
import { useVideoExport } from '../hooks/useVideoExport';
import { VideoExportPanel } from './VideoExport';

export const HASH_DEBOUNCE_MS = 300;

interface ReplayViewerProps {
  stream: ReplayStream;
  gameId: string;
  at: number | null;
  returnHash: string | null;
}

export function ReplayViewer({ stream, gameId, at, returnHash }: ReplayViewerProps) {
  const prefs = usePrefs();
  // The felt's width and the hand scale follow the measured stage (ReplayScene reports them).
  const [tableFit, setTableFit] = useState<TableFit>(() => ({
    width: DEFAULT_TABLE_WIDTH,
    handScale: HAND_SCALE_MIN,
    opponentHandScale: OPPONENT_HAND_SCALE,
  }));
  const onTableFit = useCallback((fit: TableFit) => {
    setTableFit((prev) =>
      prev.width === fit.width && prev.handScale === fit.handScale && prev.opponentHandScale === fit.opponentHandScale ? prev : fit,
    );
  }, []);
  const { timeline, clock, snapshot, state, layout, jumped } = useReplayPlayback(stream, prefs, at, tableFit);
  const store = useTextureStore(stream);
  const video = useVideoExport(stream, clock, snapshot.index);
  // The table area's CSS size feeds the export dialog's size and file estimate.
  const [tableNode, setTableNode] = useState<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = useState<{ width: number; height: number } | null>(null);
  useEffect(() => {
    if (!tableNode || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const { width, height } = tableNode.getBoundingClientRect();
      if (width > 0 && height > 0) setStageSize({ width: Math.round(width), height: Math.round(height) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(tableNode);
    return () => observer.disconnect();
  }, [tableNode]);
  useTexturePriorities(store, timeline, layout, snapshot.turn ?? 0);
  const [hover] = useState(() => new HoverStore());
  const [zoom] = useState(() => new ViewZoom());
  const narrow = useNarrowViewport();
  const [tableOpen, setTableOpen] = useState(false);
  const goToTurnRef = useRef<HTMLInputElement>(null);
  const closeTable = useCallback(() => setTableOpen(false), []);

  useReplayKeyboard(clock, {
    focusGoToTurn: () => goToTurnRef.current?.focus(),
    toggleTable: () => setTableOpen((open) => !open),
    zoom: (direction) => {
      if (direction === 'reset') zoom.reset();
      else zoom.zoomBy(direction === 'in' ? KEY_ZOOM_STEP : 1 / KEY_ZOOM_STEP);
    },
  });

  // Shareable position: rewrite `?at=` while paused (never during playback, never a new entry).
  const written = useRef(snapshot.seq);
  useEffect(() => {
    if (snapshot.playing || snapshot.seq === written.current) return;
    const timer = setTimeout(() => {
      written.current = snapshot.seq;
      // Never pull the user back: once the hash has left this replay (a nav
      // click whose hashchange has not reached React yet), leave it alone.
      if (parseReplayRoute(window.location.hash)?.gameId !== gameId) return;
      try {
        window.history.replaceState(window.history.state, '', replayRouteHash(gameId, { at: snapshot.seq, returnHash }));
      } catch {
        // History unavailable: the link just stays at its old position.
      }
    }, HASH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [gameId, returnHash, snapshot.playing, snapshot.seq]);

  const hereHash = useCallback(() => replayRouteHash(gameId, { at: clock.seq, returnHash }), [clock, gameId, returnHash]);
  const onSeek = useCallback((seq: number) => clock.seek(seq), [clock]);
  const onCardClick = useCallback(
    (card: CardKey) => {
      const name = stream.cards[card]?.name;
      if (name) window.location.hash = cardRouteHash(name, hereHash());
    },
    [hereHash, stream.cards],
  );

  const playerSeat = stream.seats[String(stream.player_seat)];
  const opponentSeat = Object.entries(stream.seats).find(([seat]) => Number(seat) !== stream.player_seat)?.[1];
  const game = stream.game;
  // Formatted once: Intl date formatting is far too slow to repeat on every event tick.
  const startedAt = useMemo(() => (game.started_at ? ` · ${formatDateTime(game.started_at)}` : ''), [game.started_at]);
  const back = returnHash ?? REPLAY_ROUTE_HASH;
  const elapsed = stream.events[snapshot.index]?.t ?? 0;
  // Below 900 px the log stacks under the notice and is never collapsed.
  const logCollapsed = prefs.logCollapsed && !narrow;
  const toggleLog = useCallback(() => savePrefs({ logCollapsed: !prefs.logCollapsed }), [prefs.logCollapsed]);

  return (
    <div className="replay-page">
      <header className="replay-header">
        <a className="replay-back" href={back}>
          ← Back
        </a>
        <h3 className="replay-title">
          <span>{playerSeat?.deck_name || 'Your deck'}</span>
          <span className="replay-vs">vs</span>
          <span>{opponentSeat?.deck_name || opponentSeat?.name || 'Opponent'}</span>
        </h3>
        <FidelityBadge stream={stream} />
        <span className="replay-meta">
          {game.format}
          {startedAt}
        </span>
        <Badge tone={outcomeTone(game.outcome)}>{outcomeLabel(game.outcome)}</Badge>
        <div className="replay-header-actions">
          {narrow ? null : (
            <button
              type="button"
              className="replay-btn replay-export-btn"
              onClick={video.open}
              disabled={video.state.status === 'running'}
              title="Render this replay to an MP4 video"
            >
              <span className="replay-btn-icon" aria-hidden="true">
                ⬇
              </span>
              {video.state.status === 'running' ? 'Exporting…' : 'Export video'}
            </button>
          )}
          <button
            type="button"
            className="replay-btn"
            data-table-toggle
            aria-expanded={tableOpen}
            aria-haspopup="dialog"
            onClick={() => setTableOpen((open) => !open)}
            title="Table colors, camera and view (T)"
          >
            Replay Options
          </button>
          {tableOpen ? (
            <TablePopover prefs={prefs} hindsightAvailable={timeline.hindsight.size > 0} onClose={closeTable} />
          ) : null}
        </div>
      </header>
      <div className={`replay-body${logCollapsed ? ' replay-body-log-collapsed' : ''}`}>
        <section className="replay-stage" aria-label="Table">
          <ReplayHud stream={stream} state={state} elapsed={elapsed} />
          {narrow ? (
            <div className="state-panel replay-narrow-notice" role="note">
              The 3D table needs a window at least 900 px wide. Widen the window to watch the replay; the action log
              still works below.
            </div>
          ) : (
            <div className="replay-table-area" ref={setTableNode}>
              <ReplayScene
                layout={layout}
                state={state}
                prefs={prefs}
                cards={stream.cards}
                store={store}
                hover={hover}
                zoom={zoom}
                snap={jumped}
                playing={snapshot.playing}
                onCardClick={onCardClick}
                onTableFit={onTableFit}
                exportHandle={video.handle}
              />
              {video.state.status === 'idle' ? (
                <GameEndOverlay stream={stream} state={state} clock={clock} backHash={back} />
              ) : null}
              <VideoExportPanel controller={video} stream={stream} prefs={prefs} currentIndex={snapshot.index} stageSize={stageSize} />
            </div>
          )}
        </section>
        <aside className={`replay-log-panel${logCollapsed ? ' replay-log-collapsed' : ''}`} aria-label="Action log">
          <div className="replay-log-head">
            {logCollapsed ? null : <h3>Actions</h3>}
            {narrow ? null : (
              <CollapseToggle
                collapsed={logCollapsed}
                side="right"
                label="actions"
                className="replay-log-toggle"
                title={logCollapsed ? 'Show the action log' : 'Hide the action log (more room for the table)'}
                onToggle={toggleLog}
              />
            )}
          </div>
          {logCollapsed ? (
            <span className="replay-log-rail-label" aria-hidden="true">
              Actions
            </span>
          ) : (
            <ReplayLog
              stream={stream}
              seq={snapshot.seq}
              hover={hover}
              cardReturnHash={replayRouteHash(gameId, { returnHash })}
              returnHashNow={hereHash}
              onSeek={onSeek}
            />
          )}
        </aside>
      </div>
      <ReplayControls stream={stream} clock={clock} snapshot={snapshot} goToTurnRef={goToTurnRef} />
      <CardPreview hover={hover} store={store} />
    </div>
  );
}
