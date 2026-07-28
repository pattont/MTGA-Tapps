import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { fetchCardSearch, type CardSearchResult } from '../api';
import { formatCardName } from '../format';
import { cardRouteHash } from '../routes';
import { CardLink } from './CardLink';
import { TypeChip } from './TypeChip';

const SEARCH_DELAY_MS = 180;

export function CardSearch() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CardSearchResult[]>([]);
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
        const nextResults = await fetchCardSearch(trimmedQuery, controller.signal);
        setResults(nextResults);
        setStatus('loaded');
        setOpen(true);
      } catch (error: unknown) {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          setResults([]);
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
    () => results.find((result) => result.card_name.toLocaleLowerCase() === trimmedQuery.toLocaleLowerCase()),
    [results, trimmedQuery],
  );

  function closeSearch() {
    setQuery('');
    setResults([]);
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
        const result = exactResult ?? results[0];
        if (result) {
          closeSearch();
          window.location.hash = cardRouteHash(result.card_name);
        }
      }}
    >
      <div className="card-search-control">
        <input
          id={`${listId}-input`}
          type="search"
          role="combobox"
          aria-label="Search by card name"
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={open && Boolean(trimmedQuery)}
          autoComplete="off"
          placeholder="Search by card name"
          value={query}
          onChange={(event) => {
            const nextQuery = event.target.value;
            setQuery(nextQuery);
            setOpen(Boolean(nextQuery.trim()));
            if (!nextQuery.trim()) {
              setResults([]);
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
        <button type="submit" aria-label="Open first matching card" disabled={results.length === 0}>
          Search
        </button>
      </div>
      {open && trimmedQuery ? (
        <div className="card-search-results" id={listId} role="listbox" aria-label="Matching tracked cards">
          {status === 'loading' ? <p>Searching tracked cards...</p> : null}
          {status === 'error' ? <p>Card search is unavailable.</p> : null}
          {status === 'loaded' && results.length === 0 ? <p>No tracked cards found.</p> : null}
          {results.map((result) => (
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
