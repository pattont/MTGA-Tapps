/** Scryfall art crop for a commander; front face only for MDFC/partner names. */
export function commanderArtUrl(name: string): string {
  const front = name.split(' // ')[0];
  return `https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(front)}&format=image&version=art_crop`;
}
