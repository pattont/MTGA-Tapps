/** MTG color-combo naming, mirroring src/mtga_tracker/colors.py. */

const WUBRG_ORDER = 'WUBRG';

const COLOR_NAMES: Record<string, string> = {
  W: 'White',
  U: 'Blue',
  B: 'Black',
  R: 'Red',
  G: 'Green',
};

/** Canonical keys are WUBRG-ordered strings. */
const COMBO_NAMES: Record<string, string> = {
  WU: 'Azorius',
  WR: 'Boros',
  UB: 'Dimir',
  BG: 'Golgari',
  RG: 'Gruul',
  UR: 'Izzet',
  WB: 'Orzhov',
  BR: 'Rakdos',
  WG: 'Selesnya',
  UG: 'Simic',
  WUG: 'Bant',
  WUB: 'Esper',
  UBR: 'Grixis',
  BRG: 'Jund',
  WRG: 'Naya',
  WBG: 'Abzan',
  WUR: 'Jeskai',
  WBR: 'Mardu',
  UBG: 'Sultai',
  URG: 'Temur',
  WBRG: 'Dune',
  UBRG: 'Glint',
  WURG: 'Ink',
  WUBG: 'Witch',
  WUBR: 'Yore',
};

/** WUBRG-ordered unique color letters found in value. "C" (colorless — a
    real identity in MTG) survives only on its own: next to actual colors
    it's just noise, alone it means the thing is genuinely colorless. */
export function normalizeColors(value: string | null | undefined): string {
  if (!value) {
    return '';
  }
  const seen = new Set(Array.from(String(value).toUpperCase()));
  const letters = Array.from(WUBRG_ORDER)
    .filter((letter) => seen.has(letter))
    .join('');
  if (letters) {
    return letters;
  }
  return seen.has('C') ? 'C' : '';
}

/** Community name for a color combination ("Dimir", "Mono-Red", "5c"), or null. */
export function colorComboLabel(value: string | null | undefined): string | null {
  const colors = normalizeColors(value);
  if (!colors) {
    return null;
  }
  if (colors === 'C') {
    return 'Colorless';
  }
  if (colors.length === 1) {
    return `Mono-${COLOR_NAMES[colors]}`;
  }
  if (colors.length === 5) {
    return '5c';
  }
  return COMBO_NAMES[colors] ?? colors;
}
