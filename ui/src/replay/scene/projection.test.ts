import { describe, expect, it } from 'vitest';
import { Object3D, OrthographicCamera } from 'three';
import { CARD_HEIGHT, CARD_WIDTH } from '../layout';
import type { Layout } from '../layout';
import { handOccluders, isCovered, positionLabels, projectToScreen } from './projection';
import type { SceneLabel } from './labels';

function camera() {
  const c = new OrthographicCamera(-8, 8, 5, -5, 1, 100);
  c.position.set(0, 0, 40);
  c.lookAt(0, 0, 0);
  c.updateMatrixWorld();
  c.updateProjectionMatrix();
  return c;
}

describe('label projection', () => {
  it('maps world points to canvas pixels', () => {
    const out = { x: 0, y: 0, visible: false };
    projectToScreen(camera(), 0, 0, 0, 800, 500, out);
    expect(out).toMatchObject({ x: 400, y: 250, visible: true });
    projectToScreen(camera(), 8, 5, 0, 800, 500, out);
    expect(out.x).toBeCloseTo(800);
    expect(out.y).toBeCloseTo(0);
  });

  it('positions label elements and follows animated meshes', () => {
    const root = document.createElement('div');
    root.append(document.createElement('span'), document.createElement('span'), document.createElement('span'));
    const labels: SceneLabel[] = [
      { id: 'a', text: 'Library 3', tone: 'pile', obj: null, x: -8, y: 0, z: 0, align: 'center' },
      { id: 'b', text: '3/3', tone: 'stat', obj: 'card', x: 0, y: -1, z: 0, align: 'start' },
      { id: 'c', text: 'gone', tone: 'stat', obj: 'missing', x: 0, y: 0, z: 0, align: 'center' },
    ];
    const poses = (obj: string) => (obj === 'card' ? { x: 4, y: 1, z: 0 } : null);
    positionLabels(root, labels, camera(), { width: 800, height: 500 }, poses, { x: 0, y: 0, visible: false });
    const [a, b, c] = Array.from(root.children) as HTMLElement[];
    expect(a.style.transform).toBe('translate(0px, 250px) translateX(-50%)');
    expect(a.style.opacity).toBe('1');
    expect(b.style.transform).toBe('translate(600px, 250px) translateY(-50%)');
    expect(c.style.opacity).toBe('0');
  });

  it('skips DOM writes for labels whose rounded position did not change', () => {
    const root = document.createElement('div');
    root.append(document.createElement('span'));
    const labels: SceneLabel[] = [{ id: 'a', text: 'Library 3', tone: 'pile', obj: null, x: 0, y: 0, z: 0, align: 'center' }];
    const point = { x: 0, y: 0, visible: false };
    positionLabels(root, labels, camera(), { width: 800, height: 500 }, () => null, point);
    const node = root.children[0] as HTMLElement;
    expect(node.style.transform).toBe('translate(400px, 250px) translateX(-50%)');
    // Same frame again: nothing is rebuilt or rewritten (a marker survives).
    node.style.transform = 'translate(1px, 1px)';
    positionLabels(root, labels, camera(), { width: 800, height: 500 }, () => null, point);
    expect(node.style.transform).toBe('translate(1px, 1px)');
    // A real move rewrites it.
    positionLabels(root, labels, camera(), { width: 1000, height: 500 }, () => null, point);
    expect(node.style.transform).toBe('translate(500px, 250px) translateX(-50%)');
  });

  it('hides a table label a hand card covers, never the hand card label itself', () => {
    // A hand card lifted toward the camera over the point (0, 0) of the table.
    const hand = new Object3D();
    hand.position.set(0, 0, 1);
    const layout = { cards: [{ obj: 'h1', zone: 'hand' }, { obj: 'b1', zone: 'battlefield' }] } as unknown as Layout;
    const registry = { object: (obj: string) => (obj === 'h1' ? hand : null) };
    const occluders = handOccluders(layout, registry, camera(), 800, 500);
    expect(occluders.map((o) => o.obj)).toEqual(['h1']);
    const root = document.createElement('div');
    root.append(document.createElement('span'), document.createElement('span'), document.createElement('span'));
    const labels: SceneLabel[] = [
      { id: 'under', text: '×2', tone: 'pile', obj: 'b1', x: 0.1, y: 0.1, z: 0, align: 'center' },
      { id: 'clear', text: '1/1', tone: 'stat', obj: 'b2', x: CARD_WIDTH, y: CARD_HEIGHT, z: 0, align: 'center' },
      { id: 'own', text: 'From exile', tone: 'castable', obj: 'h1', x: 0, y: 0, z: 0, align: 'center' },
    ];
    const poses = (obj: string) => (obj === 'h1' ? { x: 0, y: 0, z: 1 } : { x: 0, y: 0, z: 0 });
    positionLabels(root, labels, camera(), { width: 800, height: 500 }, poses, { x: 0, y: 0, visible: false }, () => 1, occluders);
    const [under, clear, own] = Array.from(root.children) as HTMLElement[];
    expect(under.style.opacity).toBe('0');
    expect(clear.style.opacity).toBe('1');
    expect(own.style.opacity).toBe('1');
  });

  it('never hides a label in front of the card', () => {
    const behind = new Object3D();
    behind.position.set(0, 0, -1);
    const layout = { cards: [{ obj: 'h1', zone: 'hand' }] } as unknown as Layout;
    const occluders = handOccluders(layout, { object: () => behind }, camera(), 800, 500);
    const p = projectToScreen(camera(), 0, 0, 0, 800, 500, { x: 0, y: 0, visible: false });
    expect(isCovered(p.x, p.y, p.depth ?? 0, 'b1', occluders)).toBe(false);
  });
});
