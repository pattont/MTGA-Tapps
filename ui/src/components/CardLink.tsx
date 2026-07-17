import type { ReactNode } from 'react';
import { cardRouteHash } from '../routes';

interface CardLinkProps {
  cardName: string;
  children?: ReactNode;
}

export function CardLink({ cardName, children }: CardLinkProps) {
  return (
    <a className="card-link" href={cardRouteHash(cardName)}>
      {children ?? cardName}
    </a>
  );
}
