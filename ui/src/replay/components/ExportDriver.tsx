/**
 * Runs a video export from inside the R3F canvas. For every planned frame it
 * steps the playback clock (synchronously, so React commits the new board
 * before the frame), drives one fixed-step animation frame through R3F's
 * `advance`, renders the table, redraws the DOM overlays with Canvas 2D on
 * top of it (frameComposer) and hands the frame to the MP4 encoder. Runs as
 * fast as the machine allows, never in real time, and restores the clock
 * when it is done or cancelled.
 */
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useRef } from 'react';
import { flushSync } from 'react-dom';
import { composeFrame, frameLayout } from '../export/frameComposer';
import type { FrameLayout } from '../export/frameComposer';
import { buildFrameInput } from '../export/frameInput';
import type { FrameSource } from '../export/frameInput';
import { createMp4Encoder } from '../export/mp4Encoder';
import type { VideoQuality } from '../export/mp4Encoder';
import { exportFileName } from '../export/videoPlan';
import type { VideoPlan } from '../export/videoPlan';
import { buildLogItems } from '../logText';
import type { LogItem } from '../logText';
import type { PlaybackClock } from '../player';
import type { ReplayStream } from '../types';
import type { CardKey } from '../types';
import type { ScreenPoint } from '../scene/projection';

export interface ExportJob {
  id: number;
  plan: VideoPlan;
  /** Video width to aim for (the stage, plus the log column, is scaled up to it, at most 3×). */
  targetWidth: number;
  /** Draw the actions log beside the table (else the current action is a caption). */
  includeLog: boolean;
  quality: VideoQuality;
}

export interface ExportProgress {
  phase: 'art' | 'frames' | 'encoding';
  done: number;
  total: number;
}

export interface ExportResult {
  blob: Blob;
  fileName: string;
  seconds: number;
  codec: string;
  width: number;
  height: number;
}

/** What the viewer hands the scene to run an export. */
export interface ExportHandle {
  job: ExportJob;
  stream: ReplayStream;
  clock: PlaybackClock;
  onProgress: (progress: ExportProgress) => void;
  onDone: (result: ExportResult) => void;
  onError: (message: string) => void;
}

export interface ExportDriverProps extends ExportHandle, Omit<FrameSource, 'stream' | 'clock' | 'logItems'> {}

/** Longest wait for card art before the export starts anyway. */
const ART_TIMEOUT_MS = 30_000;
/** Frames between progress reports and a yield to the browser. */
const REPORT_EVERY = 5;
/** Longest wait for the canvas to commit a new board before the frame is drawn anyway. */
const COMMIT_TIMEOUT_MS = 2_000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export function ExportDriver(props: ExportDriverProps) {
  const { job } = props;
  const size = useThree((s) => s.size);
  const advance = useThree((s) => s.advance);
  const invalidate = useThree((s) => s.invalidate);
  // The frame hook and the export loop read the latest props (the board
  // changes under them every step); the layout effect runs inside flushSync.
  const latest = useRef(props);
  useLayoutEffect(() => {
    latest.current = props;
  });
  const logItems = useRef<readonly LogItem[] | null>(null);
  const capture = useRef<{ ctx: CanvasRenderingContext2D; layout: FrameLayout; canvas: HTMLCanvasElement } | null>(null);
  const pending = useRef(false);
  const point = useRef<ScreenPoint>({ x: 0, y: 0, visible: false });

  // Priority above 0 takes the render over from R3F while the driver is mounted.
  useFrame((root) => {
    const cap = capture.current;
    if (!cap || !pending.current) return;
    pending.current = false;
    root.gl.render(root.scene, root.camera);
    const source = { ...latest.current, logItems: logItems.current };
    composeFrame(cap.ctx, cap.layout, buildFrameInput(source, root.camera, root.gl.domElement, cap.layout, point.current));
  }, 1);

  useEffect(() => {
    let cancelled = false;
    const { stream, store, registry, clock, onProgress, onDone, onError } = latest.current;
    const plan = job.plan;
    const total = plan.frames.length;

    const run = async () => {
      if (!total) throw new Error('Nothing to export.');
      const layout = frameLayout(size.width, size.height, job.targetWidth, job.includeLog);
      logItems.current = job.includeLog ? buildLogItems(stream) : null;
      const canvas = document.createElement('canvas');
      canvas.width = layout.width;
      canvas.height = layout.height;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('This browser cannot draw video frames.');
      capture.current = { ctx, layout, canvas };

      // Card art first, so the video never shows a face still loading.
      onProgress({ phase: 'art', done: 0, total });
      const priorities = new Map<CardKey, number>();
      Object.keys(stream.cards).forEach((key, index) => priorities.set(key, index));
      store.request(priorities);
      const deadline = performance.now() + ART_TIMEOUT_MS;
      while (store.inFlight > 0 && performance.now() < deadline) {
        if (cancelled) return;
        await sleep(100);
      }
      if (cancelled) return;

      // The canvas renders its children with its own reconciler, so a clock
      // step committed with flushSync can reach the board a tick later. Draw
      // only once it has: otherwise a frame shows the previous action, and the
      // closing hold repeats the board from before the game ended.
      const boardCommitted = async () => {
        const deadline = performance.now() + COMMIT_TIMEOUT_MS;
        while (latest.current.state.seq !== clock.snapshot.seq && performance.now() < deadline) await sleep(0);
      };

      const encoder = await createMp4Encoder({ width: layout.width, height: layout.height, fps: plan.fps, quality: job.quality });
      const startSeq = clock.seq;
      const wasPlaying = clock.isPlaying;
      clock.pause();
      registry.fixedStep = 1 / plan.fps;
      try {
        flushSync(() => clock.seek(stream.events[plan.fromIndex].seq));
        await boardCommitted();
        let renderedIndex = -1;
        for (let f = 0; f < total; f += 1) {
          if (cancelled) {
            encoder.cancel();
            return;
          }
          const target = plan.frames[f];
          if (clock.snapshot.index < target) {
            while (clock.snapshot.index < target) flushSync(() => clock.step(1));
            await boardCommitted();
          }
          // A hold with nothing in motion repeats the last frame: no render, no compose.
          const still = renderedIndex === clock.snapshot.index && !registry.busy;
          if (!still) {
            registry.tick();
            pending.current = true;
            advance(performance.now(), true);
            if (pending.current) throw new Error('The table did not render a frame.');
            renderedIndex = clock.snapshot.index;
          }
          await encoder.addFrame(canvas, f);
          if (f % REPORT_EVERY === 0) {
            onProgress({ phase: 'frames', done: f + 1, total });
            await sleep(0);
          }
        }
        onProgress({ phase: 'encoding', done: total, total });
        const blob = await encoder.finish();
        if (cancelled) return;
        onDone({ blob, fileName: exportFileName(stream), seconds: plan.seconds, codec: encoder.codec, width: layout.width, height: layout.height });
      } finally {
        registry.fixedStep = null;
        capture.current = null;
        flushSync(() => clock.seek(startSeq));
        if (wasPlaying) clock.play();
        invalidate();
      }
    };

    run().catch((error: unknown) => {
      if (cancelled) return;
      onError(error instanceof Error ? error.message : String(error));
    });
    return () => {
      cancelled = true;
    };
    // The job id is the whole identity of a run; everything else is read live through `latest`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  return null;
}
