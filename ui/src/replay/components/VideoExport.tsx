/**
 * Video export UI: the options dialog (speed, pacing, range, size), the
 * progress panel with cancel, and the finished/failed states. The state
 * machine is hooks/useVideoExport; the rendering runs in the scene
 * (ExportDriver).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { DEFAULT_TARGET_WIDTH, LOG_PX, frameLayout } from '../export/frameComposer';
import { estimateBytes } from '../export/mp4Encoder';
import type { VideoQuality } from '../export/mp4Encoder';
import { buildVideoPlan } from '../export/videoPlan';
import { openingEndIndex } from '../scrub';
import type { ExportOptions, VideoExportController } from '../hooks/useVideoExport';
import { formatClock } from '../logText';
import { PLAYBACK_SPEEDS } from '../player';
import type { Pacing, PlaybackSpeed } from '../player';
import type { ReplayPrefs } from '../prefs';
import type { ReplayStream } from '../types';
import type { ExportProgress } from './ExportDriver';

function formatBytes(bytes: number): string {
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1000))} kB`;
}

/** "H.264" or "VP9" from a WebCodecs codec string. */
function codecName(codec: string): string {
  if (codec.startsWith('avc1')) return 'H.264';
  if (codec.startsWith('vp09')) return 'VP9';
  return codec;
}

const SIZES: ReadonlyArray<{ width: number; label: string }> = [
  { width: 1920, label: 'Full HD (1920 wide)' },
  { width: 1280, label: 'HD (1280 wide)' },
];

const QUALITIES: ReadonlyArray<{ value: VideoQuality; label: string }> = [
  { value: 'small', label: 'Smaller file' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'best', label: 'Best quality' },
];

function OptionsForm({
  stream,
  prefs,
  currentIndex,
  stageSize,
  onStart,
  onClose,
}: {
  stream: ReplayStream;
  prefs: ReplayPrefs;
  currentIndex: number;
  stageSize: { width: number; height: number } | null;
  onStart: (options: ExportOptions) => void;
  onClose: () => void;
}) {
  const [speed, setSpeed] = useState<PlaybackSpeed>(prefs.speed);
  const [pacing, setPacing] = useState<Pacing>(prefs.pacing);
  const [range, setRange] = useState<'game' | 'here'>('game');
  const [targetWidth, setTargetWidth] = useState(DEFAULT_TARGET_WIDTH);
  const [includeLog, setIncludeLog] = useState(true);
  const [quality, setQuality] = useState<VideoQuality>('balanced');
  const plan = useMemo(
    () => buildVideoPlan(stream.events, { speed, pacing, fromIndex: range === 'here' ? currentIndex : openingEndIndex(stream.events) }),
    [stream.events, speed, pacing, range, currentIndex],
  );
  const estimate = useMemo(() => {
    const size = stageSize ?? { width: 840, height: 659 };
    const layout = frameLayout(size.width, size.height, targetWidth, includeLog);
    return { layout, bytes: estimateBytes(layout.width, layout.height, plan.fps, quality, plan.seconds) };
  }, [stageSize, targetWidth, includeLog, quality, plan]);
  return (
    <>
      <p className="replay-export-lead">
        Renders the table exactly as it plays here, with the HUD, stack, badges and each action as a caption, into an
        MP4 you can share. Nothing is uploaded.
      </p>
      <div className="replay-export-grid">
        <label>
          <span>Speed</span>
          <select value={speed} onChange={(event) => setSpeed(Number(event.target.value) as PlaybackSpeed)}>
            {PLAYBACK_SPEEDS.map((value) => (
              <option key={value} value={value}>
                {value}×
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Pacing</span>
          <select value={pacing} onChange={(event) => setPacing(event.target.value as Pacing)}>
            <option value="paced">Paced (readable holds)</option>
            <option value="realtime">Real time (the game's own gaps)</option>
          </select>
        </label>
        <label>
          <span>Range</span>
          <select value={range} onChange={(event) => setRange(event.target.value as 'game' | 'here')}>
            <option value="game">Whole game</option>
            <option value="here">From the current moment</option>
          </select>
        </label>
        <label>
          <span>Size</span>
          <select value={targetWidth} onChange={(event) => setTargetWidth(Number(event.target.value))}>
            {SIZES.map((size) => (
              <option key={size.width} value={size.width}>
                {size.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Quality</span>
          <select value={quality} onChange={(event) => setQuality(event.target.value as VideoQuality)}>
            {QUALITIES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="replay-export-check">
          <input type="checkbox" checked={includeLog} onChange={(event) => setIncludeLog(event.target.checked)} />
          <span>Actions log beside the table ({LOG_PX} px column)</span>
        </label>
      </div>
      <p className="replay-export-estimate" aria-live="polite">
        About {formatClock(plan.seconds)} of video at 30 fps, {estimate.layout.width}×{estimate.layout.height}, up to
        about {formatBytes(estimate.bytes)}
        {plan.truncated ? ' (capped at 20 minutes; raise the speed for the whole game)' : ''}.
      </p>
      <p className="replay-export-note">
        The browser&apos;s encoder has the last word on size: it spends less on still moments, and some (Firefox) keep
        their own quality whatever is chosen here.
      </p>
      <div className="replay-export-actions">
        <button
          type="button"
          className="replay-btn replay-btn-primary"
          onClick={() => onStart({ speed, pacing, range, targetWidth, includeLog, quality })}
        >
          Export
        </button>
        <button type="button" className="replay-btn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </>
  );
}

const PHASE_TEXT: Record<ExportProgress['phase'], string> = {
  art: 'Loading card art…',
  frames: 'Rendering frames',
  encoding: 'Finishing the file…',
};

export function VideoExportPanel({
  controller,
  stream,
  prefs,
  currentIndex,
  stageSize = null,
}: {
  controller: VideoExportController;
  stream: ReplayStream;
  prefs: ReplayPrefs;
  currentIndex: number;
  /** The live stage's CSS size, for the size and file estimate. */
  stageSize?: { width: number; height: number } | null;
}) {
  const { state, supported, start, close, cancel } = controller;
  const downloaded = useRef<string | null>(null);
  // Save the file as soon as it is ready (once per result).
  useEffect(() => {
    if (state.status !== 'done' || downloaded.current === state.url) return;
    downloaded.current = state.url;
    const anchor = document.createElement('a');
    anchor.href = state.url;
    anchor.download = state.result.fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }, [state]);
  if (state.status === 'idle') return null;
  return (
    <div className="replay-export" role="dialog" aria-label="Export video" aria-modal="false">
      <div className="replay-export-card">
        <h3>Export video</h3>
        {state.status === 'dialog' ? (
          supported ? (
            <OptionsForm stream={stream} prefs={prefs} currentIndex={currentIndex} stageSize={stageSize} onStart={start} onClose={close} />
          ) : (
            <>
              <p className="replay-export-lead">
                This browser cannot encode video (it lacks WebCodecs). Chrome, Edge, Safari 16.4 or Firefox 130 and
                newer can.
              </p>
              <div className="replay-export-actions">
                <button type="button" className="replay-btn" onClick={close}>
                  Close
                </button>
              </div>
            </>
          )
        ) : null}
        {state.status === 'running' ? (
          <>
            <p className="replay-export-lead">
              {state.progress ? PHASE_TEXT[state.progress.phase] : 'Starting…'}
              {state.progress?.phase === 'frames'
                ? ` ${state.progress.done} / ${state.progress.total} · ${Math.round((100 * state.progress.done) / state.progress.total)}%`
                : ''}
            </p>
            <progress
              className="replay-export-progress"
              max={state.progress?.total ?? 1}
              value={state.progress?.phase === 'art' ? undefined : (state.progress?.done ?? 0)}
              aria-label="Export progress"
            />
            <p className="replay-export-note">The table is busy rendering; playback resumes where it was when this finishes.</p>
            <div className="replay-export-actions">
              <button type="button" className="replay-btn" onClick={cancel}>
                Cancel
              </button>
            </div>
          </>
        ) : null}
        {state.status === 'done' ? (
          <>
            <p className="replay-export-lead">
              Saved <strong>{state.result.fileName}</strong> · {formatClock(state.result.seconds)} ·{' '}
              {state.result.width}×{state.result.height} · {codecName(state.result.codec)} ·{' '}
              {formatBytes(state.result.blob.size)}
            </p>
            <div className="replay-export-actions">
              <a className="replay-btn replay-btn-primary" href={state.url} download={state.result.fileName}>
                Download again
              </a>
              <button type="button" className="replay-btn" onClick={close}>
                Close
              </button>
            </div>
          </>
        ) : null}
        {state.status === 'error' ? (
          <>
            <p className="replay-export-lead replay-export-error">Export failed: {state.message}</p>
            <div className="replay-export-actions">
              <button type="button" className="replay-btn" onClick={close}>
                Close
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
