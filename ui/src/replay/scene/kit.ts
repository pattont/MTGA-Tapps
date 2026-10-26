/**
 * Geometries and materials shared by every mesh in one scene. Created once
 * per page; materials that depend on preferences come from the texture store
 * caches, so switching colors never rebuilds meshes.
 */
import {
  AdditiveBlending,
  BoxGeometry,
  CanvasTexture,
  Color,
  DoubleSide,
  MeshBasicMaterial,
  MeshLambertMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
} from 'three';
import type { Material } from 'three';
import { CARD_HEIGHT, CARD_WIDTH } from '../layout';
import type { PlacementHighlight } from '../layout';
import { createVignetteCanvas } from './sceneCanvases';
import type { TextureStore } from './textureStore';

/** Teal used for replay affordances (matches the --replay dark token). */
export const REPLAY_TEAL = '#2bb3a3';
/** Brighter teal for glows on the green felt, where the token teal has too little contrast. */
const ATTACK_GLOW = '#4ff0da';

export const HIGHLIGHT_COLORS: Record<Exclude<PlacementHighlight, null>, string> = {
  attacking: ATTACK_GLOW,
  blocking: '#e8b84e',
  targeted: '#f2994a',
  damaged: '#ff5a4f',
};

/** Side cards beside the hand: a dashed outline for graveyard casts, a gold glow for plotted cards. */
export const CASTABLE_COLORS = { graveyard: '#9fd0ff', plot: '#f2c14e' } as const;

export interface SceneKit {
  card: PlaneGeometry;
  shadow: PlaneGeometry;
  ring: PlaneGeometry;
  inferred: PlaneGeometry;
  pile: BoxGeometry;
  /** Unit plane and box: the table is scaled to the stage-dependent felt size. */
  unitPlane: PlaneGeometry;
  unitBox: BoxGeometry;
  vignetteMaterial: MeshBasicMaterial;
  shadowMaterial: MeshBasicMaterial;
  /** A hovering (flying) card's shadow: darker, since it falls clear of the card. */
  hoverShadowMaterial: MeshBasicMaterial;
  ringMaterials: Record<Exclude<PlacementHighlight, null>, MeshBasicMaterial>;
  inferredMaterial: MeshBasicMaterial;
  /** Dims a card the current action removed (held in its slot until the action ends). */
  removedMaterial: MeshBasicMaterial;
  castableMaterial: MeshBasicMaterial;
  plotMaterial: MeshBasicMaterial;
  slotMaterial: MeshBasicMaterial;
  blankMaterial: MeshBasicMaterial;
  edgeMaterial: MeshLambertMaterial;
  railMaterial: MeshStandardMaterial;
  setDamageOpacity(opacity: number): void;
  dispose(): void;
}

export function createSceneKit(store: TextureStore): SceneKit {
  const card = new PlaneGeometry(CARD_WIDTH, CARD_HEIGHT);
  const shadow = new PlaneGeometry(CARD_WIDTH * 1.68, CARD_HEIGHT * 1.6);
  const ring = new PlaneGeometry(CARD_WIDTH * 1.24, CARD_HEIGHT * 1.17);
  // Taller than the card: the "inferred" tag hangs below the bottom edge.
  const inferred = new PlaneGeometry(CARD_WIDTH * 1.11, CARD_HEIGHT * 1.25);
  inferred.translate(0, -CARD_HEIGHT * 0.09, 0);
  const pile = new BoxGeometry(CARD_WIDTH, CARD_HEIGHT, 1);
  pile.translate(0, 0, 0.5);
  const unitPlane = new PlaneGeometry(1, 1);
  const unitBox = new BoxGeometry(1, 1, 1);
  const vignette = new CanvasTexture(createVignetteCanvas());
  const vignetteMaterial = new MeshBasicMaterial({
    color: new Color('#000000'),
    alphaMap: vignette,
    transparent: true,
    depthWrite: false,
  });

  const overlay = (color: string, map = store.helper('ring')) =>
    new MeshBasicMaterial({ map, color: new Color(color), transparent: true, depthWrite: false, side: DoubleSide });
  // Rings are light: added to the felt under them, never painted over it.
  const glow = (color: string) => {
    const material = overlay(color);
    material.blending = AdditiveBlending;
    return material;
  };
  const ringMaterials = {
    attacking: glow(HIGHLIGHT_COLORS.attacking),
    blocking: glow(HIGHLIGHT_COLORS.blocking),
    targeted: glow(HIGHLIGHT_COLORS.targeted),
    damaged: glow(HIGHLIGHT_COLORS.damaged),
  };
  const inferredMaterial = overlay('#ffffff', store.helper('inferred'));
  const removedMaterial = new MeshBasicMaterial({
    color: new Color('#05080c'),
    alphaMap: store.helper('alpha'),
    transparent: true,
    opacity: 0.55,
    depthWrite: false,
  });
  const castableMaterial = overlay(CASTABLE_COLORS.graveyard, store.helper('castable'));
  const plotMaterial = glow(CASTABLE_COLORS.plot);
  const slotMaterial = new MeshBasicMaterial({ map: store.helper('slot'), transparent: true, depthWrite: false });
  const shadowMaterial = new MeshBasicMaterial({
    map: store.helper('shadow'),
    transparent: true,
    depthWrite: false,
    opacity: 0.7,
  });
  const hoverShadowMaterial = new MeshBasicMaterial({
    map: store.helper('hoverShadow'),
    transparent: true,
    depthWrite: false,
  });
  const blankMaterial = new MeshBasicMaterial({
    color: new Color('#8f897d'),
    alphaMap: store.helper('alpha'),
    alphaTest: 0.5,
  });
  const edgeMaterial = new MeshLambertMaterial({ color: new Color('#cfc8b8') });
  const railMaterial = new MeshStandardMaterial({ color: new Color('#2a1c12'), roughness: 0.5, metalness: 0.12 });

  const materials: Material[] = [
    ...Object.values(ringMaterials),
    inferredMaterial,
    removedMaterial,
    castableMaterial,
    plotMaterial,
    slotMaterial,
    shadowMaterial,
    hoverShadowMaterial,
    blankMaterial,
    edgeMaterial,
    railMaterial,
    vignetteMaterial,
  ];
  return {
    card,
    shadow,
    ring,
    inferred,
    pile,
    unitPlane,
    unitBox,
    vignetteMaterial,
    shadowMaterial,
    hoverShadowMaterial,
    ringMaterials,
    inferredMaterial,
    removedMaterial,
    castableMaterial,
    plotMaterial,
    slotMaterial,
    blankMaterial,
    edgeMaterial,
    railMaterial,
    setDamageOpacity(opacity: number) {
      ringMaterials.damaged.opacity = opacity;
    },
    dispose() {
      for (const geometry of [card, shadow, ring, inferred, pile, unitPlane, unitBox]) geometry.dispose();
      for (const material of materials) material.dispose();
      vignette.dispose();
    },
  };
}
