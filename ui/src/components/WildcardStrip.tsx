import type { PlayerInventory } from '../api';
import { formatNumber } from '../format';

type Rarity = 'common' | 'uncommon' | 'rare' | 'mythic';

const RARITIES: { key: Rarity; label: string; field: keyof PlayerInventory }[] = [
  { key: 'common', label: 'Common', field: 'wc_common' },
  { key: 'uncommon', label: 'Uncommon', field: 'wc_uncommon' },
  { key: 'rare', label: 'Rare', field: 'wc_rare' },
  { key: 'mythic', label: 'Mythic', field: 'wc_mythic' },
];

/** Five-petal wildcard burst; the rarity picks the gradient. */
function WildcardIcon({ rarity }: { rarity: Rarity }) {
  const id = `wc-${rarity}`;
  return (
    <svg className={`wildcard-icon wildcard-${rarity}`} viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" className="wildcard-stop-hi" />
          <stop offset="1" className="wildcard-stop-lo" />
        </linearGradient>
      </defs>
      <g fill={`url(#${id})`} stroke="rgb(0 0 0 / 40%)" strokeWidth="0.5" strokeLinejoin="round">
        {/* five petals fanning up from the bowl, then the bowl */}
        <path d="M16 3.5 C12.8 9 12.8 15.5 16 21 C19.2 15.5 19.2 9 16 3.5Z" />
        <path d="M16 3.5 C12.8 9 12.8 15.5 16 21 C19.2 15.5 19.2 9 16 3.5Z" transform="rotate(-30 16 21)" />
        <path d="M16 3.5 C12.8 9 12.8 15.5 16 21 C19.2 15.5 19.2 9 16 3.5Z" transform="rotate(30 16 21)" />
        <path d="M16 5 C13.4 10 13.4 16 16 21 C18.6 16 18.6 10 16 5Z" transform="rotate(-62 16 21)" />
        <path d="M16 5 C13.4 10 13.4 16 16 21 C18.6 16 18.6 10 16 5Z" transform="rotate(62 16 21)" />
        <path d="M5 21.5 C8 27.5 24 27.5 27 21.5 C22 24.5 10 24.5 5 21.5Z" />
      </g>
    </svg>
  );
}

/**
 * Wildcards available, straight from the inventory block Arena restates in
 * its log at launch and on every event join. Renders nothing until the
 * tracker has seen one.
 */
export function WildcardStrip({ inventory }: { inventory: PlayerInventory | null | undefined }) {
  if (!inventory) {
    return null;
  }
  const seen = new Date(inventory.captured_at);
  const title = Number.isNaN(seen.getTime())
    ? 'Wildcards available'
    : `Wildcards available — as of ${seen.toLocaleString()}`;
  return (
    <div className="wildcard-strip" role="group" aria-label="Wildcards available" title={title}>
      <span className="wildcard-strip-label">Wildcards</span>
      {RARITIES.map(({ key, label, field }) => (
        <span key={key} className="wildcard-item" aria-label={`${label} wildcards`}>
          <WildcardIcon rarity={key} />
          <strong>{formatNumber(inventory[field] as number | null)}</strong>
        </span>
      ))}
    </div>
  );
}
