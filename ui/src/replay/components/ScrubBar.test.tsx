import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { makeSampleStream } from '../fixtures/sampleStream';
import type { PlaybackClock, PlaybackSnapshot } from '../player';
import { indexAtFraction, openingEndIndex } from '../scrub';
import { ScrubBar } from './ScrubBar';

const stream = makeSampleStream();
const first = openingEndIndex(stream.events);
const total = stream.events.length - first;
const seqAt = (fraction: number) => stream.events[first + indexAtFraction(fraction, total)].seq;

function setup() {
  const clock = { seek: vi.fn(), pause: vi.fn(), play: vi.fn(), snapshot: { atEnd: false } } as unknown as PlaybackClock;
  const snapshot = { index: first, playing: false, turn: 1, atEnd: false } as unknown as PlaybackSnapshot;
  render(<ScrubBar stream={stream} clock={clock} snapshot={snapshot} />);
  const track = screen.getByRole('slider', { name: 'Replay position' });
  vi.spyOn(track, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 200, top: 0, height: 20, right: 200, bottom: 20, x: 0, y: 0, toJSON: () => ({}) });
  return { clock, track };
}

afterEach(() => vi.restoreAllMocks());

describe('ScrubBar', () => {
  it('never lets the browser start a selection or a drag-and-drop from the bar', () => {
    const { track } = setup();
    expect(fireEvent.pointerDown(track, { button: 0, clientX: 20, pointerId: 1 })).toBe(false);
    expect(fireEvent.dragStart(track)).toBe(false);
  });

  it('keeps the last dragged position when the browser cancels the drag', () => {
    const { clock, track } = setup();
    fireEvent.pointerDown(track, { button: 0, clientX: 20, pointerId: 1 });
    fireEvent.pointerMove(track, { clientX: 150, pointerId: 1 });
    // A cancel reports no real place on the bar (often 0): it must not seek there.
    fireEvent.pointerCancel(track, { clientX: 0, pointerId: 1 });
    expect(vi.mocked(clock.seek).mock.lastCall).toEqual([seqAt(0.75)]);
    // A pointer released past the end of the track stops at the end.
    fireEvent.pointerDown(track, { button: 0, clientX: 20, pointerId: 2 });
    fireEvent.pointerUp(track, { clientX: 900, pointerId: 2 });
    expect(vi.mocked(clock.seek).mock.lastCall).toEqual([seqAt(1)]);
  });
});
