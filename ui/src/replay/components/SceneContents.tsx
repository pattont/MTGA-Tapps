/**
 * Everything inside the R3F canvas: table, lights, cards, piles, the camera
 * rig, the single animation loop and the DOM label and arrow projectors.
 */
import { useFrame, useThree } from '@react-three/fiber';
import { useLayoutEffect, useMemo, useRef } from 'react';
import type { RefObject } from 'react';
import { CARD_HEIGHT, CARD_WIDTH, PILE_CARD_DEPTH, PILE_MAX_CARDS } from '../layout';
import type { CardPlacement, Layout, PilePlacement, TableGeometry } from '../layout';
import type { ReplayPrefs, SleeveColor } from '../prefs';
import type { BoardState } from '../reducer';
import { seatAnchor } from '../scene/arrows';
import type { ArrowEnd, SceneArrow } from '../scene/arrows';
import { RAIL_WIDTH } from '../scene/cameraFit';
import type { SceneKit } from '../scene/kit';
import type { SceneLabel } from '../scene/labels';
import type { Pose } from '../scene/motion';
import { spawnPose } from '../scene/motion';
import type { MotionRegistry } from '../scene/motionRegistry';
import { handOccluders, positionArrows, positionLabels } from '../scene/projection';
import type { ScreenOccluder, ScreenPoint } from '../scene/projection';
import type { TextureStore } from '../scene/textureStore';
import type { CardKey, ReplayCard } from '../types';
import type { ViewZoom } from '../scene/viewZoom';
import { CameraRig } from './CameraRig';
import { CardMesh } from './CardMesh';
import type { CardHandlers } from './CardMesh';

const DAMAGE_FLASH_MS = 700;

export interface SceneContentsProps {
  layout: Layout;
  state: BoardState;
  prefs: ReplayPrefs;
  cards: Readonly<Record<CardKey, ReplayCard>>;
  store: TextureStore;
  kit: SceneKit;
  registry: MotionRegistry;
  labels: readonly SceneLabel[];
  labelRoot: RefObject<HTMLDivElement | null>;
  arrows: readonly SceneArrow[];
  arrowRoot: RefObject<SVGGElement | null>;
  /** The DOM stack preview layer and its cards by stack id (arrow sources). */
  stackRoot: RefObject<HTMLDivElement | null>;
  stackNodes: ReadonlyMap<string, HTMLElement>;
  handlers: CardHandlers;
  snap: boolean;
  /** Wheel zoom and drag pan of the fitted view. */
  zoom: ViewZoom;
}

/** Felt, wooden base and rails, scaled to the stage-dependent felt size. */
function Table({ store, felt, kit, table }: { store: TextureStore; felt: ReplayPrefs['felt']; kit: SceneKit; table: TableGeometry }) {
  const invalidate = useThree((s) => s.invalidate);
  const { width, depth } = table;
  useLayoutEffect(() => {
    // One felt tile per ~2.4 units, so the weave keeps its size as the table widens.
    store.felt(felt).repeat.set(width / 2.4, depth / 2.4);
    invalidate();
  }, [felt, width, depth, store, invalidate]);
  const outerW = width + RAIL_WIDTH * 2;
  const outerD = depth + RAIL_WIDTH * 2;
  const railX = width / 2 + RAIL_WIDTH / 2;
  const railY = depth / 2 + RAIL_WIDTH / 2;
  return (
    <group>
      <mesh geometry={kit.unitPlane} material={store.feltMaterial(felt)} scale={[width, depth, 1]} />
      <mesh geometry={kit.unitPlane} material={kit.vignetteMaterial} scale={[width, depth, 1]} position-z={0.001} renderOrder={-1} />
      <mesh geometry={kit.unitBox} material={kit.railMaterial} position-z={-0.085} scale={[outerW + 0.16, outerD + 0.16, 0.16]} />
      <mesh geometry={kit.unitBox} material={kit.railMaterial} position={[0, railY, 0.045]} scale={[outerW, RAIL_WIDTH, 0.09]} />
      <mesh geometry={kit.unitBox} material={kit.railMaterial} position={[0, -railY, 0.045]} scale={[outerW, RAIL_WIDTH, 0.09]} />
      <mesh geometry={kit.unitBox} material={kit.railMaterial} position={[railX, 0, 0.045]} scale={[RAIL_WIDTH, depth, 0.09]} />
      <mesh geometry={kit.unitBox} material={kit.railMaterial} position={[-railX, 0, 0.045]} scale={[RAIL_WIDTH, depth, 0.09]} />
    </group>
  );
}

function Pile({ pile, sleeve, store, kit }: { pile: PilePlacement; sleeve: SleeveColor; store: TextureStore; kit: SceneKit }) {
  if (pile.count === 0) {
    // Command zones exist only in commander formats (see usesCommandZone); an
    // empty one keeps its slot so the viewer sees the commander is out.
    return (
      <mesh
        geometry={kit.unitPlane}
        position={[pile.x, pile.y, 0.002]}
        scale={[CARD_WIDTH * pile.scale, CARD_HEIGHT * pile.scale, 1]}
        material={kit.slotMaterial}
      />
    );
  }
  const height = Math.max(PILE_CARD_DEPTH, Math.min(pile.count, PILE_MAX_CARDS) * PILE_CARD_DEPTH);
  const library = pile.zone === 'library';
  const faceTop = library ? store.pileTopMaterial(sleeve) : kit.edgeMaterial;
  const materials = [kit.edgeMaterial, kit.edgeMaterial, kit.edgeMaterial, kit.edgeMaterial, faceTop, kit.edgeMaterial];
  return (
    <mesh
      geometry={kit.pile}
      material={materials}
      position={[pile.x, pile.y, 0]}
      rotation-z={pile.rotZ}
      scale={[pile.scale, pile.scale, height]}
    />
  );
}

/** Seek jumps place cards instantly; set before the cards' own layout effects run. */
function SnapMode({ registry, snap }: { registry: MotionRegistry; snap: boolean }) {
  useLayoutEffect(() => {
    registry.setSnap(snap);
  });
  return null;
}

/** Steps every card toward its target and keeps frames coming only while needed. */
function Animator({ registry, kit, layout }: { registry: MotionRegistry; kit: SceneKit; layout: Layout }) {
  const busy = useRef(false);
  const flashStart = useRef(-Infinity);
  const invalidate = useThree((s) => s.invalidate);
  const damaged = layout.cards.some((card) => card.highlight === 'damaged');
  useLayoutEffect(() => {
    if (!damaged) return;
    flashStart.current = performance.now();
    kit.setDamageOpacity(1);
    invalidate();
  }, [damaged, layout, kit, invalidate]);
  useFrame((state, delta) => {
    // The cards' depth stretch follows the camera (a preset transition or a
    // refit moves it); the extra frame makes sure the final pose is seen.
    const camera = state.camera;
    const viewer = 'isPerspectiveCamera' in camera && camera.isPerspectiveCamera ? camera.position : null;
    let more = registry.setViewer(viewer);
    // The first frame after idle carries the whole idle gap as its delta.
    more = registry.step(busy.current ? delta : 1 / 60) || more;
    busy.current = registry.busy;
    const t = (performance.now() - flashStart.current) / DAMAGE_FLASH_MS;
    if (t >= 0 && t <= 1.05) {
      kit.setDamageOpacity(1 - 0.6 * Math.min(1, t));
      more = more || t < 1;
    }
    if (more) state.invalidate();
  });
  return null;
}

/** Writes label transforms straight into the DOM on rendered frames (no React). */
function LabelProjector({
  labels,
  root,
  registry,
  layout,
}: {
  labels: readonly SceneLabel[];
  root: RefObject<HTMLDivElement | null>;
  registry: MotionRegistry;
  layout: Layout;
}) {
  const invalidate = useThree((s) => s.invalidate);
  const point = useRef<ScreenPoint>({ x: 0, y: 0, visible: false });
  const occluders = useRef<ScreenOccluder[]>([]);
  useLayoutEffect(() => invalidate(), [labels, invalidate]);
  useFrame((state) => {
    if (root.current) {
      // Labels are DOM over the canvas: hide the ones a hand card covers.
      handOccluders(layout, registry, state.camera, state.size.width, state.size.height, occluders.current);
      positionLabels(
        root.current,
        labels,
        state.camera,
        state.size,
        (obj) => registry.pose(obj),
        point.current,
        (obj) => registry.stretchOf(obj),
        occluders.current,
      );
    }
  });
  return null;
}

/** Moves the SVG targeting arrows on rendered frames (no React). */
function ArrowProjector({
  arrows,
  root,
  stackRoot,
  stackNodes,
  registry,
  layout,
  playerSeat,
}: {
  arrows: readonly SceneArrow[];
  root: RefObject<SVGGElement | null>;
  stackRoot: RefObject<HTMLDivElement | null>;
  stackNodes: ReadonlyMap<string, HTMLElement>;
  registry: MotionRegistry;
  layout: Layout;
  playerSeat: number;
}) {
  const invalidate = useThree((s) => s.invalidate);
  useLayoutEffect(() => invalidate(), [arrows, invalidate]);
  // Stable callbacks reading the latest layout, so frames allocate nothing.
  const latest = useRef({ layout, playerSeat });
  useLayoutEffect(() => {
    latest.current = { layout, playerSeat };
  });
  const ends = useMemo(() => {
    const seatPoint = { x: 0, y: 0, z: 0 };
    const objPoint = { x: 0, y: 0, z: 0 };
    return {
      world(end: ArrowEnd) {
        if (end.kind === 'seat') return seatAnchor(latest.current.layout, end.seat, latest.current.playerSeat, seatPoint);
        if (end.kind !== 'obj') return null;
        const pose = registry.pose(end.obj);
        if (!pose) return null;
        objPoint.x = pose.x;
        objPoint.y = pose.y;
        objPoint.z = pose.z + 0.02;
        return objPoint;
      },
      dom(stackId: string, out: ScreenPoint) {
        const layer = stackRoot.current;
        const node = stackNodes.get(stackId);
        const parent = node?.offsetParent;
        const stage = layer?.offsetParent;
        if (!layer || !node || !node.isConnected || !parent || !stage) return false;
        // The card's own offsets ignore its enter transform, so the arrow aims at
        // where it lands; its container is measured as drawn, since the stack
        // column is centered on the stage and the kept cards beside it are
        // translated (offsets alone put the start far above a short stack).
        const box = parent.getBoundingClientRect();
        const origin = stage.getBoundingClientRect();
        out.x = box.left - origin.left + node.offsetLeft + 4;
        out.y = box.top - origin.top + node.offsetTop + Math.min(node.offsetHeight * 0.38, 120);
        out.visible = true;
        return true;
      },
    };
  }, [registry, stackRoot, stackNodes]);
  useFrame((state) => {
    if (root.current) positionArrows(root.current, arrows, state.camera, state.size, ends.world, ends.dom);
  });
  return null;
}

function Anisotropy({ store }: { store: TextureStore }) {
  const gl = useThree((s) => s.gl);
  useLayoutEffect(() => {
    store.setAnisotropy(Math.min(8, gl.capabilities.getMaxAnisotropy()));
  }, [gl, store]);
  return null;
}

export function SceneContents(props: SceneContentsProps) {
  const { layout, state, prefs, cards, store, kit, registry, labels, labelRoot, arrows, arrowRoot, stackRoot, stackNodes, handlers, snap } =
    props;
  const latest = useRef({ state, layout });
  useLayoutEffect(() => {
    latest.current = { state, layout };
  });
  // Stable so memoized cards do not re-render; reads the newest board when a card first appears.
  const spawn = useMemo(
    () =>
      (placement: CardPlacement): Pose | null =>
        registry.snap
          ? null
          : spawnPose(placement, latest.current.state, latest.current.layout, (obj) => registry.pose(obj)),
    [registry],
  );
  const sleeveOf = (seat: number): SleeveColor =>
    seat === state.playerSeat ? prefs.playerSleeve : prefs.opponentSleeve;

  return (
    <>
      <SnapMode registry={registry} snap={snap} />
      <ambientLight intensity={1.1} />
      <directionalLight position={[-5, -7, 14]} intensity={2.2} />
      <CameraRig preset={prefs.camera} table={layout.table} zoom={props.zoom} />
      <Anisotropy store={store} />
      <Table store={store} felt={prefs.felt} kit={kit} table={layout.table} />
      {layout.piles.map((pile) => (
        <Pile key={`${pile.seat}:${pile.zone}`} pile={pile} sleeve={sleeveOf(pile.seat)} store={store} kit={kit} />
      ))}
      {layout.cards.map((placement) => (
        <CardMesh
          key={placement.obj}
          placement={placement}
          cardInfo={placement.card ? cards[placement.card] : undefined}
          sleeve={sleeveOf(placement.seat)}
          store={store}
          kit={kit}
          registry={registry}
          spawn={spawn}
          handlers={handlers}
        />
      ))}
      <Animator registry={registry} kit={kit} layout={layout} />
      <LabelProjector labels={labels} root={labelRoot} registry={registry} layout={layout} />
      <ArrowProjector
        arrows={arrows}
        root={arrowRoot}
        stackRoot={stackRoot}
        stackNodes={stackNodes}
        registry={registry}
        layout={layout}
        playerSeat={state.playerSeat}
      />
    </>
  );
}
