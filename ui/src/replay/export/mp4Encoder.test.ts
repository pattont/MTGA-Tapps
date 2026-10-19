import { describe, expect, it } from 'vitest';
import { chunkMetadata } from './mp4Encoder';

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
