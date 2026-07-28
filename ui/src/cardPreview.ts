const failedPreviewUrls = new Set<string>();
const previewOrientations = new Map<string, CardPreviewOrientation>();

export type CardPreviewOrientation = 'portrait' | 'landscape';

interface ScryfallCardMetadata {
  layout?: string;
}

export function cardPreviewImageUrl(cardName: string): string {
  const params = new URLSearchParams({
    exact: cardName,
    format: 'image',
    version: 'normal',
  });
  return `https://api.scryfall.com/cards/named?${params.toString()}`;
}

export function cardPreviewMetadataUrl(cardName: string): string {
  const params = new URLSearchParams({ exact: cardName });
  return `https://api.scryfall.com/cards/named?${params.toString()}`;
}

export function cachedCardPreviewOrientation(cardName: string): CardPreviewOrientation {
  return previewOrientations.get(cardName) ?? 'portrait';
}

export async function loadCardPreviewOrientation(
  cardName: string,
  signal?: AbortSignal,
): Promise<CardPreviewOrientation> {
  const cached = previewOrientations.get(cardName);
  if (cached) {
    return cached;
  }
  if (!cardName.includes('//')) {
    previewOrientations.set(cardName, 'portrait');
    return 'portrait';
  }

  const response = await fetch(cardPreviewMetadataUrl(cardName), {
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Scryfall card metadata failed (${response.status})`);
  }
  const metadata = (await response.json()) as ScryfallCardMetadata;
  const orientation = metadata.layout === 'split' ? 'landscape' : 'portrait';
  previewOrientations.set(cardName, orientation);
  return orientation;
}

export function previewImageHasFailed(url: string): boolean {
  return failedPreviewUrls.has(url);
}

export function rememberFailedPreviewImage(url: string): void {
  failedPreviewUrls.add(url);
}
