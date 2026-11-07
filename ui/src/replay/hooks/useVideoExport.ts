/**
 * Video export state machine (idle → dialog → running → done | error),
 * shared between the transport bar button, the dialog/progress panel and
 * the scene's ExportDriver through `handle`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { supportsVideoExport } from '../export/mp4Encoder';
import type { VideoFormat, VideoQuality } from '../export/mp4Encoder';
import { buildVideoPlan } from '../export/videoPlan';
import { openingEndIndex } from '../scrub';
import type { Pacing, PlaybackClock, PlaybackSpeed } from '../player';
import type { ReplayStream } from '../types';
import type { ExportHandle, ExportJob, ExportProgress, ExportResult } from '../components/ExportDriver';

export type ExportState =
  | { status: 'idle' }
  | { status: 'dialog' }
  | { status: 'running'; job: ExportJob; progress: ExportProgress | null }
  | { status: 'done'; result: ExportResult; url: string }
  | { status: 'error'; message: string };

export interface ExportOptions {
  speed: PlaybackSpeed;
  pacing: Pacing;
  range: 'game' | 'here';
  targetWidth: number;
  includeLog: boolean;
  quality: VideoQuality;
  format: VideoFormat;
}

export interface VideoExportController {
  state: ExportState;
  supported: boolean;
  open: () => void;
  close: () => void;
  start: (options: ExportOptions) => void;
  cancel: () => void;
  /** Handed to the scene while a job runs. */
  handle: ExportHandle | null;
}

let nextJobId = 1;

export function useVideoExport(stream: ReplayStream, clock: PlaybackClock, currentIndex: number): VideoExportController {
  const [state, setState] = useState<ExportState>({ status: 'idle' });
  const supported = useMemo(() => supportsVideoExport(), []);

  // The finished file's object URL lives exactly as long as the done state.
  useEffect(() => {
    if (state.status !== 'done') return;
    const { url } = state;
    return () => URL.revokeObjectURL(url);
  }, [state]);

  const open = useCallback(() => setState((s) => (s.status === 'running' ? s : { status: 'dialog' })), []);
  const close = useCallback(() => setState({ status: 'idle' }), []);
  const cancel = useCallback(() => setState({ status: 'idle' }), []);

  const start = useCallback(
    (options: ExportOptions) => {
      const plan = buildVideoPlan(stream.events, {
        speed: options.speed,
        pacing: options.pacing,
        fromIndex: options.range === 'here' ? currentIndex : openingEndIndex(stream.events),
      });
      if (!plan.frames.length) {
        setState({ status: 'error', message: 'There is nothing to export.' });
        return;
      }
      const job: ExportJob = {
        id: nextJobId,
        plan,
        targetWidth: options.targetWidth,
        includeLog: options.includeLog,
        quality: options.quality,
        format: options.format,
      };
      nextJobId += 1;
      setState({ status: 'running', job, progress: null });
    },
    [stream.events, currentIndex],
  );

  const job = state.status === 'running' ? state.job : null;
  const handle = useMemo<ExportHandle | null>(() => {
    if (!job) return null;
    return {
      job,
      stream,
      clock,
      onProgress: (progress) => setState((s) => (s.status === 'running' && s.job.id === job.id ? { ...s, progress } : s)),
      onDone: (result) => setState({ status: 'done', result, url: URL.createObjectURL(result.blob) }),
      onError: (message) => setState({ status: 'error', message }),
    };
  }, [job, stream, clock]);

  return { state, supported, open, close, start, cancel, handle };
}
