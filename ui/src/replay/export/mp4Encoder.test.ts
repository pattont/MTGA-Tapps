import { ArrayBufferTarget, Muxer } from 'mp4-muxer';
import { describe, expect, it } from 'vitest';
import { chunkMetadata, muxerOptions, projectedBytes, sizeNote } from './mp4Encoder';

const config = { codec: 'vp09.00.40.08', width: 1280, height: 720 };

describe('chunkMetadata', () => {
  it('fills in a VP9 stream description the encoder left out', () => {
    expect(chunkMetadata('vp9', config, {}, false)?.decoderConfig).toEqual({
      codec: 'vp09.00.40.08',
      codedWidth: 1280,
      codedHeight: 720,
      colorSpace: { primaries: 'bt709', transfer: 'bt709', matrix: 'bt709', fullRange: false },
    });
    expect(chunkMetadata('vp9', config, undefined, false)?.decoderConfig?.codec).toBe('vp09.00.40.08');
  });

  it('adds only a colour space to a VP9 description that has none', () => {
    const meta = chunkMetadata('vp9', config, { decoderConfig: { codec: 'vp09.00.41.08', codedWidth: 640 } }, false);
    expect(meta?.decoderConfig?.codec).toBe('vp09.00.41.08');
    expect(meta?.decoderConfig?.codedWidth).toBe(640);
    expect(meta?.decoderConfig?.colorSpace?.primaries).toBe('bt709');
  });

  it('leaves later chunks and H.264 metadata alone', () => {
    expect(chunkMetadata('vp9', config, {}, true)).toEqual({});
    expect(chunkMetadata('avc', { ...config, codec: 'avc1.640028' }, {}, false)).toEqual({});
    const reported = { decoderConfig: { codec: 'avc1.640028', description: new Uint8Array([1]) } };
    expect(chunkMetadata('avc', { ...config, codec: 'avc1.640028' }, reported, false)).toBe(reported);
  });
});

describe('muxerOptions', () => {
  it('accepts a first chunk stamped one frame late (Firefox)', () => {
    const target = new ArrayBufferTarget();
    const muxer = new Muxer(muxerOptions(target, 'vp9', { width: 1280, height: 720, fps: 30 }));
    const meta = chunkMetadata('vp9', config, undefined, false);
    const frame = Math.round(1_000_000 / 30);
    muxer.addVideoChunkRaw(new Uint8Array([1, 2, 3]), 'key', frame, frame, meta);
    muxer.addVideoChunkRaw(new Uint8Array([4, 5, 6]), 'delta', 2 * frame, frame);
    muxer.finalize();
    expect(target.buffer.byteLength).toBeGreaterThan(0);
  });
});

describe('projectedBytes', () => {
  it('waits until enough frames are encoded to project', () => {
    expect(projectedBytes(0, 10, 1800)).toBeNull();
    expect(projectedBytes(500_000, 59, 1800)).toBeNull();
    expect(projectedBytes(5_000_000, 89, 1800)).toBeNull();
  });

  it('scales the size so far to the whole video', () => {
    expect(projectedBytes(6_000_000, 450, 1800)).toBe(24_000_000);
    expect(projectedBytes(24_100_000, 1800, 1800)).toBe(24_100_000);
  });
});

describe('sizeNote', () => {
  const chrome = 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36';
  const firefox = 'Mozilla/5.0 (Windows NT 10.0; rv:144.0) Gecko/20100101 Firefox/144.0';

  it('says nothing when the file is close to the estimate', () => {
    expect(sizeNote(50_000_000, 60_000_000, 'avc1.640028', chrome)).toBeNull();
    expect(sizeNote(1, 0, 'avc1.640028', chrome)).toBeNull();
  });

  it('explains a small file from a mostly still table', () => {
    expect(sizeNote(30_000_000, 60_000_000, 'avc1.640028', chrome)).toMatch(/mostly still/);
    expect(sizeNote(30_000_000, 60_000_000, 'avc1.640028', firefox)).toMatch(/mostly still/);
  });

  it('gives the estimate it compares against', () => {
    expect(sizeNote(30_000_000, 60_000_000, 'avc1.640028', chrome)).toMatch(/60\.0 MB estimate/);
  });

  it("always names Firefox's VP9 encoder, which ignores the Quality setting", () => {
    expect(sizeNote(30_000_000, 60_000_000, 'vp09.00.40.08', firefox)).toMatch(/Firefox's VP9/);
    expect(sizeNote(59_000_000, 60_000_000, 'vp09.00.40.08', firefox)).toMatch(/Firefox's VP9/);
    expect(sizeNote(30_000_000, 60_000_000, 'vp09.00.40.08', chrome)).toMatch(/mostly still/);
  });
});
