import type { ReactNode } from 'react';
import { opponentRouteHash } from '../routes';

export function OpponentLink({
  opponentName,
  children,
}: {
  opponentName: string;
  children?: ReactNode;
}) {
  return (
    <a className="deck-link" href={opponentRouteHash(opponentName)}>
      {children ?? opponentName}
    </a>
  );
}
