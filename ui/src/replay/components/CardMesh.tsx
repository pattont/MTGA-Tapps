/**
 * One card on the table: front and back planes (single-sided, so no
 * z-fighting), optional highlight ring and dashed "inferred" outline, and a
 * soft shadow on the felt. Position and rotation are owned by the motion
 * registry; React only updates the target.
 */
import type { ThreeEvent } from '@react-three/fiber';
import { useThree } from '@react-three/fiber';
import { memo, useLayoutEffect, useRef, useSyncExternalStore } from 'react';
import type { Group, Material, Mesh } from 'three';
import type { CardPlacement } from '../layout';
import type { SleeveColor } from '../prefs';
import type { SceneKit } from '../scene/kit';
import type { MotionRegistry } from '../scene/motionRegistry';
import type { Pose } from '../scene/motion';
import { isUnknownCard } from '../scene/textureStore';
import type { TextureStore } from '../scene/textureStore';
import type { CardKey, ReplayCard } from '../types';

export interface CardHandlers {
  over(placement: CardPlacement, x: number, y: number): void;
  out(placement: CardPlacement): void;
  click(placement: CardPlacement): void;
}

interface CardMeshProps {
  placement: CardPlacement;
  cardInfo: ReplayCard | undefined;
  sleeve: SleeveColor;
  store: TextureStore;
  kit: SceneKit;
  registry: MotionRegistry;
  spawn: (placement: CardPlacement) => Pose | null;
  handlers: CardHandlers;
}

const noRaycast = () => null;

function useFace(store: TextureStore, key: CardKey | null) {
  return useSyncExternalStore(store.subscribe, () => store.face(key));
}

function CardMeshImpl({ placement, cardInfo, sleeve, store, kit, registry, spawn, handlers }: CardMeshProps) {
  const group = useRef<Group>(null);
  const shadow = useRef<Mesh>(null);
  const invalidate = useThree((s) => s.invalidate);
  const face = useFace(store, placement.card);
  const { obj, x, y, z, rotZ, rotY, scale } = placement;

  useLayoutEffect(() => {
    const node = group.current;
    if (!node) return;
    const target = { x, y, z, rotZ, rotY, scale };
    const start = registry.pose(obj) ? null : spawn(placement);
    registry.set(obj, node, shadow.current, target, start);
    invalidate();
    // Only the pose fields matter; `placement` is a fresh object every layout.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [obj, x, y, z, rotZ, rotY, scale, registry, invalidate]);

  useLayoutEffect(() => {
    const node = group.current;
    return () => {
      if (node) registry.remove(obj, node);
    };
  }, [obj, registry]);

  const back: Material = store.cardMaterial(store.sleeve(sleeve));
  let front: Material = back;
  if (placement.card !== null) {
    if (isUnknownCard(placement.card, cardInfo)) front = store.cardMaterial(store.unknown(sleeve));
    else front = face ? store.cardMaterial(face) : kit.blankMaterial;
  }

  const onOver = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    handlers.over(placement, event.nativeEvent.clientX, event.nativeEvent.clientY);
  };
  const onOut = () => handlers.out(placement);
  const onClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    handlers.click(placement);
  };

  return (
    <>
      <group ref={group} onPointerOver={onOver} onPointerMove={onOver} onPointerOut={onOut} onClick={onClick}>
        <mesh geometry={kit.card} material={front} position-z={0.0008} />
        <mesh geometry={kit.card} material={back} position-z={-0.0008} rotation-y={Math.PI} />
        {placement.highlight ? (
          <mesh
            geometry={kit.ring}
            material={kit.ringMaterials[placement.highlight]}
            position-z={-0.003}
            raycast={noRaycast}
            renderOrder={1}
          />
        ) : null}
        {placement.castable ? (
          <mesh
            geometry={kit.ring}
            material={placement.castable === 'plot' ? kit.plotMaterial : kit.castableMaterial}
            position-z={-0.0025}
            raycast={noRaycast}
          />
        ) : null}
        {placement.removed && placement.zone === 'battlefield' ? (
          <mesh geometry={kit.card} material={kit.removedMaterial} position-z={0.0016} raycast={noRaycast} />
        ) : null}
        {placement.inferred ? (
          <mesh geometry={kit.inferred} material={kit.inferredMaterial} position-z={-0.002} raycast={noRaycast} />
        ) : null}
      </group>
      <mesh ref={shadow} geometry={kit.shadow} material={kit.shadowMaterial} raycast={noRaycast} />
    </>
  );
}

function samePlacement(a: CardPlacement, b: CardPlacement): boolean {
  return (
    a.obj === b.obj &&
    a.card === b.card &&
    a.faceUp === b.faceUp &&
    a.x === b.x &&
    a.y === b.y &&
    a.z === b.z &&
    a.rotZ === b.rotZ &&
    a.rotY === b.rotY &&
    a.scale === b.scale &&
    a.highlight === b.highlight &&
    a.inferred === b.inferred &&
    a.castable === b.castable &&
    a.removed === b.removed &&
    a.seat === b.seat &&
    sameUnder(a.under, b.under)
  );
}

function sameUnder(a: CardPlacement['under'], b: CardPlacement['under']): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  return a.every((u, i) => u.obj === b[i].obj && u.card === b[i].card && u.zone === b[i].zone);
}

export const CardMesh = memo(
  CardMeshImpl,
  (prev, next) =>
    samePlacement(prev.placement, next.placement) &&
    prev.cardInfo === next.cardInfo &&
    prev.sleeve === next.sleeve &&
    prev.store === next.store &&
    prev.kit === next.kit &&
    prev.registry === next.registry &&
    prev.spawn === next.spawn &&
    prev.handlers === next.handlers,
);
