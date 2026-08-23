import { useEffect, useState } from 'react';
import {
  fetchTrackerSettings,
  saveDeckAiSettings,
  saveDeckFinderCreators,
  type DeckAiSettings,
  type DeckFinderCreator,
  type DeckFinderCreatorSettings,
} from '../api';
import { Section } from './Section';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const CREATOR_SITES = [
  ['moxfield', 'Moxfield'],
  ['aetherhub', 'Aetherhub'],
  ['tcgplayer', 'TCGplayer'],
] as const;

function creatorLines(creators: DeckFinderCreator[]): string {
  return creators
    .map((creator) =>
      creator.short_name ? `${creator.name} | ${creator.short_name}` : creator.name,
    )
    .join('\n');
}

function parseCreatorLines(text: string): DeckFinderCreator[] {
  return text
    .split('\n')
    .map((line) => {
      const [name, short] = line.split('|', 2).map((part) => part.trim());
      return { name: name ?? '', short_name: short || null };
    })
    .filter((creator) => creator.name.length > 0);
}

function saveLabel(status: SaveStatus, idle: string): string {
  if (status === 'saving') {
    return 'Saving…';
  }
  if (status === 'saved') {
    return 'Saved';
  }
  if (status === 'error') {
    return 'Save Failed';
  }
  return idle;
}

export function SettingsPage() {
  const [error, setError] = useState<string | null>(null);
  const [deckAi, setDeckAi] = useState<DeckAiSettings | null>(null);
  const [creators, setCreators] = useState<DeckFinderCreatorSettings | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTrackerSettings()
      .then((settings) => {
        if (!cancelled) {
          setDeckAi(settings.deck_ai);
          setCreators(settings.deck_finder);
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : 'Settings failed to load');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <Section
        id="settings-deck-ai"
        title="Deck AI"
        description="Identify your opponent's deck with an AI provider. One small, cheap request per completed game — tracking never waits on it. The key is stored locally in settings.json and only ever sent to the provider you choose."
      >
        {error ? (
          <p className="empty-state deckfinder-state">{error}</p>
        ) : deckAi === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading settings...
          </p>
        ) : (
          <DeckAiForm initial={deckAi} />
        )}
      </Section>

      <Section
        id="settings-creators"
        title="Deck Finder Creators"
        description="Which creators the Deck Finder's Moxfield, Aetherhub, and TCGplayer sites follow. One creator per line. Add a short display name after a pipe — “Ashlizzlle | Ash” makes imported decks show up as “Jeskai Artifacts (Ash)” in Arena."
      >
        {error ? null : creators === null ? (
          <p className="state-panel deckfinder-state" role="status" aria-busy="true">
            Loading creators...
          </p>
        ) : (
          <CreatorsForm initial={creators} />
        )}
      </Section>

      <Section
        id="settings-db-health"
        title="Database Health"
        description="Audit the tracker database for incomplete or suspicious games, review findings, and reset data if something went wrong."
      >
        <div className="settings-form">
          <div>
            <a className="deck-export-button settings-link-button" href="#/audit">
              Open Database Health
            </a>
          </div>
        </div>
      </Section>
    </>
  );
}

function DeckAiForm({ initial }: { initial: DeckAiSettings }) {
  const [enabled, setEnabled] = useState(initial.enabled);
  const [provider, setProvider] = useState(initial.provider);
  const [keys, setKeys] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.providers.map((entry) => [entry.key, entry.api_key])),
  );
  const [models, setModels] = useState<Record<string, string>>(() =>
    Object.fromEntries(initial.providers.map((entry) => [entry.key, entry.model])),
  );
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<SaveStatus>('idle');

  const active = initial.providers.find((entry) => entry.key === provider) ?? initial.providers[0];

  async function save() {
    setStatus('saving');
    try {
      await saveDeckAiSettings({ enabled, provider, keys, models });
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 1800);
    } catch {
      setStatus('error');
    }
  }

  return (
    <div className="settings-form">
      <label className="settings-check">
        <input
          checked={enabled}
          type="checkbox"
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enable AI deck identification
      </label>

      <label className="settings-field">
        <span>Provider</span>
        <select value={provider} onChange={(event) => setProvider(event.target.value)}>
          {initial.providers.map((entry) => (
            <option key={entry.key} value={entry.key}>
              {entry.label}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-field">
        <span>API key</span>
        <div className="settings-key-row">
          <input
            autoComplete="off"
            placeholder="API key"
            spellCheck={false}
            type={showKey ? 'text' : 'password'}
            value={keys[provider] ?? ''}
            onChange={(event) =>
              setKeys((current) => ({ ...current, [provider]: event.target.value }))
            }
          />
          <button
            className="quick-filter"
            type="button"
            onClick={() => setShowKey((current) => !current)}
          >
            {showKey ? 'Hide' : 'Show'}
          </button>
        </div>
      </label>

      <label className="settings-field">
        <span>Model</span>
        <input
          placeholder={active?.default_model ?? ''}
          spellCheck={false}
          type="text"
          value={models[provider] ?? ''}
          onChange={(event) =>
            setModels((current) => ({ ...current, [provider]: event.target.value }))
          }
        />
      </label>

      <div>
        <button
          className="deck-export-button"
          disabled={status === 'saving'}
          type="button"
          onClick={() => void save()}
        >
          {saveLabel(status, 'Save Deck AI Settings')}
        </button>
      </div>
    </div>
  );
}

function CreatorsForm({ initial }: { initial: DeckFinderCreatorSettings }) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => ({
    moxfield: creatorLines(initial.moxfield),
    aetherhub: creatorLines(initial.aetherhub),
    tcgplayer: creatorLines(initial.tcgplayer),
  }));
  const [status, setStatus] = useState<SaveStatus>('idle');

  async function save() {
    setStatus('saving');
    try {
      await saveDeckFinderCreators({
        moxfield: parseCreatorLines(drafts.moxfield ?? ''),
        aetherhub: parseCreatorLines(drafts.aetherhub ?? ''),
        tcgplayer: parseCreatorLines(drafts.tcgplayer ?? ''),
      });
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 1800);
    } catch {
      setStatus('error');
    }
  }

  return (
    <div className="settings-form">
      {CREATOR_SITES.map(([key, label]) => {
        const value = drafts[key] ?? '';
        // Size the editor to its content so nothing scrolls out of view.
        const rows = Math.max(value.split('\n').length + 1, 3);
        return (
          <label key={key} className="settings-field">
            <span>{label}</span>
            <textarea
              placeholder={'CreatorName | Short name'}
              rows={rows}
              spellCheck={false}
              value={value}
              onChange={(event) =>
                setDrafts((current) => ({ ...current, [key]: event.target.value }))
              }
            />
          </label>
        );
      })}
      <div>
        <button
          className="deck-export-button"
          disabled={status === 'saving'}
          type="button"
          onClick={() => void save()}
        >
          {saveLabel(status, 'Save Creators')}
        </button>
      </div>
    </div>
  );
}
