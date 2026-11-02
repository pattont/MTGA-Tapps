import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as encoder from '../export/mp4Encoder';
import { makeSampleStream } from '../fixtures/sampleStream';
import type { ExportState, VideoExportController } from '../hooks/useVideoExport';
import { DEFAULT_PREFS } from '../prefs';
import type { ExportResult } from './ExportDriver';
import { VideoExportPanel } from './VideoExport';

vi.mock('../export/mp4Encoder', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../export/mp4Encoder')>()),
  encoderCodec: vi.fn(),
}));

const stream = makeSampleStream();
const FIREFOX = 'Mozilla/5.0 (Windows NT 10.0; rv:144.0) Gecko/20100101 Firefox/144.0';
const CHROME = 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36';

function panel(state: ExportState) {
  const controller = { state, supported: true, open: vi.fn(), close: vi.fn(), start: vi.fn(), cancel: vi.fn(), handle: null } as VideoExportController;
  return render(<VideoExportPanel controller={controller} stream={stream} prefs={DEFAULT_PREFS} currentIndex={0} />);
}

function result(size: number, codec: string): ExportResult {
  const blob = new Blob([new Uint8Array(1)]);
  Object.defineProperty(blob, 'size', { value: size });
  return { blob, fileName: 'replay.mp4', seconds: 300, codec, width: 1920, height: 1080, estimateBytes: 60_000_000 };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(encoder.encoderCodec).mockReset();
});

describe('VideoExportPanel', () => {
  it('shows the size so far and the projected total while rendering', () => {
    const job = { id: 1, plan: { frames: [], fps: 30, seconds: 60 }, targetWidth: 1920, includeLog: true, quality: 'balanced' } as never;
    panel({ status: 'running', job, progress: { phase: 'frames', done: 450, total: 1800, bytes: 6_000_000 } });
    expect(screen.getByText(/450 \/ 1800 · 25% · 6\.0 MB so far, about 24\.0 MB in all/)).toBeTruthy();
  });

  it('says a file well under the estimate is complete', () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(FIREFOX);
    panel({ status: 'done', result: result(30_000_000, 'vp09.00.40.08'), url: 'blob:x' });
    expect(screen.getByText(/The video is complete\..*Firefox's VP9/)).toBeTruthy();
  });

  it('adds no note when the file is close to the estimate', () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    panel({ status: 'done', result: result(55_000_000, 'avc1.640028'), url: 'blob:x' });
    expect(screen.queryByText(/The video is complete/)).toBeNull();
  });

  it("locks Quality when Firefox would use its VP9 encoder", async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(FIREFOX);
    vi.mocked(encoder.encoderCodec).mockResolvedValue('vp09.00.40.08');
    panel({ status: 'dialog' });
    const select = screen.getByRole('combobox', { name: 'Quality' }) as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(true));
    expect(screen.getByText(/Quality can.t be changed here/)).toBeTruthy();
    expect(screen.queryByText(/at most about/)).toBeNull();
  });

  it('keeps Quality for Firefox on H.264, which follows it', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(FIREFOX);
    vi.mocked(encoder.encoderCodec).mockResolvedValue('avc1.640028');
    panel({ status: 'dialog' });
    await waitFor(() => expect(encoder.encoderCodec).toHaveBeenCalled());
    await act(async () => {});
    expect((screen.getByRole('combobox', { name: 'Quality' }) as HTMLSelectElement).disabled).toBe(false);
    expect(screen.getByText(/at most about/)).toBeTruthy();
  });

  it('never probes the encoder outside Firefox', () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(CHROME);
    panel({ status: 'dialog' });
    expect(encoder.encoderCodec).not.toHaveBeenCalled();
    expect((screen.getByRole('combobox', { name: 'Quality' }) as HTMLSelectElement).disabled).toBe(false);
  });
});
