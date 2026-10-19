import { describe, expect, it } from 'vitest';
import { PerspectiveCamera, Vector3 } from 'three';
import { StreamBuilder } from '../fixtures/streamBuilder';
import { buildTimeline } from '../reducer';
import { CARD_HEIGHT, CARD_WIDTH, layoutBoard } from '../layout';
import type { CardPlacement } from '../layout';
import { DEFAULT_MARGINS, applyPerspective, fitPerspective, fitTableForView } from './cameraFit';
import { depthStretch, stretchedScale } from './motion';
import type { Viewport } from './cameraFit';

const axis = new Vector3(0, 0, 1);

/** Screen-space (NDC) y range of `cards` as the scene draws them: floating, depth-stretched, turned. */
function screenY(camera: PerspectiveCamera, cards: CardPlacement[]): { min: number; max: number } {
  let min = Infinity;
  let max = -Infinity;
  const s = { x: 0, y: 0 };
  for (const c of cards) {
    stretchedScale(c.scale, depthStretch(camera.position, c.x, c.y, c.z), c.rotZ, s);
    for (const dx of [-1, 1]) {
      for (const dy of [-1, 1]) {
        const p = new Vector3((dx * CARD_WIDTH * s.x) / 2, (dy * CARD_HEIGHT * s.y) / 2, 0)
          .applyAxisAngle(axis, c.rotZ)
          .add(new Vector3(c.x, c.y, c.z))
          .project(camera);
        min = Math.min(min, p.y);
        max = Math.max(max, p.y);
      }
    }
  }
  return { min, max };
}

describe('hand framing', () => {
  it('keeps both floating hands on screen for laptop, desktop, Retina and narrow stages', () => {
    const b = new StreamBuilder();
    b.add('game_start', { seats_hand_sizes: { 1: 7, 2: 7 }, library_sizes: { 1: 40, 2: 40 } });
    const state = buildTimeline(b.build({}, { playerSeat: 1 })).final;
    const stages: Array<[Viewport, number]> = [
      [{ width: 1070, height: 685 }, 2], // Retina laptop
      [{ width: 1070, height: 685 }, 1],
      [{ width: 1400, height: 1000 }, 1], // 1440p monitor
      [{ width: 1400, height: 1000 }, 2], // 5K display
      [{ width: 1700, height: 900 }, 2],
      [{ width: 900, height: 900 }, 2],
      [{ width: 840, height: 1100 }, 1], // narrow: the hands grow
    ];
    for (const [view, pixelRatio] of stages) {
      const fit = fitTableForView(view, DEFAULT_MARGINS, 'table', undefined, pixelRatio);
      const { cards, table } = layoutBoard(state, {
        mirrorOpponent: false,
        hindsight: false,
        playerSeat: 1,
        tableWidth: fit.width,
        handScale: fit.handScale,
        opponentHandScale: fit.opponentHandScale,
      });
      const camera = new PerspectiveCamera();
      applyPerspective(camera, fitPerspective(0, view, DEFAULT_MARGINS, table), view);
      const theirs = screenY(camera, cards.filter((c) => c.row === 'hand' && c.seat === 2));
      const mine = screenY(camera, cards.filter((c) => c.row === 'hand' && c.seat === 1));
      // Inside the stage, using at most half the fit margin.
      const allowance = DEFAULT_MARGINS.top / view.height;
      expect(theirs.max, `${view.width}x${view.height}@${pixelRatio}x`).toBeLessThanOrEqual(1 - allowance);
      expect(mine.min, `${view.width}x${view.height}@${pixelRatio}x`).toBeGreaterThanOrEqual(-1 + allowance);
    }
  });
});
