import { useState } from 'react';
import type { CommanderRef } from '../api';
import { CardLink } from './CardLink';
import { ColorPips } from './ColorPips';

/** Scryfall art crop for a commander; front face only for MDFC/partner names. */
export function commanderArtUrl(name: string): string {
  const front = name.split(' // ')[0];
  return `https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(front)}&format=image&version=art_crop`;
}

/** One side's commander callout: art filling the box, name with the usual
    card hover link, and the commander's color identity under the name. */
function CommanderBox({
  eyebrow,
  commanders,
  returnHash,
  slim = false,
}: {
  eyebrow: string;
  commanders: CommanderRef[];
  returnHash: string;
  /** Shorter banner variant (deck page decklist callout). */
  slim?: boolean;
}) {
  const [artFailed, setArtFailed] = useState(false);
  const artName = commanders[0]?.card_name ?? null;
  const colors = commanders.map((commander) => commander.colors).join('');
  const className = [
    'commander-box',
    artName && !artFailed ? 'commander-box-art-loaded' : '',
    slim ? 'commander-box-slim' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={className}>
      {artName && !artFailed ? (
        <>
          <img
            alt=""
            aria-hidden="true"
            className="commander-box-art"
            loading="lazy"
            src={commanderArtUrl(artName)}
            onError={() => setArtFailed(true)}
          />
          <div aria-hidden="true" className="commander-box-scrim" />
        </>
      ) : null}
      <span className="commander-box-eyebrow">{eyebrow}</span>
      <span className="commander-box-name">
        {commanders.length > 0
          ? commanders.map((commander, index) => (
              <span key={commander.card_name}>
                {index > 0 ? ' · ' : ''}
                <CardLink cardName={commander.card_name} returnHash={returnHash}>
                  {commander.card_name}
                </CardLink>
              </span>
            ))
          : 'Not revealed'}
      </span>
      {colors ? (
        <span className="commander-box-pips">
          <ColorPips colors={colors} />
        </span>
      ) : null}
    </div>
  );
}

/** Thin full-width commander banner (deck page's decklist section). */
export function CommanderBanner({
  commanders,
  returnHash,
}: {
  commanders: CommanderRef[];
  returnHash: string;
}) {
  return (
    <div className="commander-banner">
      <CommanderBox commanders={commanders} eyebrow="Commander" returnHash={returnHash} slim />
    </div>
  );
}

/** Full-width "Our Commander vs Opponent Commander" strip for Brawl games. */
export function CommanderVersus({
  player,
  opponent,
  returnHash,
}: {
  player: CommanderRef[];
  opponent: CommanderRef[];
  returnHash: string;
}) {
  return (
    <div aria-label="Commanders" className="commander-versus" role="group">
      <CommanderBox commanders={player} eyebrow="Our Commander" returnHash={returnHash} />
      <CommanderBox commanders={opponent} eyebrow="Opponent Commander" returnHash={returnHash} />
    </div>
  );
}
