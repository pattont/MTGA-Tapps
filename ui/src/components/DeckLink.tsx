import type { ReactNode } from 'react';
import { useContext } from 'react';
import type { SnapshotFilters } from '../api';
import { RouteFiltersContext } from '../routeFilters';
import { deckRouteHashWithFilters } from '../routes';

interface DeckLinkProps {
  deckName: string;
  children?: ReactNode;
  filters?: SnapshotFilters;
}

export function DeckLink({ deckName, children, filters }: DeckLinkProps) {
  const contextFilters = useContext(RouteFiltersContext);
  return (
    <a className="deck-link" href={deckRouteHashWithFilters(deckName, filters ?? contextFilters)}>
      {children ?? deckName}
    </a>
  );
}
