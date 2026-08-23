import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { fetchGlobalSearch, type GlobalSearchResult } from '../api';
import { formatCardName } from '../format';
import { cardRouteHash, deckRouteHash, opponentRouteHash } from '../routes';
import { CardLink } from './CardLink';
import { TypeChip } from './TypeChip';

const SEARCH_DELAY_MS = 180;

export function CardSearch() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GlobalSearchResult>({ cards: [], decks: [], opponents: [] });
  const [status, setStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');
  const [open, setOpen] = useState(false);
  const listId = useId();
  const wrapperRef = useRef<HTMLFormElement>(null);
  const trimmedQuery = query.trim();

  useEffect(() => {
    if (!trimmedQuery) {
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setStatus('loading');
      try {
        const nextResults = await fetchGlobalSearch(trimmedQuery, 6, controller.signal);
        setResults(nextResults);
        setStatus('loaded');
        setOpen(true);
      } catch (error: unknown) {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          setResults({ cards: [], decks: [], opponents: [] });
          setStatus('error');
          setOpen(true);
        }
      }
    }, SEARCH_DELAY_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [trimmedQuery]);

  const exactResult = useMemo(
    () =>
      results.cards.find(
        (result) => result.card_name.toLocaleLowerCase() === trimmedQuery.toLocaleLowerCase(),
      ),
    [results, trimmedQuery],
  );
  const totalResults = results.cards.length + results.decks.length + results.opponents.length;

  function closeSearch() {
    setQuery('');
    setResults({ cards: [], decks: [], opponents: [] });
    setStatus('idle');
    setOpen(false);
  }

  return (
    <form
      className="card-search"
      role="search"
      ref={wrapperRef}
      onBlur={(event) => {
        if (!wrapperRef.current?.contains(event.relatedTarget)) {
          setOpen(false);
        }
      }}
      onSubmit={(event) => {
        event.preventDefault();
        const result = exactResult ?? results.cards[0];
        if (result) {
          closeSearch();
          window.location.hash = cardRouteHash(result.card_name);
          return;
        }
        if (results.decks[0]) {
          const deckName = results.decks[0].deck_name;
          closeSearch();
          window.location.hash = deckRouteHash(deckName);
        }
      }}
    >
      <div className="card-search-control">
        <input
          id={`${listId}-input`}
          type="search"
          role="combobox"
          aria-label="Search by card or deck name"
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={open && Boolean(trimmedQuery)}
          autoComplete="off"
          placeholder="Search by card or deck name"
          value={query}
          onChange={(event) => {
            const nextQuery = event.target.value;
            setQuery(nextQuery);
            setOpen(Boolean(nextQuery.trim()));
            if (!nextQuery.trim()) {
              setResults({ cards: [], decks: [], opponents: [] });
              setStatus('idle');
            }
          }}
          onFocus={() => setOpen(Boolean(trimmedQuery))}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setOpen(false);
            }
          }}
        />
        <button type="submit" aria-label="Open first matching result" disabled={totalResults === 0}>
          Search
        </button>
      </div>
      {open && trimmedQuery ? (
        <div className="card-search-results" id={listId} role="listbox" aria-label="Matching cards, decks, and opponents">
          {status === 'loading' ? <p>Searching...</p> : null}
          {status === 'error' ? <p>Search is unavailable.</p> : null}
          {status === 'loaded' && totalResults === 0 ? <p>No matches found.</p> : null}
          {results.decks.map((deck) => (
            <a
              key={`deck-${deck.deck_name}`}
              aria-selected={false}
              href={deckRouteHash(deck.deck_name)}
              role="option"
              onClick={closeSearch}
            >
              <span className="card-search-result-name">{deck.deck_name}</span>
              <span className="card-search-result-kind">Deck</span>
              <span className="card-search-result-stats">
                {deck.games} {deck.games === 1 ? 'game' : 'games'}
              </span>
            </a>
          ))}
          {results.opponents.map((opponent) => (
            <a
              key={`opponent-${opponent.display_name}`}
              aria-selected={false}
              href={opponentRouteHash(opponent.display_name)}
              role="option"
              onClick={closeSearch}
            >
              <span className="card-search-result-name">{opponent.display_name}</span>
              <span className="card-search-result-kind">Opponent</span>
              <span className="card-search-result-stats">
                {opponent.games} {opponent.games === 1 ? 'game' : 'games'}
              </span>
            </a>
          ))}
          {results.cards.map((result) => (
            <CardLink
              key={result.card_name}
              cardName={result.card_name}
              role="option"
              aria-selected={false}
              onClick={closeSearch}
            >
              <span className="card-search-result-name">{formatCardName(result.card_name)}</span>
              <TypeChip type={result.type_category} />
              <span className="card-search-result-stats">
                {result.games_seen} {result.games_seen === 1 ? 'game' : 'games'} · {result.total_played} played
              </span>
            </CardLink>
          ))}
        </div>
      ) : null}
    </form>
  );
}
