/** "Replay Options" popover: felt and sleeve colors, camera preset and view toggles (saved per viewer). */
import { useEffect, useRef } from 'react';
import { FELT_COLORS, SLEEVE_COLORS, savePrefs } from '../prefs';
import type { FeltColor, PaletteColor, ReplayPrefs, SleeveColor } from '../prefs';

interface SwatchesProps<T extends string> {
  label: string;
  palette: Record<T, PaletteColor>;
  value: T;
  onPick: (value: T) => void;
}

function Swatches<T extends string>({ label, palette, value, onPick }: SwatchesProps<T>) {
  return (
    <fieldset className="replay-swatches">
      <legend>{label}</legend>
      <div>
        {(Object.keys(palette) as T[]).map((id) => (
          <button
            key={id}
            type="button"
            className="replay-swatch"
            aria-pressed={id === value}
            aria-label={`${label}: ${palette[id].label}`}
            title={palette[id].label}
            style={{ background: `linear-gradient(135deg, ${palette[id].accent}, ${palette[id].hex})` }}
            onClick={() => onPick(id)}
          />
        ))}
      </div>
    </fieldset>
  );
}

interface TablePopoverProps {
  prefs: ReplayPrefs;
  hindsightAvailable: boolean;
  onClose: () => void;
}

export function TablePopover({ prefs, hindsightAvailable, onClose }: TablePopoverProps) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panel.current && !panel.current.contains(target) && !(target as Element).closest?.('[data-table-toggle]')) {
        onClose();
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  return (
    <div className="replay-popover" role="dialog" aria-labelledby="replay-options-title" ref={panel}>
      <h4 className="replay-popover-title" id="replay-options-title">
        Replay Options
      </h4>
      <Swatches<FeltColor> label="Felt" palette={FELT_COLORS} value={prefs.felt} onPick={(felt) => savePrefs({ felt })} />
      <Swatches<SleeveColor>
        label="Your sleeves"
        palette={SLEEVE_COLORS}
        value={prefs.playerSleeve}
        onPick={(playerSleeve) => savePrefs({ playerSleeve })}
      />
      <Swatches<SleeveColor>
        label="Opponent sleeves"
        palette={SLEEVE_COLORS}
        value={prefs.opponentSleeve}
        onPick={(opponentSleeve) => savePrefs({ opponentSleeve })}
      />
      <fieldset className="replay-segmented">
        <legend>Camera</legend>
        <div>
          {(['table', 'topdown'] as const).map((camera) => (
            <button key={camera} type="button" aria-pressed={prefs.camera === camera} onClick={() => savePrefs({ camera })}>
              {camera === 'table' ? 'Table' : 'Top-down'}
            </button>
          ))}
        </div>
      </fieldset>
      <fieldset className="replay-segmented">
        <legend>Pacing</legend>
        <div>
          {(['paced', 'realtime'] as const).map((pacing) => (
            <button key={pacing} type="button" aria-pressed={prefs.pacing === pacing} onClick={() => savePrefs({ pacing })}>
              {pacing === 'paced' ? 'Paced' : 'Real time'}
            </button>
          ))}
        </div>
      </fieldset>
      <label className="replay-check">
        <input
          type="checkbox"
          checked={prefs.mirrorOpponent}
          onChange={(event) => savePrefs({ mirrorOpponent: event.target.checked })}
        />
        Mirror opponent (cards face them)
      </label>
      <label className="replay-check" title={hindsightAvailable ? undefined : 'Only recorded games know hidden cards ahead of time'}>
        <input
          type="checkbox"
          checked={prefs.hindsight}
          disabled={!hindsightAvailable}
          onChange={(event) => savePrefs({ hindsight: event.target.checked })}
        />
        Hindsight: show opponent cards in hand once revealed
      </label>
      <p className="replay-popover-shortcuts">
        Shortcuts: Space play · ←/→ step · J/K turn · Home/End · [ ] speed · G go to turn · Wheel or +/− zoom, drag to pan, 0 reset · T this panel
      </p>
    </div>
  );
}
