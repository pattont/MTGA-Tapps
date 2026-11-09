/**
 * MP4 encoding in the browser: WebCodecs `VideoEncoder` (H.264 when the
 * browser offers it, else VP9) muxed into a fast-start MP4 by mp4-muxer.
 * Frames are pushed one canvas at a time with explicit timestamps, so the
 * export can run faster than real time. Nothing leaves the machine.
 */
import { ArrayBufferTarget, Muxer, type MuxerOptions } from 'mp4-muxer';

export type VideoQuality = 'small' | 'balanced' | 'best';

/**
 * H.264 plays everywhere (QuickTime, phones); VP9 plays in browsers, VLC,
 * Discord and Windows' own player, and is sharper where the browser only has
 * a software H.264 encoder (Chrome's ignores the bitrate and stays near 1 Mbps).
 */
export type VideoFormat = 'h264' | 'vp9';

export interface Mp4EncoderOptions {
  width: number;
  height: number;
  fps: number;
  /** Target bitrate class; 'balanced' when omitted. */
  quality?: VideoQuality;
  /** Codec to try first; 'h264' when omitted. The other is the fallback. */
  format?: VideoFormat;
}

export interface Mp4Encoder {
  /** Codec string actually in use (for the done message). */
  readonly codec: string;
  /** Bytes of video encoded so far. */
  readonly bytes: number;
  /** Encodes one frame; resolves once the encoder has room for the next. */
  addFrame(source: CanvasImageSource, index: number): Promise<void>;
  /** Flushes and muxes; resolves with the MP4. */
  finish(): Promise<Blob>;
  /** Drops everything encoded so far. */
  cancel(): void;
}

/** The browser can encode video (Chrome, Edge, Safari 16.4+, Firefox 130+). */
export function supportsVideoExport(): boolean {
  return typeof VideoEncoder !== 'undefined' && typeof VideoFrame !== 'undefined';
}

type Candidate = { container: 'avc' | 'vp9'; codec: string };
/** H.264 profiles, best first: High, Main, Baseline. */
const AVC: readonly Candidate[] = [
  { container: 'avc', codec: 'avc1.640028' },
  { container: 'avc', codec: 'avc1.4d0028' },
  { container: 'avc', codec: 'avc1.42001f' },
];
const VP9: readonly Candidate[] = [{ container: 'vp9', codec: 'vp09.00.40.08' }];

/** Codecs to try, the chosen format first and the other as a fallback. */
export function candidatesFor(format: VideoFormat = 'h264'): readonly Candidate[] {
  return format === 'vp9' ? [...VP9, ...AVC] : [...AVC, ...VP9];
}

/** Bits per pixel per frame and the ceiling for each quality; the table is mostly still, so modest rates look clean. */
const QUALITY: Record<VideoQuality, { bpp: number; cap: number }> = {
  small: { bpp: 0.02, cap: 2_500_000 },
  balanced: { bpp: 0.04, cap: 5_000_000 },
  best: { bpp: 0.09, cap: 12_000_000 },
};

/** Bits per second for a frame size, rate and quality. */
export function bitrateFor(width: number, height: number, fps: number, quality: VideoQuality = 'balanced'): number {
  const { bpp, cap } = QUALITY[quality];
  return Math.min(cap, Math.max(600_000, Math.round(width * height * fps * bpp)));
}

/** Rough file size in bytes for `seconds` of video. */
export function estimateBytes(width: number, height: number, fps: number, quality: VideoQuality, seconds: number): number {
  return Math.round((bitrateFor(width, height, fps, quality) / 8) * seconds);
}

/**
 * The final size projected from what is encoded so far, or null while too
 * little is done to say (the first key frame alone would inflate it).
 */
export function projectedBytes(bytes: number, done: number, total: number): number | null {
  if (total <= 0 || done <= 0 || bytes <= 0) return null;
  if (done >= total) return bytes;
  if (done < Math.max(60, total * 0.05)) return null;
  return Math.round((bytes * total) / done);
}

/**
 * Firefox's VP9 encoder (what Firefox on Windows ends up with) ignores the
 * bitrate and every other quality control, so the Quality choice and the
 * size estimate mean nothing there. Its H.264 encoder (Firefox on a Mac)
 * does follow the bitrate.
 */
export function qualityIgnored(codec: string, userAgent: string): boolean {
  return codec.startsWith('vp09') && /firefox/i.test(userAgent);
}

/**
 * A note for the finished export when its size needs explaining: always for
 * an encoder that sets its own quality, otherwise when the file is well
 * under the estimate (any encoder spends less than the ceiling on a mostly
 * still table). Null when the size is close to the estimate.
 */
export function sizeNote(actual: number, estimate: number, codec: string, userAgent: string): string | null {
  if (qualityIgnored(codec, userAgent)) {
    return "The video is complete. Firefox's VP9 encoder sets its own quality and size, so the Quality setting has no effect in Firefox.";
  }
  if (!(estimate > 0) || actual >= estimate * 0.75) return null;
  return `The video is complete. It's smaller than the ${formatMegabytes(estimate)} estimate because the table is mostly still, and the encoder needs fewer bytes for still frames.`;
}

function formatMegabytes(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

/** Pending encodes allowed before addFrame waits (keeps memory bounded). */
const MAX_QUEUE = 8;
/** An encoder that accepts frames but outputs nothing for this long is treated as stalled. */
const STALL_MS = 20_000;
/** One key frame every two seconds, so seeking in the result is quick. */
const KEYFRAME_SECONDS = 2;

/** Colour space assumed when the encoder reports none (canvas frames are sRGB, tagged BT.709 by every browser). */
const BT709: VideoColorSpaceInit = { primaries: 'bt709', transfer: 'bt709', matrix: 'bt709', fullRange: false };
/** How long the one-frame probe may take before that codec is skipped. */
const PROBE_MS = 10_000;

/**
 * The metadata to hand the muxer with one encoded chunk. The MP4 header needs
 * the stream setup (`decoderConfig`) the encoder reports with its first key
 * frame; some browsers omit it, which mp4-muxer only notices when it finalizes.
 * VP9 needs no codec-private data, so a missing config is filled in from what
 * we asked for; H.264 cannot be, so it passes through unchanged.
 */
export function chunkMetadata(
  container: 'avc' | 'vp9',
  config: Pick<VideoEncoderConfig, 'codec' | 'width' | 'height'>,
  meta: EncodedVideoChunkMetadata | undefined,
  haveConfig: boolean,
): EncodedVideoChunkMetadata | undefined {
  if (container !== 'vp9') return meta;
  const reported = meta?.decoderConfig;
  if (reported) return reported.colorSpace ? meta : { ...meta, decoderConfig: { ...reported, colorSpace: BT709 } };
  if (haveConfig) return meta;
  return {
    ...meta,
    decoderConfig: { codec: config.codec, codedWidth: config.width, codedHeight: config.height, colorSpace: BT709 },
  };
}

/** One encoded frame, held until the export finishes. */
export interface HeldChunk {
  data: Uint8Array;
  type: 'key' | 'delta';
  /** Presentation time in microseconds, as the encoder stamped it. */
  timestamp: number;
  meta: EncodedVideoChunkMetadata | undefined;
}

/**
 * Decode times for chunks in the order the encoder output them. An encoder
 * that uses B-frames (Firefox's H.264 on Windows) outputs frames in decode
 * order, so their presentation times go 1, 3, 2, 5, 4…; the MP4 needs decode
 * times that only rise, each at or before its frame's presentation time.
 * They are the presentation times sorted, moved back just enough for that.
 * Frames already in order get their own times back unchanged.
 */
export function decodeTimestamps(presentation: readonly number[]): number[] {
  const decode = [...presentation].sort((a, b) => a - b);
  for (let i = 1; i < decode.length; i += 1) {
    if (decode[i] <= decode[i - 1]) decode[i] = decode[i - 1] + 1;
  }
  let shift = 0;
  decode.forEach((time, i) => {
    shift = Math.max(shift, time - presentation[i]);
  });
  return shift ? decode.map((time) => time - shift) : decode;
}

/** Hands the held chunks to the muxer with decode times that suit any frame order. */
export function muxChunks(muxer: Muxer<ArrayBufferTarget>, chunks: readonly HeldChunk[], frameMicros: number): void {
  const decode = decodeTimestamps(chunks.map((chunk) => chunk.timestamp));
  chunks.forEach((chunk, i) => {
    muxer.addVideoChunkRaw(chunk.data, chunk.type, chunk.timestamp, Math.round(frameMicros), chunk.meta, chunk.timestamp - decode[i]);
  });
}

/**
 * Muxer setup. Frames go in from timestamp 0, but some encoders (Firefox's)
 * stamp their first chunk one frame later, and mp4-muxer's default rejects
 * any first chunk not at 0. 'offset' starts the track at whatever comes first.
 */
export function muxerOptions(
  target: ArrayBufferTarget,
  container: 'avc' | 'vp9',
  opts: Pick<Mp4EncoderOptions, 'width' | 'height' | 'fps'>,
): MuxerOptions<ArrayBufferTarget> {
  return {
    target,
    video: { codec: container, width: opts.width, height: opts.height, frameRate: opts.fps },
    fastStart: 'in-memory',
    firstTimestampBehavior: 'offset',
  };
}

/** A frame-sized canvas with something drawn on it, for the probe. */
function probeCanvas(width: number, height: number): CanvasImageSource {
  const canvas: OffscreenCanvas | HTMLCanvasElement =
    typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(width, height) : Object.assign(document.createElement('canvas'), { width, height });
  const ctx = canvas.getContext('2d') as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null;
  if (ctx) {
    ctx.fillStyle = '#123';
    ctx.fillRect(0, 0, width, height);
  }
  return canvas;
}

/**
 * Encodes one frame with `config` and reports whether the result can be muxed:
 * a browser can call a codec supported and then produce nothing, or (H.264)
 * no stream description, which only surfaces after the whole export.
 */
async function probeEncoder(container: 'avc' | 'vp9', config: VideoEncoderConfig): Promise<boolean> {
  let chunks = 0;
  let described = false;
  let failed = false;
  const encoder = new VideoEncoder({
    output: (_chunk, meta) => {
      chunks += 1;
      if (meta?.decoderConfig?.description) described = true;
    },
    error: () => {
      failed = true;
    },
  });
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    encoder.configure(config);
    const frame = new VideoFrame(probeCanvas(config.width, config.height), { timestamp: 0 });
    try {
      encoder.encode(frame, { keyFrame: true });
    } finally {
      frame.close();
    }
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error('probe timed out')), PROBE_MS);
    });
    await Promise.race([encoder.flush(), timeout]);
  } catch {
    failed = true;
  } finally {
    clearTimeout(timer);
    try {
      encoder.close();
    } catch {
      // Already closed by an error.
    }
  }
  return !failed && chunks > 0 && (container === 'vp9' || described);
}

async function pickConfig(opts: Mp4EncoderOptions): Promise<{ container: 'avc' | 'vp9'; config: VideoEncoderConfig }> {
  const bitrate = bitrateFor(opts.width, opts.height, opts.fps, opts.quality ?? 'balanced');
  for (const candidate of candidatesFor(opts.format)) {
    // No acceleration preference: the browser uses a hardware encoder when it
    // has one and software otherwise (asking for hardware outright can be
    // reported as supported and then never produce a frame).
    const config: VideoEncoderConfig = {
      codec: candidate.codec,
      width: opts.width,
      height: opts.height,
      bitrate,
      framerate: opts.fps,
      latencyMode: 'quality',
      ...(candidate.container === 'avc' ? { avc: { format: 'avc' } } : {}),
    };
    try {
      const support = await VideoEncoder.isConfigSupported(config);
      if (!support.supported) continue;
      const chosen = support.config ?? config;
      if (await probeEncoder(candidate.container, chosen)) return { container: candidate.container, config: chosen };
    } catch {
      // Try the next codec.
    }
  }
  throw new Error('This browser cannot encode H.264 or VP9 video.');
}

const codecChoices = new Map<string, Promise<string>>();

/**
 * The codec an export of this size would use, found the same way the export
 * finds it (one probe frame per candidate) and remembered per size, so the
 * dialog can tell before the export starts.
 */
export function encoderCodec(width: number, height: number, fps: number, format: VideoFormat = 'h264'): Promise<string> {
  const key = `${width}x${height}@${fps}/${format}`;
  let choice = codecChoices.get(key);
  if (!choice) {
    choice = pickConfig({ width, height, fps, format }).then(({ config }) => config.codec);
    choice.catch(() => codecChoices.delete(key));
    codecChoices.set(key, choice);
  }
  return choice;
}

export async function createMp4Encoder(opts: Mp4EncoderOptions): Promise<Mp4Encoder> {
  if (!supportsVideoExport()) throw new Error('Video export needs a browser with WebCodecs.');
  if (opts.width % 2 || opts.height % 2) throw new Error('Video dimensions must be even.');
  const { container, config } = await pickConfig(opts);
  const target = new ArrayBufferTarget();
  const muxer = new Muxer(muxerOptions(target, container, opts));
  let failure: Error | null = null;
  // Chunks wait here until finish(), when the whole order is known (see decodeTimestamps).
  const held: HeldChunk[] = [];
  let bytes = 0;
  let haveConfig = false;
  const encoder = new VideoEncoder({
    output: (chunk, meta) => {
      const muxMeta = chunkMetadata(container, config, meta, haveConfig);
      if (muxMeta?.decoderConfig) haveConfig = true;
      const data = new Uint8Array(chunk.byteLength);
      chunk.copyTo(data);
      held.push({ data, type: chunk.type, timestamp: chunk.timestamp, meta: muxMeta });
      bytes += chunk.byteLength;
    },
    error: (error) => {
      failure = error instanceof Error ? error : new Error(String(error));
    },
  });
  encoder.configure(config);
  const frameMicros = 1_000_000 / opts.fps;
  const keyEvery = Math.max(1, Math.round(opts.fps * KEYFRAME_SECONDS));
  let closed = false;

  const waitForRoom = async () => {
    const started = performance.now();
    while (encoder.encodeQueueSize > MAX_QUEUE && !failure) {
      if (performance.now() - started > STALL_MS) {
        failure = new Error('The video encoder stopped responding.');
        break;
      }
      await new Promise<void>((resolve) => setTimeout(resolve, 4));
    }
  };

  return {
    codec: config.codec,
    get bytes() {
      return bytes;
    },
    async addFrame(source, index) {
      if (failure) throw failure;
      if (closed) throw new Error('Encoder closed.');
      const frame = new VideoFrame(source, {
        timestamp: Math.round(index * frameMicros),
        duration: Math.round(frameMicros),
      });
      try {
        encoder.encode(frame, { keyFrame: index % keyEvery === 0 });
      } finally {
        frame.close();
      }
      await waitForRoom();
      if (failure) throw failure;
    },
    async finish() {
      if (closed) throw new Error('Encoder closed.');
      await encoder.flush();
      if (failure) throw failure;
      closed = true;
      encoder.close();
      // Checked here because mp4-muxer would otherwise fail with a bare
      // "decoderConfig is null" when it writes the header.
      if (held.length === 0) throw new Error('The video encoder produced no video.');
      if (!haveConfig) throw new Error("The browser's video encoder did not describe its stream, so the MP4 cannot be written.");
      muxChunks(muxer, held, frameMicros);
      held.length = 0;
      muxer.finalize();
      return new Blob([target.buffer], { type: 'video/mp4' });
    },
    cancel() {
      if (closed) return;
      closed = true;
      held.length = 0;
      try {
        encoder.close();
      } catch {
        // Already closed by an error.
      }
    },
  };
}
