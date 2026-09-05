import type { Settings } from '../types';
import { Close } from './Icons';

interface Props {
  settings: Settings;
  platform: string;
  onChange: (next: Settings) => void;
  onClose: () => void;
  onQuit: () => void;
}

/** "Alt+Shift+T" -> "⌥⇧T" on macOS, unchanged elsewhere. */
export function hotkeyLabel(chord: string, platform: string): string {
  if (platform !== 'macos') return chord;
  return chord
    .split('+')
    .map((part) => ({ Alt: '⌥', Option: '⌥', Shift: '⇧', Cmd: '⌘', Command: '⌘', Super: '⌘', Ctrl: '⌃', Control: '⌃' })[part] ?? part)
    .join('');
}

const SYSTEM_RESERVED = new Set(['Cmd+Q', 'Cmd+Tab', 'Cmd+Space', 'Alt+F4', 'Ctrl+Alt+Delete', 'Super+L', 'Cmd+H', 'Cmd+M']);
const ARENA_KEYS = new Set(['Space', 'Enter', 'Escape', 'Z', 'Q', 'W', 'E', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0']);

/** Why a chord is refused, or null when it is fine. */
export function refuseHotkey(chord: string): string | null {
  const parts = chord.split('+').map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return 'Needs a modifier — a bare key would eat game input.';
  const key = parts[parts.length - 1];
  const mods = parts.slice(0, -1);
  if (mods.length === 0 || mods.every((m) => !['Alt', 'Option', 'Shift', 'Cmd', 'Command', 'Ctrl', 'Control', 'Super'].includes(m))) {
    return 'Needs a modifier — a bare key would eat game input.';
  }
  if (SYSTEM_RESERVED.has(chord)) return 'Reserved by the system.';
  const keyName = key.length === 1 ? key.toUpperCase() : key;
  if (mods.length === 1 && mods[0] === 'Shift' && ARENA_KEYS.has(keyName)) return 'Arena uses that key in-game.';
  return null;
}

/** Turn a keydown into an accelerator string, or null for a modifier-only press. */
export function chordFromEvent(event: KeyboardEvent): string | null {
  const mods: string[] = [];
  if (event.ctrlKey) mods.push('Ctrl');
  if (event.altKey) mods.push('Alt');
  if (event.shiftKey) mods.push('Shift');
  if (event.metaKey) mods.push('Cmd');
  const key = event.key;
  if (['Control', 'Alt', 'Shift', 'Meta'].includes(key)) return null;
  const name = key === ' ' ? 'Space' : key.length === 1 ? key.toUpperCase() : key;
  return [...mods, name].join('+');
}

export function Flyout({ settings, platform, onChange, onClose, onQuit }: Props) {
  const hotkeys = platform === 'macos' ? settings.hotkeysMacos : settings.hotkeysWindows;
  const setHotkeys = (next: Settings['hotkeysMacos']) =>
    onChange(platform === 'macos' ? { ...settings, hotkeysMacos: next } : { ...settings, hotkeysWindows: next });
  const capture = (which: 'toggle' | 'visibility') => (event: KeyboardEvent) => {
    event.preventDefault();
    const chord = chordFromEvent(event);
    if (!chord) return;
    const reason = refuseHotkey(chord);
    const target = event.currentTarget as HTMLElement;
    if (reason) {
      target.dataset.error = reason;
      return;
    }
    delete target.dataset.error;
    setHotkeys({ ...hotkeys, [which]: chord });
    target.blur();
  };

  return (
    <div class="fly" role="dialog" aria-label="Overlay settings">
      <div class="fly-head">
        <h4>Overlay settings</h4>
        <button type="button" onClick={onClose} aria-label="Close settings">
          <Close />
        </button>
      </div>
      <label class="r">
        <span>Background</span>
        <input type="checkbox" checked={settings.background} onChange={(event) => onChange({ ...settings, background: (event.currentTarget as HTMLInputElement).checked })} />
      </label>
      <label class={`r${settings.background ? '' : ' off'}`}>
        <span>Tint strength</span>
        <input
          type="range"
          min="20"
          max="100"
          disabled={!settings.background}
          value={Math.round(settings.opacity * 100)}
          onInput={(event) => onChange({ ...settings, opacity: Number((event.currentTarget as HTMLInputElement).value) / 100 })}
          aria-label="Tint strength"
        />
        <span class="v">{Math.round(settings.opacity * 100)}%</span>
      </label>
      <label class="r">
        <span>Max panel height</span>
        <input
          type="range"
          min="30"
          max="100"
          step="5"
          value={settings.panelMaxHeightPct}
          onInput={(event) => onChange({ ...settings, panelMaxHeightPct: Number((event.currentTarget as HTMLInputElement).value) })}
          aria-label="Max panel height, percent of the screen"
        />
        <span class="v">{settings.panelMaxHeightPct}%</span>
      </label>
      <div class="r">
        <span>Dock</span>
        <span class="seg" role="group" aria-label="Dock">
          {(['left', 'right', 'float'] as const).map((dock) => (
            <button key={dock} type="button" class={settings.dock === dock ? 'on' : ''} onClick={() => onChange({ ...settings, dock })}>
              {dock === 'left' ? 'Left' : dock === 'right' ? 'Right' : 'Float'}
            </button>
          ))}
        </span>
      </div>
      <label class="r">
        <span>Unpinned: return to rail after</span>
        <span class="v">
          <input
            type="number"
            min="1"
            max="60"
            value={settings.returnAfterSeconds}
            onChange={(event) =>
              onChange({ ...settings, returnAfterSeconds: Math.max(1, Math.min(60, Number((event.currentTarget as HTMLInputElement).value) || 4)) })
            }
            aria-label="Return to rail after seconds"
          />{' '}
          s
        </span>
      </label>
      <label class="r">
        <span>Open pinned by default</span>
        <input type="checkbox" checked={settings.openPinned} onChange={(event) => onChange({ ...settings, openPinned: (event.currentTarget as HTMLInputElement).checked })} />
      </label>
      <label class="r">
        <span>Click-through when pinned</span>
        <input
          type="checkbox"
          checked={settings.clickThroughWhenPinned}
          onChange={(event) => onChange({ ...settings, clickThroughWhenPinned: (event.currentTarget as HTMLInputElement).checked })}
        />
      </label>
      <div class="r">
        <span>Lands</span>
        <span class="seg" role="group" aria-label="Lands">
          <button type="button" class={settings.lands === 'grouped' ? 'on' : ''} onClick={() => onChange({ ...settings, lands: 'grouped' })}>
            Basic / Nonbasic
          </button>
          <button type="button" class={settings.lands === 'all' ? 'on' : ''} onClick={() => onChange({ ...settings, lands: 'all' })}>
            Every land
          </button>
        </span>
      </div>
      <div class="r">
        <span>Rows</span>
        <span class="seg" role="group" aria-label="Density">
          <button type="button" class={settings.density === 'comfortable' ? 'on' : ''} onClick={() => onChange({ ...settings, density: 'comfortable' })}>
            Comfortable
          </button>
          <button type="button" class={settings.density === 'compact' ? 'on' : ''} onClick={() => onChange({ ...settings, density: 'compact' })}>
            Compact
          </button>
        </span>
      </div>
      <label class="r">
        <span>Hide when Arena isn't in front</span>
        <input
          type="checkbox"
          checked={settings.hideWhenArenaNotInFront}
          onChange={(event) => onChange({ ...settings, hideWhenArenaNotInFront: (event.currentTarget as HTMLInputElement).checked })}
        />
      </label>
      <div class="r">
        <span>Toggle rail / panel</span>
        <button type="button" class="hot" onKeyDown={capture('toggle')} title="Click, then press the new chord">
          {hotkeyLabel(hotkeys.toggle, platform)}
        </button>
      </div>
      <div class="r">
        <span>Show / hide</span>
        <button type="button" class="hot" onKeyDown={capture('visibility')} title="Click, then press the new chord">
          {hotkeyLabel(hotkeys.visibility, platform)}
        </button>
      </div>
      <div class="r">
        <span>Tracker API</span>
        <input
          class="url"
          type="text"
          value={settings.apiUrl}
          onChange={(event) => onChange({ ...settings, apiUrl: (event.currentTarget as HTMLInputElement).value.trim() || settings.apiUrl })}
          aria-label="Tracker API URL"
        />
      </div>
      <div class="fly-foot">
        <button type="button" class="quit" onClick={onQuit}>
          Quit overlay
        </button>
      </div>
    </div>
  );
}
