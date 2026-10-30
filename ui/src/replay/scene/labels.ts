/**
 * DOM labels drawn over the canvas: pile counts, and on every face-up
 * battlefield card a readable badge across its lower edge with the creature's
 * current power/toughness or the planeswalker's loyalty (Arena style), plus a
 * small chip across its upper edge for any other counters, or "Commander" on
 * a seat's commander (with its counters after it), or the basic land type a
 * land chose as it entered (Multiversal Passage), in that land's color, and a
 * purple sleep badge just above the top edge of a summoning-sick creature. Stack items are
 * captioned by the DOM stack preview instead. Pure: computed once per board
 * state; the projector moves them each rendered frame without React.
 */
import type { ObjectMarks, RemovalKind, SeatMarks } from '../effects';
import { CARD_HEIGHT, CARD_WIDTH, PILE_CARD_DEPTH, PILE_MAX_CARDS, TAPPED_ROTATION } from '../layout';
import type { CardPlacement, CastableMark, Layout, PileZone } from '../layout';
import type { CardKey, ReplayCard } from '../types';

export type LabelTone =
  | 'pile'
  | 'stat'
  | 'loyalty'
  | 'counters'
  | 'commander'
  | 'castable'
  | 'tucked'
  | 'sick'
  | 'damage'
  | 'removed'
  | 'buff'
  | 'debuff'
  | 'effect'
  | 'life-loss'
  | 'life-gain'
  | LandTypeTone;

/** A chosen basic land type's chip, in that land's mana color. */
export type LandTypeTone = 'land-plains' | 'land-island' | 'land-swamp' | 'land-mountain' | 'land-forest';

const LAND_TYPE_TONES: Record<string, LandTypeTone> = {
  Plains: 'land-plains',
  Island: 'land-island',
  Swamp: 'land-swamp',
  Mountain: 'land-mountain',
  Forest: 'land-forest',
};

export interface SceneLabel {
  id: string;
  text: string;
  tone: LabelTone;
  /** Follow this mesh's animated pose (offset by x/y/z) when set. */
  obj: string | null;
  x: number;
  y: number;
  z: number;
  align: 'center' | 'start';
  /** A stat badge that differs from the printed card (modified power/toughness). */
  emphasis?: boolean;
}

/** Text of the sleep badge on a summoning-sick creature. */
export const SICK_BADGE = 'Zzz';

/** Counter type recorded games use for planeswalker loyalty (replay_capture.COUNTER_TYPE_NAMES). */
export const LOYALTY_COUNTER = 'loyalty';

const PILE_NAMES: Record<PileZone, string> = {
  library: 'Library',
  graveyard: 'Graveyard',
  exile: 'Exile',
  command: 'Command',
};

function rotate(dx: number, dy: number, angle: number): [number, number] {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return [dx * c - dy * s, dx * s + dy * c];
}

/**
 * Offsets on a card in its upright frame: a tapped card's labels stay above
 * and below it, within its sideways footprint, instead of turning with it to
 * its left and right edges, where they ran into the neighbouring cards.
 */
function cardFrame(placement: CardPlacement): {
  at: (dx: number, dy: number) => [number, number];
  /** Half the footprint's height and width, scaled. */
  half: number;
  halfWidth: number;
} {
  const angle = placement.rotZ - (placement.tapped ? TAPPED_ROTATION : 0);
  const height = placement.tapped ? CARD_WIDTH : CARD_HEIGHT;
  const width = placement.tapped ? CARD_HEIGHT : CARD_WIDTH;
  return {
    at: (dx, dy) => rotate(dx, dy, angle),
    half: (height / 2) * placement.scale,
    halfWidth: (width / 2) * placement.scale,
  };
}

function isPlaneswalker(card: ReplayCard | undefined): boolean {
  return `${card?.primary_type ?? ''} ${card?.type_line ?? ''}`.toLowerCase().includes('planeswalker');
}

/** The badge across a card's lower edge: loyalty for a planeswalker, else current power/toughness. */
export function statBadge(
  placement: CardPlacement,
  card: ReplayCard | undefined,
): { text: string; tone: 'stat' | 'loyalty'; emphasis: boolean } | null {
  const loyalty = placement.counters[LOYALTY_COUNTER];
  if (loyalty !== undefined && (isPlaneswalker(card) || placement.power === null)) {
    return { text: String(loyalty), tone: 'loyalty', emphasis: false };
  }
  const printed = card && card.power !== null && card.toughness !== null ? `${card.power}/${card.toughness}` : null;
  if (placement.power !== null && placement.toughness !== null) {
    const current = `${placement.power}/${placement.toughness}`;
    return { text: current, tone: 'stat', emphasis: printed !== null && current !== printed };
  }
  return printed ? { text: printed, tone: 'stat', emphasis: false } : null;
}

/** Counters other than loyalty, as a short chip text ("+1/+1 ×2 · flying ×1"). */
const CASTABLE_LABELS: Record<CastableMark, string> = {
  flashback: 'Flashback',
  escape: 'Escape',
  disturb: 'Disturb',
  harmonize: 'Harmonize',
  plot: 'Plotted',
  cast_from_exile: 'From exile',
};

export function countersText(placement: CardPlacement): string | null {
  const parts: string[] = [];
  for (const [type, count] of Object.entries(placement.counters)) {
    if (type === LOYALTY_COUNTER) continue;
    // "+1/+1" alone reads as one counter; any other type always shows its count ("plan ×1").
    parts.push(count === 1 && (type === '+1/+1' || type === '-1/-1') ? type : `${type} ×${count}`);
  }
  return parts.length ? parts.join(' · ') : null;
}

/** Chip text for a card removed by the current action. */
export const REMOVAL_LABELS: Record<RemovalKind, string> = {
  destroyed: 'Destroyed',
  died: 'Died',
  exiled: 'Exiled',
  returned: 'Returned to hand',
  sacrificed: 'Sacrificed',
  graveyard: 'To graveyard',
  library: 'To library',
  discarded: 'Discarded',
};

const MINUS = '\u2212';

function signed(n: number): string {
  return n < 0 ? `${MINUS}${-n}` : `+${n}`;
}

/**
 * What the current action changed on a permanent besides damage: counters
 * added or removed ("+2/+2", "−1/−1", "+1 shield") or an effect's
 * power/toughness change ("+3/+0", "−2/−2"), with its tone.
 */
export function changeLabel(marks: ObjectMarks | null): { text: string; tone: 'buff' | 'debuff' | 'effect' } | null {
  if (!marks) return null;
  const parts: string[] = [];
  let score = 0;
  let plain = false;
  for (const [type, delta] of Object.entries(marks.counters)) {
    if (type === '+1/+1' || type === '-1/-1') {
      const n = type === '+1/+1' ? delta : -delta;
      parts.push(`${signed(n)}/${signed(n)}`);
      score += n;
    } else {
      parts.push(`${signed(delta)} ${type}`);
      plain = true;
    }
  }
  if (!parts.length && marks.pt) {
    parts.push(`${signed(marks.pt.power)}/${signed(marks.pt.toughness)}`);
    score += marks.pt.power + marks.pt.toughness;
  }
  if (!parts.length) return null;
  const tone = score > 0 ? 'buff' : score < 0 ? 'debuff' : plain ? 'effect' : 'buff';
  return { text: parts.join(' · '), tone };
}

/** The number at a seat's table edge: its life change this action (or the damage it took). */
export function seatNumber(marks: SeatMarks): { text: string; tone: 'life-loss' | 'life-gain' } | null {
  const change = marks.life || -marks.damage;
  if (!change) return null;
  return { text: signed(change), tone: change < 0 ? 'life-loss' : 'life-gain' };
}

function effectLabels(labels: SceneLabel[], placement: CardPlacement): void {
  const { marks } = placement;
  if (!marks) return;
  const frame = cardFrame(placement);
  const s = placement.scale;
  const change = placement.zone === 'battlefield' ? changeLabel(marks) : null;
  // A tapped card is short: the removal chip sits just below the middle, the
  // damage and change chips just above it, side by side when both show.
  const lower = placement.tapped ? -0.12 * s : -0.2 * s;
  const changeAt = placement.tapped
    ? frame.at(placement.damage ? 0.25 * s : 0, 0.1 * s)
    : frame.at(0, 0.3 * s);
  if (placement.removed) {
    const [dx, dy] = frame.at(0, lower);
    labels.push({
      id: `removed:${placement.obj}`,
      text: REMOVAL_LABELS[placement.removed],
      tone: 'removed',
      obj: placement.obj,
      x: dx,
      y: dy,
      z: 0.05,
      align: 'center',
    });
  } else if (marks.tapped && placement.zone === 'battlefield') {
    const [dx, dy] = frame.at(0, lower);
    labels.push({ id: `tapped:${placement.obj}`, text: 'Tapped', tone: 'effect', obj: placement.obj, x: dx, y: dy, z: 0.05, align: 'center' });
  }
  if (change) {
    const [dx, dy] = changeAt;
    labels.push({ id: `change:${placement.obj}`, text: change.text, tone: change.tone, obj: placement.obj, x: dx, y: dy, z: 0.05, align: 'center' });
  }
}

export function sceneLabels(layout: Layout, cards: Readonly<Record<CardKey, ReplayCard>>): SceneLabel[] {
  const labels: SceneLabel[] = [];
  for (const seat of layout.seatMarks) {
    const number = seatNumber(seat.marks);
    if (number) {
      labels.push({ id: `seat:${seat.seat}`, text: number.text, tone: number.tone, obj: null, x: seat.x, y: seat.y, z: 0.3, align: 'center' });
    }
    if (seat.marks.milled) {
      const pile = layout.piles.find((p) => p.seat === seat.seat && p.zone === 'graveyard');
      if (pile) {
        labels.push({
          id: `milled:${seat.seat}`,
          text: `Milled ${seat.marks.milled}`,
          tone: 'effect',
          obj: null,
          x: pile.x,
          y: pile.y + (CARD_HEIGHT * pile.scale) / 2 - 0.12,
          z: Math.min(pile.count, PILE_MAX_CARDS) * PILE_CARD_DEPTH + 0.03,
          align: 'center',
        });
      }
    }
  }
  for (const pile of layout.piles) {
    // An empty command zone keeps its label: it shows where the commander went out from.
    const empty = pile.zone === 'command' && pile.count === 0;
    labels.push({
      id: `pile:${pile.seat}:${pile.zone}`,
      text: empty ? PILE_NAMES[pile.zone] : `${PILE_NAMES[pile.zone]} ${pile.count}`,
      tone: 'pile',
      obj: null,
      // A badge across the lower edge of the pile, so neighbouring piles never collide.
      x: pile.x,
      y: pile.y - (CARD_HEIGHT * pile.scale) / 2 + 0.12,
      z: Math.min(pile.count, PILE_MAX_CARDS) * PILE_CARD_DEPTH + 0.03,
      align: 'center',
    });
  }
  for (const placement of layout.cards) {
    if (placement.castable) {
      // A chip across the upper edge names why the card sits beside the hand.
      const [dx, dy] = rotate(0, (CARD_HEIGHT / 2 - 0.1) * placement.scale, placement.rotZ);
      labels.push({
        id: `castable:${placement.obj}`,
        text: CASTABLE_LABELS[placement.castable],
        tone: 'castable',
        obj: placement.obj,
        x: dx,
        y: dy,
        z: 0.02,
        align: 'center',
        emphasis: placement.castable === 'plot',
      });
      continue;
    }
    // A token stacked under an identical one shows only its edge; the top card speaks for the stack.
    if (placement.stackedUnder) continue;
    if (placement.faceUp) effectLabels(labels, placement);
    if (placement.zone !== 'battlefield' || !placement.faceUp) continue;
    const frame = cardFrame(placement);
    const s = placement.scale;
    if (placement.damage) {
      // A red badge over the art for damage this moment ("−6"), above the stat badge.
      const change = placement.marks ? changeLabel(placement.marks) : null;
      const [dx, dy] = placement.tapped ? frame.at(change ? -0.25 * s : 0, 0.1 * s) : frame.at(0, 0.08 * s);
      labels.push({
        id: `damage:${placement.obj}`,
        text: `\u2212${placement.damage}`,
        tone: 'damage',
        obj: placement.obj,
        x: dx,
        y: dy,
        z: 0.04,
        align: 'center',
      });
    }
    const card = placement.card ? cards[placement.card] : undefined;
    const badge = statBadge(placement, card);
    if (badge) {
      const [dx, dy] = frame.at(0, -frame.half + 0.1 * s);
      labels.push({
        id: `stat:${placement.obj}`,
        text: badge.text,
        tone: badge.tone,
        obj: placement.obj,
        x: dx,
        y: dy,
        z: 0.02,
        align: 'center',
        emphasis: badge.emphasis,
      });
    }
    const counters = countersText(placement);
    const parts = [placement.chosen, placement.commander ? 'Commander' : null, counters].filter(Boolean);
    const chip = parts.length ? parts.join(' · ') : null;
    const landTone = placement.chosen ? LAND_TYPE_TONES[placement.chosen.split(' ')[0]] : undefined;
    if (placement.stackCount) {
      // How many identical tokens the stack holds, in the lower left corner.
      const [dx, dy] = frame.at(-frame.halfWidth + 0.14 * s, -frame.half + 0.1 * s);
      labels.push({
        id: `stack:${placement.obj}`,
        text: `\u00d7${placement.stackCount}`,
        tone: 'pile',
        obj: placement.obj,
        x: dx,
        y: dy,
        z: 0.02,
        align: 'center',
      });
    }
    if (placement.sick) {
      // Summoning sick: a sleep badge centered just above the top edge, clear of the name.
      const [dx, dy] = frame.at(0, frame.half + 0.08 * s);
      labels.push({
        id: `sick:${placement.obj}`,
        text: SICK_BADGE,
        tone: 'sick',
        obj: placement.obj,
        x: dx,
        y: dy,
        z: 0.02,
        align: 'center',
      });
    }
    if (placement.tuckedCount) {
      // How many cards the host's pile of exiled cards holds: a badge on the
      // upper right corner, clear of the name and cost (hover lists them).
      const [dx, dy] = frame.at(frame.halfWidth - 0.06 * s, frame.half + 0.02 * s);
      labels.push({
        id: `tucked:${placement.obj}`,
        text: `${placement.tuckedCount} under`,
        tone: 'tucked',
        obj: placement.obj,
        x: dx,
        y: dy,
        z: 0.02,
        align: 'center',
      });
    }
    if (chip) {
      const [dx, dy] = frame.at(0, frame.half - 0.1 * s);
      labels.push({
        id: `counters:${placement.obj}`,
        text: chip,
        tone: placement.commander ? 'commander' : counters ? 'counters' : (landTone ?? 'counters'),
        obj: placement.obj,
        x: dx,
        y: dy,
        z: 0.02,
        align: 'center',
      });
    }
  }
  return labels;
}
