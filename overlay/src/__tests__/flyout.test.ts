import { describe, expect, it } from 'vitest';
import { chordFromEvent, hotkeyLabel, refuseHotkey } from '../components/Flyout';

describe('hotkey helpers', () => {
  it('shows mac glyphs only on macOS', () => {
    expect(hotkeyLabel('Alt+Shift+T', 'macos')).toBe('⌥⇧T');
    expect(hotkeyLabel('Alt+Shift+T', 'windows')).toBe('Alt+Shift+T');
    expect(hotkeyLabel('Cmd+Shift+H', 'macos')).toBe('⌘⇧H');
  });

  it('refuses chords the game or the system needs', () => {
    expect(refuseHotkey('T')).toMatch(/modifier/);
    expect(refuseHotkey('Shift+Space')).toMatch(/Arena/);
    expect(refuseHotkey('Alt+F4')).toMatch(/system/);
    expect(refuseHotkey('Alt+Shift+T')).toBeNull();
    expect(refuseHotkey('Ctrl+Shift+2')).toBeNull();
  });

  it('turns keydown events into accelerator strings', () => {
    expect(chordFromEvent({ ctrlKey: false, altKey: true, shiftKey: true, metaKey: false, key: 't' } as KeyboardEvent)).toBe('Alt+Shift+T');
    expect(chordFromEvent({ ctrlKey: false, altKey: true, shiftKey: false, metaKey: false, key: 'Shift' } as KeyboardEvent)).toBeNull();
    expect(chordFromEvent({ ctrlKey: true, altKey: false, shiftKey: false, metaKey: false, key: ' ' } as KeyboardEvent)).toBe('Ctrl+Space');
  });
});
