/**
 * Gathers everything one exported frame needs (frameComposer.FrameInput)
 * from the live board: labels and arrow ends projected through the camera
 * at the cards' animated poses, the stack column with its art, the HUD
 * values, the current action as a caption and the ending. Pure apart from
 * reading the registry's poses.
 */
import type { Camera } from 'three';
import { formatCardName } from '../../format';
import { describeGameEnd } from '../gameEnd';
import type { Layout } from '../layout';
import { activeItemIndex, eventActor, formatClock, phaseLabel, stripClock } from '../logText';
import type { LogItem } from '../logText';
import type { PlaybackClock } from '../player';
import type { ReplayPrefs } from '../prefs';
import type { BoardState } from '../reducer';
import { sceneArrows, seatAnchor, sleeveNeon } from '../scene/arrows';
import type { ArrowEnd } from '../scene/arrows';
import { sceneLabels, seatNumber } from '../scene/labels';
import type { MotionRegistry } from '../scene/motionRegistry';
import { projectToScreen } from '../scene/projection';
import type { ScreenPoint } from '../scene/projection';
import { STACK_KIND_LABELS, effectExits, stackView } from '../scene/stackView';
import type { TextureStore } from '../scene/textureStore';
import type { CardKey, ReplayCard, ReplayStream } from '../types';
import type { FrameArrow, FrameArrowEnd, FrameInput, FrameLabel, FrameLayout, FrameSeat, FrameStackItem } from './frameComposer';

/** The live objects a frame is read from. */
export interface FrameSource {
  stream: ReplayStream;
  clock: PlaybackClock;
  cards: Readonly<Record<CardKey, ReplayCard>>;
  store: TextureStore;
  registry: MotionRegistry;
  prefs: ReplayPrefs;
  layout: Layout;
  state: BoardState;
  /** The action log rows (buildLogItems) when the video has a log column; null for a caption instead. */
  logItems: readonly LogItem[] | null;
}

function imageOf(texture: { image?: unknown } | null): CanvasImageSource | null {
  const image = texture?.image;
  if (!image) return null;
  if (typeof HTMLImageElement !== 'undefined' && image instanceof HTMLImageElement) return image.complete ? image : null;
  if (typeof HTMLCanvasElement !== 'undefined' && image instanceof HTMLCanvasElement) return image;
  if (typeof ImageBitmap !== 'undefined' && image instanceof ImageBitmap) return image;
  return null;
}

/** Everything the composer needs for the current board, projected through `camera`. */
export function buildFrameInput(
  props: FrameSource,
  camera: Camera,
  scene: CanvasImageSource,
  layout: FrameLayout,
  point: ScreenPoint,
): FrameInput {
  const { stream, cards, store, registry, state, prefs, clock } = props;
  const board = props.layout;
  const playerSeat = stream.player_seat;
  const w = layout.sceneWidth;
  const h = layout.sceneHeight;

  const labels: FrameLabel[] = [];
  for (const label of sceneLabels(board, cards)) {
    let { x, y, z } = label;
    if (label.obj) {
      const pose = registry.pose(label.obj);
      if (!pose) continue;
      x += pose.x;
      y = y * registry.stretchOf(label.obj) + pose.y;
      z += pose.z;
    }
    const p = projectToScreen(camera, x, y, z, w, h, point);
    if (!p.visible) continue;
    labels.push({ x: p.x, y: p.y, text: label.text, tone: label.tone, emphasis: label.emphasis });
  }

  const stackItem = (item: ReturnType<typeof stackView>[number]): FrameStackItem => ({
    stackId: item.stackId,
    image: imageOf(store.face(item.card)),
    name: formatCardName(item.name),
    who: item.controller === playerSeat ? 'You' : 'Opponent',
    kind: STACK_KIND_LABELS[item.kind],
    top: item.top,
    mine: item.controller === playerSeat,
  });
  // The live stack, then the items kept for the current action (stamped).
  const stack: FrameStackItem[] = [
    ...stackView(state).map(stackItem),
    ...effectExits(state).map((item) => ({ ...stackItem(item), exit: item.exit })),
  ];

  const neon = { player: sleeveNeon(prefs.playerSleeve), opponent: sleeveNeon(prefs.opponentSleeve) };
  const endOf = (end: ArrowEnd): FrameArrowEnd | null => {
    if (end.kind === 'stack') return { stackId: end.stackId };
    let x: number;
    let y: number;
    let z: number;
    if (end.kind === 'obj') {
      const pose = registry.pose(end.obj);
      if (!pose) return null;
      ({ x, y, z } = pose);
    } else {
      const anchor = seatAnchor(board, end.seat, playerSeat);
      ({ x, y, z } = anchor);
    }
    const p = projectToScreen(camera, x, y, z, w, h, point);
    return p.visible ? { x: p.x, y: p.y } : null;
  };
  const arrows: FrameArrow[] = [];
  for (const arrow of sceneArrows(state, board)) {
    const from = endOf(arrow.from);
    const to = endOf(arrow.to);
    if (!from || !to) continue;
    const colors = arrow.seat === playerSeat ? neon.player : neon.opponent;
    arrows.push({ from, to, glow: colors.glow, core: colors.core, reticle: arrow.to.kind === 'seat' });
  }

  const event = stream.events[clock.snapshot.index];
  const seatInfo = (seat: number): FrameSeat => {
    const info = stream.seats[String(seat)];
    return {
      name: seat === playerSeat ? 'You' : info?.name || 'Opponent',
      life: state.life[seat] ?? info?.starting_life ?? 20,
      hand: state.seats[seat]?.handSize ?? 0,
      library: state.seats[seat]?.librarySize ?? 0,
      active: state.activeSeat === seat,
      change: (() => {
        const marks = state.effects.seats.get(seat);
        const number = marks ? seatNumber(marks) : null;
        return number ? { text: number.text, loss: number.tone === 'life-loss' } : null;
      })(),
    };
  };
  const opponentSeat = Object.keys(stream.seats)
    .map(Number)
    .find((seat) => seat !== playerSeat);
  const phase =
    phaseLabel(state.step) && phaseLabel(state.phase)
      ? `${phaseLabel(state.phase)} – ${phaseLabel(state.step)}`
      : phaseLabel(state.phase);
  const hud = {
    turn: state.turn > 0 ? `Turn ${state.turn}` : 'Pre-game',
    whose: state.activeSeat === null ? null : state.activeSeat === playerSeat ? 'Your turn' : "Opponent's turn",
    whoseIsPlayer: state.activeSeat === playerSeat,
    phase,
    clock: formatClock(event?.t ?? 0),
    you: seatInfo(playerSeat),
    opponent: seatInfo(opponentSeat ?? playerSeat),
  };
  const log = props.logItems ? { items: props.logItems, activeIndex: activeItemIndex(props.logItems, event?.seq ?? -1), playerSeat } : null;
  const caption = !log && event?.log?.text ? { text: stripClock(event.log.text), actor: eventActor(event, playerSeat) } : null;
  let ending: FrameInput['ending'] = null;
  if (state.ended) {
    const summary = describeGameEnd(stream, state);
    const result = summary.result === 'win' || summary.result === 'loss' || summary.result === 'draw' ? summary.result : 'unknown';
    ending = { headline: summary.headline, reason: summary.reason, result };
  }
  return { scene, hud, labels, stack, arrows, caption, log, ending, colors: { player: neon.player.glow, opponent: neon.opponent.glow } };
}

