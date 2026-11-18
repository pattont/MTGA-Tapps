import { colorLetters, nonlandSeen, railTitle } from '../opponentModel';
import type { OverlayOpponent } from '../types';
import { Chevron } from './Icons';
import W from '../icons/W.svg';
import U from '../icons/U.svg';
import B from '../icons/B.svg';
import R from '../icons/R.svg';
import G from '../icons/G.svg';

const PIP_ICONS: Record<string, string> = { W, U, B, R, G };

interface Props {
  opponent: OverlayOpponent | null;
  dock: 'left' | 'right' | 'float';
  /** A card new this game just showed up: the Seen cell pulses. */
  pulse: boolean;
  onOpenPanel: () => void;
  onDragStart: (event: MouseEvent) => void;
}

/** How the rail shows your record inside its 40 px hairlines: "3–1" at the
    rail's number size, "12–1" a notch smaller, and from four digits ("12–10",
    "108–99") your win rate instead, like the Land cell's "27%". */
export function recordCell(record: { wins: number; losses: number } | null): { kind: 'none' | 'record' | 'rate'; wide: boolean; rate: number } {
  if (!record) return { kind: 'none', wide: false, rate: 0 };
  const digits = `${record.wins}${record.losses}`.length;
  const decided = record.wins + record.losses;
  if (digits >= 4) return { kind: 'rate', wide: false, rate: decided ? Math.round((100 * record.wins) / decided) : 0 };
  return { kind: 'record', wide: digits === 3, rate: 0 };
}

/** The opponent panel folded: the colours shown, distinct nonland cards
    seen, and your record against the deck line's subject. The tooltip
    names the deck. The colours cell is the drag handle. */
export function OpponentRail({ opponent, dock, pulse, onOpenPanel, onDragStart }: Props) {
  const colors = colorLetters(opponent?.colors);
  const seen = opponent ? nonlandSeen(opponent.seen) : 0;
  const record = opponent?.record ?? null;
  const shown = recordCell(record);
  return (
    <div class="rail opp-rail" role="group" aria-label="Opponent" title={railTitle(opponent)}>
      <div class="cell opp-colors" onMouseDown={onDragStart} aria-label={colors.length ? `Colours shown: ${colors.join('')}` : 'No colours shown yet'}>
        <span class="k">Opp</span>
        <span class="opp-pips">
          {colors.length > 0 ? colors.map((c) => <img key={c} src={PIP_ICONS[c]} alt={c} draggable={false} />) : <i class="opp-ring" aria-hidden="true" />}
        </span>
      </div>
      <div class="sep" />
      <div class={`cell${pulse ? ' pulse' : ''}`} aria-label={`${seen} nonland cards seen`}>
        <span class="k">Seen</span>
        <span class="v">{opponent ? seen : '—'}</span>
      </div>
      <div class="sep" />
      <div class="cell" aria-label={record ? `Your record against it: ${record.wins} wins, ${record.losses} losses` : 'No record against it yet'}>
        <span class="k">You</span>
        <span class={`v opp-vs${shown.wide ? ' wide' : ''}`} title={record ? `${record.wins}–${record.losses}` : undefined}>
          {record && shown.kind === 'record' ? (
            <>
              <span class="w">{record.wins}</span>
              <span class="of">–</span>
              <span class="l">{record.losses}</span>
            </>
          ) : record ? (
            <>
              <span class={shown.rate >= 50 ? 'w' : 'l'}>{shown.rate}</span>
              <span class="of">%</span>
            </>
          ) : (
            '—'
          )}
        </span>
      </div>
      <div class="sep" />
      {/* Points the way the panel opens: toward the board, away from the docked edge. */}
      <button type="button" class="open" onClick={onOpenPanel} title="Open the opponent panel" aria-label="Open the opponent panel">
        <Chevron dir={dock === 'left' ? 'right' : 'left'} />
      </button>
    </div>
  );
}
