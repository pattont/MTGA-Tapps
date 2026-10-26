/**
 * Texture cache for one replay page. Card faces resolve through ImageQueue
 * (Scryfall only), decode off the main thread with `img.decode()`, and load
 * at most MAX_CONCURRENT_IMAGES at a time, highest priority first (cards on
 * the table now, then the current and next turn, then the rest). Procedural
 * felt, sleeve and helper textures are cached by color id. Everything is
 * disposed with the store.
 */
import {
  CanvasTexture,
  MeshBasicMaterial,
  MeshStandardMaterial,
  NoColorSpace,
  RepeatWrapping,
  SRGBColorSpace,
  ShaderChunk,
  Texture,
} from 'three';
import { cardPreviewImageUrl } from '../../cardPreview';
import {
  ImageQueue,
  cardImageCandidates,
  generatedTokenFace,
  isRateLimitedUrl,
  resolveCardImage,
  resolvedImageCache,
  scryfallRateLimiter,
} from '../images';
import { createFeltCanvas, createSleeveCanvas } from '../materials';
import { FELT_COLORS, SLEEVE_COLORS } from '../prefs';
import type { FeltColor, SleeveColor } from '../prefs';
import type { CardKey, ReplayCard } from '../types';
import {
  createCardAlphaCanvas,
  createCastableCanvas,
  createHoverShadowCanvas,
  createInferredCanvas,
  createRingCanvas,
  createShadowCanvas,
  createSlotCanvas,
  createUnknownCanvas,
} from './sceneCanvases';

export const MAX_CONCURRENT_IMAGES = 6;
/** A card still loading after this long shows a generated frame with its name. */
export const PLACEHOLDER_DELAY_MS = 700;
/** Priority at which a card is on the table right now. */
export const VISIBLE_PRIORITY = 3;
export const UNKNOWN_CARD: CardKey = 'unknown';
/** Hover previews jump ahead of background loads in the shared queue. */
export const PREVIEW_PRIORITY = 10;

export type ImageLoader = (url: string) => Promise<TexImageSource>;
type Timer = ReturnType<typeof setTimeout>;

interface FaceEntry {
  status: 'idle' | 'queued' | 'loading' | 'done';
  priority: number;
  texture: Texture | null;
  url: string | null;
  timer: Timer | null;
}

export interface TextureStoreOptions {
  queue?: ImageQueue;
  loadImage?: ImageLoader;
  maxConcurrent?: number;
  placeholderDelayMs?: number;
}

export function loadDecodedImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.decoding = 'async';
    image.onload = () => {
      if (typeof image.decode === 'function') {
        image.decode().then(() => resolve(image), () => resolve(image));
      } else {
        resolve(image);
      }
    };
    image.onerror = () => reject(new Error(`Image failed to load: ${url}`));
    image.src = url;
  });
}

/**
 * LOD bias for card faces. A card is small on screen, so the GPU picks a
 * heavily reduced mipmap; one level sharper keeps names and art crisper. The
 * supersampled frame (pixelRatio.ts) absorbs the shimmer this would add.
 */
export const CARD_MIP_BIAS = -1;
const BIASED_MAP_FRAGMENT = ShaderChunk.map_fragment.replace(
  'texture2D( map, vMapUv )',
  `texture2D( map, vMapUv, ${CARD_MIP_BIAS.toFixed(1)} )`,
);

export function isUnknownCard(key: CardKey | null, card: ReplayCard | undefined): boolean {
  return key === UNKNOWN_CARD || (!!card && card.name === 'Unknown card' && !card.arena_id);
}

export class TextureStore {
  private readonly cards: Readonly<Record<CardKey, ReplayCard>>;
  private readonly queue: ImageQueue;
  private readonly loadImage: ImageLoader;
  private readonly maxConcurrent: number;
  private readonly placeholderDelay: number;
  private readonly faces = new Map<CardKey, FaceEntry>();
  private readonly generated = new Map<CardKey, Texture>();
  private readonly generatedUrls = new Map<CardKey, string | null>();
  private readonly owned = new Set<Texture>();
  private readonly materials = new Map<Texture, MeshBasicMaterial>();
  private readonly plainMaterials = new Map<string, MeshBasicMaterial | MeshStandardMaterial>();
  private readonly byId = new Map<string, Texture>();
  private readonly listeners = new Set<() => void>();
  private flushTimer: Timer | null = null;
  private active = 0;
  private disposed = false;
  private anisotropy = 1;
  private refs = 0;
  private disposeTimer: Timer | null = null;
  version = 0;

  constructor(cards: Readonly<Record<CardKey, ReplayCard>>, opts: TextureStoreOptions = {}) {
    this.cards = cards;
    // The app's queues all draw on one api.scryfall.com budget (8 requests/s).
    this.queue = opts.queue ?? new ImageQueue({ limiter: scryfallRateLimiter });
    this.loadImage = opts.loadImage ?? loadDecodedImage;
    this.maxConcurrent = opts.maxConcurrent ?? MAX_CONCURRENT_IMAGES;
    this.placeholderDelay = opts.placeholderDelayMs ?? PLACEHOLDER_DELAY_MS;
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Face texture for a card, or null while nothing is ready (stable reference). */
  face(key: CardKey | null): Texture | null {
    return key ? (this.faces.get(key)?.texture ?? null) : null;
  }

  /** Final image URL once resolved (used for the large hover preview). */
  resolvedUrl(key: CardKey): string | null {
    return this.faces.get(key)?.url ?? null;
  }

  /**
   * The procedural face (name, type, P/T) as a data URL, for DOM previews of
   * a card Scryfall has no image for. Null for unknown cards or when the
   * canvas cannot export (headless tests).
   */
  generatedFaceUrl(key: CardKey | null): string | null {
    const card = key ? this.cards[key] : undefined;
    if (!key || !card || isUnknownCard(key, card)) return null;
    const cached = this.generatedUrls.get(key);
    if (cached !== undefined) return cached;
    let url: string | null;
    try {
      url = generatedTokenFace(card).toDataURL('image/png');
    } catch {
      url = null;
    }
    this.generatedUrls.set(key, url);
    return url;
  }

  /**
   * Large preview image when it is known without asking Scryfall's API: the
   * resolved CDN image, a cached large lookup, or a CDN link from the server.
   * Null means `resolvePreview` must look it up (rate-limited).
   */
  previewUrlNow(key: CardKey | null): string | null {
    const card = key ? this.cards[key] : undefined;
    if (!key || !card || isUnknownCard(key, card)) return null;
    const resolved = this.resolvedUrl(key);
    if (resolved && resolved.includes('cards.scryfall.io/normal/')) {
      return resolved.replace('/normal/', '/large/');
    }
    const cached = resolvedImageCache.get(`${key}@large`);
    if (cached) return cached;
    const first = cardImageCandidates(card, 'large')[0];
    return first && !isRateLimitedUrl(first) ? first : null;
  }

  /**
   * Looks a preview image up through this page's queue, so hovering across
   * many names never sends more than the shared 8/s to api.scryfall.com.
   * Resolves to a CDN URL, or null when no image exists.
   */
  async resolvePreview(key: CardKey | null, name: string): Promise<string | null> {
    const now = this.previewUrlNow(key);
    if (now) return now;
    const card = key ? this.cards[key] : undefined;
    if (key && card && !isUnknownCard(key, card)) {
      return resolveCardImage(key, card, this.queue, { size: 'large', priority: PREVIEW_PRIORITY });
    }
    if (!name) return null;
    try {
      return await this.queue.load(cardPreviewImageUrl(name), PREVIEW_PRIORITY);
    } catch {
      return null;
    }
  }

  get inFlight(): number {
    return this.active;
  }

  setAnisotropy(value: number): void {
    this.anisotropy = Math.max(1, value);
    for (const texture of this.owned) {
      if (texture.anisotropy !== this.anisotropy) {
        texture.anisotropy = this.anisotropy;
        texture.needsUpdate = true;
      }
    }
  }

  /** Updates load priorities; unseen cards start loading in priority order. */
  request(priorities: ReadonlyMap<CardKey, number>): void {
    if (this.disposed) return;
    for (const [key, priority] of priorities) {
      const card = this.cards[key];
      if (!card || isUnknownCard(key, card)) continue;
      let entry = this.faces.get(key);
      if (!entry) {
        entry = { status: 'idle', priority, texture: null, url: null, timer: null };
        this.faces.set(key, entry);
      }
      entry.priority = priority;
      if (entry.status === 'idle') {
        if (cardImageCandidates(card, 'normal').length === 0) {
          this.useGenerated(key, entry);
          continue;
        }
        entry.status = 'queued';
        // Tokens show their procedural face at once; the printed token art
        // (a Scryfall token-set search) replaces it when it arrives.
        if (card.is_token) entry.texture = this.generatedTexture(key);
      }
      if (priority >= VISIBLE_PRIORITY && entry.status !== 'done' && !entry.texture && !entry.timer) {
        entry.timer = setTimeout(() => {
          entry.timer = null;
          if (!this.disposed && entry.status !== 'done' && !entry.texture) {
            entry.texture = this.generatedTexture(key);
            this.changed();
          }
        }, this.placeholderDelay);
      }
    }
    this.pump();
  }

  private pump(): void {
    while (!this.disposed && this.active < this.maxConcurrent) {
      let best: [CardKey, FaceEntry] | null = null;
      for (const pair of this.faces) {
        if (pair[1].status === 'queued' && (!best || pair[1].priority > best[1].priority)) best = pair;
      }
      if (!best) return;
      void this.run(best[0], best[1]);
    }
  }

  private async run(key: CardKey, entry: FaceEntry): Promise<void> {
    entry.status = 'loading';
    this.active += 1;
    try {
      const url = await resolveCardImage(key, this.cards[key], this.queue, { priority: entry.priority });
      if (this.disposed) return;
      if (!url) {
        this.useGenerated(key, entry);
        return;
      }
      entry.url = url;
      const image = await this.loadImage(url);
      if (this.disposed) return;
      const texture = this.own(new Texture(image));
      texture.needsUpdate = true;
      this.finish(entry, texture);
    } catch {
      if (!this.disposed) this.useGenerated(key, entry);
    } finally {
      this.active -= 1;
      this.pump();
    }
  }

  private finish(entry: FaceEntry, texture: Texture): void {
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = null;
    entry.status = 'done';
    entry.texture = texture;
    this.changed();
  }

  private useGenerated(key: CardKey, entry: FaceEntry): void {
    this.finish(entry, this.generatedTexture(key));
  }

  private generatedTexture(key: CardKey): Texture {
    let texture = this.generated.get(key);
    if (!texture) {
      texture = this.own(new CanvasTexture(generatedTokenFace(this.cards[key])));
      this.generated.set(key, texture);
    }
    return texture;
  }

  private own<T extends Texture>(texture: T): T {
    texture.colorSpace = SRGBColorSpace;
    texture.anisotropy = this.anisotropy;
    texture.generateMipmaps = true;
    this.owned.add(texture);
    return texture;
  }

  private cached(id: string, make: () => Texture): Texture {
    let texture = this.byId.get(id);
    if (!texture) {
      texture = this.own(make());
      this.byId.set(id, texture);
    }
    return texture;
  }

  sleeve(color: SleeveColor): Texture {
    const palette = SLEEVE_COLORS[color];
    return this.cached(`sleeve:${color}`, () => new CanvasTexture(createSleeveCanvas(palette.hex, palette.accent)));
  }

  unknown(color: SleeveColor): Texture {
    const palette = SLEEVE_COLORS[color];
    return this.cached(`unknown:${color}`, () => new CanvasTexture(createUnknownCanvas(palette.hex, palette.accent)));
  }

  felt(color: FeltColor): Texture {
    return this.cached(`felt:${color}`, () => {
      const texture = new CanvasTexture(createFeltCanvas(FELT_COLORS[color].hex));
      texture.wrapS = RepeatWrapping;
      texture.wrapT = RepeatWrapping;
      // Sharp at the tilted camera: mipmaps plus anisotropy (set with the cards').
      texture.generateMipmaps = true;
      texture.anisotropy = this.anisotropy;
      texture.repeat.set(4, 2.5);
      return texture;
    });
  }

  /** Linear-space helper masks (alpha, shadow, rings). */
  helper(name: 'alpha' | 'shadow' | 'hoverShadow' | 'ring' | 'inferred' | 'slot' | 'castable'): Texture {
    const makers = {
      alpha: createCardAlphaCanvas,
      shadow: () => createShadowCanvas(),
      hoverShadow: createHoverShadowCanvas,
      ring: createRingCanvas,
      inferred: createInferredCanvas,
      castable: createCastableCanvas,
      slot: createSlotCanvas,
    };
    const texture = this.cached(`helper:${name}`, () => new CanvasTexture(makers[name]()));
    if (name === 'alpha') texture.colorSpace = NoColorSpace;
    return texture;
  }

  /** One shared unlit material per face texture (rounded corners via alphaTest). */
  cardMaterial(texture: Texture): MeshBasicMaterial {
    let material = this.materials.get(texture);
    if (!material) {
      material = new MeshBasicMaterial({ map: texture, alphaMap: this.helper('alpha'), alphaTest: 0.5 });
      material.onBeforeCompile = (shader) => {
        shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', BIASED_MAP_FRAGMENT);
      };
      material.customProgramCacheKey = () => 'card-mip-bias';
      this.materials.set(texture, material);
    }
    return material;
  }

  /** Felt cloth material for one color (lit, so the table shows the light falloff). */
  feltMaterial(color: FeltColor): MeshStandardMaterial {
    const id = `felt:${color}`;
    let material = this.plainMaterials.get(id) as MeshStandardMaterial | undefined;
    if (!material) {
      material = new MeshStandardMaterial({ map: this.felt(color), roughness: 0.95, metalness: 0 });
      this.plainMaterials.set(id, material);
    }
    return material;
  }

  /** Square-cornered sleeve for the top of a library pile. */
  pileTopMaterial(color: SleeveColor): MeshBasicMaterial {
    const id = `pile:${color}`;
    let material = this.plainMaterials.get(id) as MeshBasicMaterial | undefined;
    if (!material) {
      material = new MeshBasicMaterial({ map: this.sleeve(color) });
      this.plainMaterials.set(id, material);
    }
    return material;
  }

  private changed(): void {
    if (this.flushTimer || this.disposed) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      this.version += 1;
      for (const listener of [...this.listeners]) listener();
    }, 32);
  }

  /** Reference counting with a deferred dispose survives StrictMode's effect replay. */
  retain(): void {
    this.refs += 1;
    if (this.disposeTimer) clearTimeout(this.disposeTimer);
    this.disposeTimer = null;
  }

  release(): void {
    this.refs = Math.max(0, this.refs - 1);
    if (this.refs === 0 && !this.disposeTimer) {
      this.disposeTimer = setTimeout(() => {
        this.disposeTimer = null;
        if (this.refs === 0) this.dispose();
      }, 0);
    }
  }

  get isDisposed(): boolean {
    return this.disposed;
  }

  dispose(): void {
    this.disposed = true;
    this.queue.cancelPending();
    if (this.flushTimer) clearTimeout(this.flushTimer);
    for (const entry of this.faces.values()) {
      if (entry.timer) clearTimeout(entry.timer);
    }
    for (const material of this.materials.values()) material.dispose();
    for (const material of this.plainMaterials.values()) material.dispose();
    this.plainMaterials.clear();
    for (const texture of this.owned) texture.dispose();
    this.materials.clear();
    this.owned.clear();
    this.listeners.clear();
  }
}
