/**
 * The WebGL table (React Three Fiber, demand-driven frame loop) plus its DOM
 * overlays: projected labels, targeting arrows (SVG) and the stack preview.
 * Measures the stage so the table's width can follow its aspect.
 */
import { Canvas } from '@react-three/fiber';
import { Component, memo, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import type { CardPlacement, Layout } from '../layout';
import type { ReplayPrefs } from '../prefs';
import type { BoardState } from '../reducer';
import { sceneArrows, sleeveNeon } from '../scene/arrows';
import { DEFAULT_MARGINS, fitTableForView } from '../scene/cameraFit';
import type { TableFit } from '../scene/cameraFit';
import { SICK_NOTE, type HoverStore } from '../scene/hoverStore';
import { createSceneKit } from '../scene/kit';
import { sceneLabels } from '../scene/labels';
import { MotionRegistry } from '../scene/motionRegistry';
import { isSupersampled, scenePixelRatio } from '../scene/pixelRatio';
import { isUnknownCard } from '../scene/textureStore';
import { WHEEL_ZOOM_RATE } from '../scene/viewZoom';
import type { ViewZoom } from '../scene/viewZoom';
import { supportsWebGL } from '../scene/webgl';
import type { TextureStore } from '../scene/textureStore';
import type { CardKey, ReplayCard } from '../types';
import type { CardHandlers } from './CardMesh';
import { ExportDriver } from './ExportDriver';
import type { ExportHandle } from './ExportDriver';
import { SceneContents } from './SceneContents';
import { StackPreview } from './StackPreview';

export interface ReplaySceneProps {
  layout: Layout;
  state: BoardState;
  prefs: ReplayPrefs;
  cards: Readonly<Record<CardKey, ReplayCard>>;
  store: TextureStore;
  hover: HoverStore;
  /** Wheel zoom and drag pan of the table (keyboard zoom is in useReplayKeyboard). */
  zoom: ViewZoom;
  /** True after a seek jump: cards move instantly instead of animating. */
  snap: boolean;
  /** Playback is running (paused: a resolved stack item is held on screen). */
  playing: boolean;
  onCardClick: (card: CardKey) => void;
  /** Reports the felt width and hand scale that fill the measured stage (see fitTableForView). */
  onTableFit?: (fit: TableFit) => void;
  /** A running video export (the scene renders its frames). */
  exportHandle?: ExportHandle | null;
}

function WebGLNotice({ detail }: { detail?: string }) {
  return (
    <div className="state-panel replay-webgl-notice" role="note">
      <strong>The 3D table needs WebGL.</strong> This browser could not start it, so the table cannot be drawn. The
      action log and the timeline still work. Try another browser or enable hardware acceleration.
      {detail ? <span className="replay-webgl-detail"> ({detail})</span> : null}
    </div>
  );
}

/** A WebGL context that fails after the probe (a lost GPU, a blocked renderer) must not blank the page. */
class SceneErrorBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
  state = { message: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  render() {
    if (this.state.message !== null) return <WebGLNotice detail={this.state.message} />;
    return this.props.children;
  }
}

/** Pointer travel (CSS px) before a press on a zoomed table becomes a pan instead of a click. */
const PAN_THRESHOLD_PX = 4;

/**
 * Wheel zoom toward the pointer and drag to pan while zoomed (the keyboard
 * zoom lives in useReplayKeyboard). A drag swallows the click that ends it, so panning never opens a
 * card. The stack preview and the zoom pill keep their own wheel and clicks.
 */
function useTableZoom(
  wrap: { current: HTMLDivElement | null },
  zoom: ViewZoom,
  hover: HoverStore,
  enabled: boolean,
): void {
  useEffect(() => {
    const node = wrap.current;
    if (!node || !enabled) return;
    const outside = (target: EventTarget | null) =>
      target instanceof Element && target.closest('.replay-stack-layer, .replay-zoom-pill') !== null;
    const size = () => node.getBoundingClientRect();

    const onWheel = (event: WheelEvent) => {
      if (outside(event.target) || event.ctrlKey) return;
      event.preventDefault();
      const rect = size();
      const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
      zoom.zoomAt(Math.exp(-delta * WHEEL_ZOOM_RATE), event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
    };

    let press: { id: number; x: number; y: number; panning: boolean } | null = null;
    let swallowClick = false;
    const onDown = (event: PointerEvent) => {
      swallowClick = false;
      if (event.button !== 0 || !zoom.zoomed || outside(event.target)) return;
      press = { id: event.pointerId, x: event.clientX, y: event.clientY, panning: false };
    };
    const onMove = (event: PointerEvent) => {
      if (!press || event.pointerId !== press.id) return;
      const dx = event.clientX - press.x;
      const dy = event.clientY - press.y;
      if (!press.panning) {
        if (Math.hypot(dx, dy) < PAN_THRESHOLD_PX) return;
        press.panning = true;
        node.setPointerCapture(event.pointerId);
        node.classList.add('is-panning');
        if (hover.get()?.source === 'scene') hover.set(null);
      }
      const rect = size();
      zoom.panBy(dx, dy, rect.width, rect.height);
      press.x = event.clientX;
      press.y = event.clientY;
    };
    const onUp = (event: PointerEvent) => {
      if (!press || event.pointerId !== press.id) return;
      if (press.panning) {
        swallowClick = true;
        node.classList.remove('is-panning');
        if (node.hasPointerCapture(event.pointerId)) node.releasePointerCapture(event.pointerId);
      }
      press = null;
    };
    const onClick = (event: MouseEvent) => {
      if (!swallowClick) return;
      swallowClick = false;
      event.stopPropagation();
      event.preventDefault();
    };

    node.addEventListener('wheel', onWheel, { passive: false });
    node.addEventListener('pointerdown', onDown);
    node.addEventListener('pointermove', onMove);
    node.addEventListener('pointerup', onUp);
    node.addEventListener('pointercancel', onUp);
    node.addEventListener('click', onClick, true);
    return () => {
      node.removeEventListener('wheel', onWheel);
      node.removeEventListener('pointerdown', onDown);
      node.removeEventListener('pointermove', onMove);
      node.removeEventListener('pointerup', onUp);
      node.removeEventListener('pointercancel', onUp);
      node.removeEventListener('click', onClick, true);
      node.classList.remove('is-panning');
    };
  }, [wrap, zoom, hover, enabled]);
}

function useZoomLevel(zoom: ViewZoom): number {
  return useSyncExternalStore(zoom.subscribe, () => zoom.zoom, () => 1);
}

function deviceRatio(): number {
  return typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1;
}

/** WebGL fixes MSAA at context creation: skip it when the table will be supersampled. */
function glOptions() {
  const width = typeof window === 'undefined' ? 0 : window.innerWidth;
  const height = typeof window === 'undefined' ? 0 : window.innerHeight;
  return { antialias: !isSupersampled(deviceRatio(), width, height), powerPreference: 'high-performance' } as const;
}

/** The table's pixel ratio, following the canvas size and the screen it is on (see pixelRatio.ts). */
function useScenePixelRatio(wrap: { current: HTMLDivElement | null }): number {
  const [ratio, setRatio] = useState(() => scenePixelRatio(deviceRatio(), 0, 0));
  useEffect(() => {
    const node = wrap.current;
    if (!node) return;
    const measure = () => {
      const { width, height } = node.getBoundingClientRect();
      setRatio(scenePixelRatio(deviceRatio(), width, height));
    };
    measure();
    // A move to another monitor changes devicePixelRatio and fires a window resize.
    window.addEventListener('resize', measure);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(node);
    return () => {
      window.removeEventListener('resize', measure);
      observer?.disconnect();
    };
  }, [wrap]);
  return ratio;
}

function sceneKey(placement: CardPlacement): string {
  return `scene:${placement.obj}`;
}

function ReplaySceneImpl({
  layout,
  state,
  prefs,
  cards,
  store,
  hover,
  zoom,
  snap,
  playing,
  onCardClick,
  onTableFit,
  exportHandle = null,
}: ReplaySceneProps) {
  const [webgl] = useState(() => supportsWebGL());
  const [registry] = useState(() => new MotionRegistry());
  const [stackNodes] = useState(() => new Map<string, HTMLElement>());
  const kit = useMemo(() => createSceneKit(store), [store]);
  useEffect(() => () => kit.dispose(), [kit]);
  const labels = useMemo(() => sceneLabels(layout, cards), [layout, cards]);
  const arrows = useMemo(() => sceneArrows(state, layout), [state, layout]);
  const labelRoot = useRef<HTMLDivElement>(null);
  const arrowRoot = useRef<SVGGElement>(null);
  const stackRoot = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [gl] = useState(glOptions);
  const dpr = useScenePixelRatio(wrap);
  const zoomLevel = useZoomLevel(zoom);
  const exporting = exportHandle !== null;
  useTableZoom(wrap, zoom, hover, webgl && !exporting);
  // A video always shows the whole table.
  useEffect(() => {
    if (exporting) zoom.reset();
  }, [exporting, zoom]);
  const click = useRef(onCardClick);
  useEffect(() => {
    click.current = onCardClick;
  }, [onCardClick]);
  const stableClick = useMemo(() => (card: CardKey) => click.current(card), []);

  // The felt and the hands follow the stage aspect: measure the stage, report the fit.
  const preset = prefs.camera;
  useEffect(() => {
    const node = wrap.current;
    if (!node || !onTableFit || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const { width, height } = node.getBoundingClientRect();
      if (width > 0 && height > 0) onTableFit(fitTableForView({ width, height }, DEFAULT_MARGINS, preset, undefined, window.devicePixelRatio));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [onTableFit, preset]);

  const handlers = useMemo<CardHandlers>(() => {
    const inspectable = (p: CardPlacement) => p.faceUp && p.card !== null && !isUnknownCard(p.card, cards[p.card]);
    return {
      over(p, x, y) {
        if (!inspectable(p) || !p.card) {
          hover.clear(sceneKey(p));
          return;
        }
        const under = p.under.length
          ? p.under.map((u) => ({ card: u.card, name: u.card ? (cards[u.card]?.name ?? '') : '', zone: u.zone }))
          : undefined;
        const note = p.sick ? SICK_NOTE : undefined;
        hover.set({ key: sceneKey(p), card: p.card, name: cards[p.card]?.name ?? '', under, note, x, y, source: 'scene' });
      },
      out(p) {
        hover.clear(sceneKey(p));
      },
      click(p) {
        if (inspectable(p) && p.card) click.current(p.card);
      },
    };
  }, [cards, hover]);

  useEffect(
    () =>
      hover.subscribe(() => {
        if (wrap.current) wrap.current.style.cursor = hover.get()?.source === 'scene' ? 'pointer' : '';
      }),
    [hover],
  );

  const colors = useMemo(
    () => ({ player: sleeveNeon(prefs.playerSleeve), opponent: sleeveNeon(prefs.opponentSleeve) }),
    [prefs.playerSleeve, prefs.opponentSleeve],
  );

  return (
    <div
      className={`replay-canvas-wrap${zoomLevel > 1 ? ' is-zoomed' : ''}`}
      ref={wrap}
      onPointerLeave={() => {
        if (hover.get()?.source === 'scene') hover.set(null);
      }}
    >
      {webgl ? (
        <SceneErrorBoundary>
          <Canvas
            className="replay-canvas"
            frameloop="demand"
            dpr={dpr}
            gl={gl}
            flat
            onPointerMissed={() => hover.set(null)}
          >
            <SceneContents
              layout={layout}
              state={state}
              prefs={prefs}
              cards={cards}
              store={store}
              kit={kit}
              registry={registry}
              labels={labels}
              labelRoot={labelRoot}
              arrows={arrows}
              arrowRoot={arrowRoot}
              stackRoot={stackRoot}
              stackNodes={stackNodes}
              handlers={handlers}
              snap={snap}
              zoom={zoom}
            />
            {exportHandle ? (
              <ExportDriver
                key={exportHandle.job.id}
                {...exportHandle}
                cards={cards}
                store={store}
                registry={registry}
                prefs={prefs}
                layout={layout}
                state={state}
              />
            ) : null}
          </Canvas>
        </SceneErrorBoundary>
      ) : (
        <WebGLNotice />
      )}
      {/* Arrows go under the labels, so a damage number always reads over them. */}
      <svg className={`replay-arrows${snap ? ' replay-arrows-snap' : ''}`} aria-hidden="true">
        <defs>
          <filter id="replay-arrow-blur" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>
        <g ref={arrowRoot}>
          {arrows.map((arrow) => {
            const neon = arrow.seat === state.playerSeat ? colors.player : colors.opponent;
            return (
              <g
                key={arrow.id}
                className={`replay-arrow replay-arrow-${arrow.tone}`}
                data-arrow={arrow.id}
                visibility="hidden"
                style={{ '--arrow-glow': neon.glow, '--arrow-core': neon.core } as CSSProperties}
              >
                <path data-part="glow" className="replay-arrow-glow" filter="url(#replay-arrow-blur)" />
                <path data-part="core" className="replay-arrow-core" />
                <path data-part="flow" className="replay-arrow-flow" />
                <polygon data-part="head" className="replay-arrow-head" />
                {arrow.to.kind === 'seat' ? <circle data-part="reticle" className="replay-arrow-reticle" r="9" /> : null}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="replay-labels" ref={labelRoot} aria-hidden="true">
        {labels.map((label) => (
          <span key={label.id} className={`replay-label replay-label-${label.tone}${label.emphasis ? ' replay-label-emphasis' : ''}`}>
            {label.text}
          </span>
        ))}
      </div>
      {zoomLevel > 1 ? (
        <button type="button" className="replay-zoom-pill" onClick={() => zoom.reset()} title="Show the whole table (0)">
          {zoomLevel.toFixed(1)}× · Reset zoom
        </button>
      ) : null}
      <div className="replay-stack-layer" ref={stackRoot}>
        <StackPreview
          state={state}
          playerSeat={state.playerSeat}
          store={store}
          snap={snap}
          playing={playing}
          nodes={stackNodes}
          onCardClick={stableClick}
        />
      </div>
    </div>
  );
}

export const ReplayScene = memo(ReplaySceneImpl);
export default ReplayScene;
