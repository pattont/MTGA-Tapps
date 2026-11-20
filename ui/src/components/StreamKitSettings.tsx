import { useEffect, useId, useState } from 'react';
import { Copy, ExternalLink, Eye, Heart, Layers, Moon } from 'lucide-react';
import {
  DEFAULT_OPTIONS,
  readsOption,
  shows,
  TITLE_MAX,
  WIDGET_GROUPS,
  WIDGET_PARTS,
  widgetInfo,
  streamUrl,
  widgetSize,
  type StreamOptions,
  type WidgetId,
  type WidgetInfo,
} from '../stream/options';
import { STREAM_KIT_STORAGE_KEY } from '../stream/previewSync';
import { Section } from './Section';

/**
 * The Stream Kit page (#/stream-kit): builds the OBS browser-source links for
 * the widgets. The options live in each link, so this page only remembers
 * the choices in the browser for next time; the tracker stores nothing.
 */


const SCALES = [75, 100, 125, 150, 200];
const SECONDS = [5, 8, 12, 20];
const GAME_COUNTS = [1, 3, 5, 10, 15, 20, 25];

type Shared = Pick<StreamOptions, 'scale' | 'bg' | 'brand'>;
type PerWidget = Partial<Record<WidgetId, Partial<StreamOptions>>>;
interface Saved {
  /**
   * Size, background and credit were once set for every widget at once. Each
   * widget now has its own; these older choices stay its starting point, so
   * links made before keep their look.
   */
  shared: Shared;
  widgets: PerWidget;
}

function loadSaved(): Saved {
  const fallback: Saved = { shared: { scale: DEFAULT_OPTIONS.scale, bg: DEFAULT_OPTIONS.bg, brand: DEFAULT_OPTIONS.brand }, widgets: {} };
  try {
    const parsed = JSON.parse(localStorage.getItem(STREAM_KIT_STORAGE_KEY) ?? 'null') as Partial<Saved> | null;
    if (!parsed || typeof parsed !== 'object') return fallback;
    return { shared: { ...fallback.shared, ...parsed.shared }, widgets: { ...parsed.widgets } };
  } catch {
    return fallback;
  }
}

function Select<T extends string | number>({
  label,
  value,
  choices,
  onChange,
}: {
  label: string;
  value: T;
  choices: Array<[T, string]>;
  onChange: (value: T) => void;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <select
        value={String(value)}
        onChange={(event) => {
          const picked = choices.find(([choice]) => String(choice) === event.target.value);
          if (picked) onChange(picked[0]);
        }}
      >
        {choices.map(([choice, text]) => (
          <option key={String(choice)} value={String(choice)}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

function Range({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  const id = useId();
  return (
    <div className="settings-field stream-kit-range">
      <span>
        <label htmlFor={id}>{label}</label> <output htmlFor={id}>{value === 0 ? 'Off' : `${value}%`}</output>
      </span>
      <input id={id} max={100} min={0} step={5} type="range" value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </div>
  );
}

/** A group of checkboxes for a list option, kept in the option's own order. */
function Checks<T extends string>({
  label,
  all,
  value,
  names,
  onChange,
}: {
  label: string;
  all: readonly T[];
  value: T[];
  names: Record<T, string>;
  onChange: (value: T[]) => void;
}) {
  return (
    <fieldset className="settings-field stream-kit-checks">
      <legend>{label}</legend>
      {all.map((item) => (
        <label key={item} className="settings-check">
          <input
            checked={value.includes(item)}
            type="checkbox"
            onChange={(event) =>
              onChange(all.filter((other) => (other === item ? event.target.checked : value.includes(other))))
            }
          />
          {names[item]}
        </label>
      ))}
    </fieldset>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="settings-field stream-kit-wide">
      <span>{label}</span>
      <input maxLength={TITLE_MAX} type="text" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

const OPPONENT_NAME = 'opponent-name';

/**
 * The widget's optional parts as "Show" checkboxes. The link stores the ones
 * turned off (`hide`), so a new part shows on links made before it existed.
 */
function ShowParts({
  widget,
  options,
  onChange,
}: {
  widget: WidgetInfo;
  options: StreamOptions;
  onChange: (patch: Partial<StreamOptions>) => void;
}) {
  const parts = WIDGET_PARTS[widget.id];
  // The opponent's name has its own link option (`opponent`), kept from 0.7.5.
  const name = widget.options.includes('opponent') ? [[OPPONENT_NAME, 'Opponent name'] as const] : [];
  const items = [...name, ...parts];
  if (items.length === 0) return null;
  const all = items.map(([part]) => part);
  const own = parts.map(([part]) => part);
  return (
    <Checks
      label="Show"
      all={all}
      value={all.filter((part) => (part === OPPONENT_NAME ? options.opponent : shows(options, part)))}
      names={Object.fromEntries(items)}
      onChange={(visible) =>
        onChange({
          ...(name.length > 0 ? { opponent: visible.includes(OPPONENT_NAME) } : {}),
          hide: own.filter((part) => !visible.includes(part)),
        })
      }
    />
  );
}

function WidgetOptions({
  widget,
  options,
  onChange,
}: {
  widget: WidgetInfo;
  options: StreamOptions;
  onChange: (patch: Partial<StreamOptions>) => void;
}) {
  const idle = widget.options.includes('idle') ? (
    <Select
      label="Between games"
      value={options.idle}
      choices={[
        ['hide', 'Hide'],
        ['show', 'Keep last game'],
      ]}
      onChange={(idle) => onChange({ idle })}
    />
  ) : null;
  const order = (
    <Select
      label="Order"
      value={options.sort}
      choices={[
        ['mana', 'Mana value'],
        ['odds', 'Draw odds'],
        ['name', 'Name'],
      ]}
      onChange={(sort) => onChange({ sort })}
    />
  );
  switch (widget.id) {
    case 'overlay':
      return (
        <>
          <Range label="Background" value={options.opacity} onChange={(opacity) => onChange({ opacity })} />
          <Select
            label="Sideboard"
            value={options.sideboard}
            choices={[
              ['right', 'Right'],
              ['left', 'Left'],
              ['below', 'Below'],
              ['off', 'Hide'],
            ]}
            onChange={(sideboard) => onChange({ sideboard })}
          />
          {order}
          <Select
            label="Lands"
            value={options.lands}
            choices={[
              ['grouped', 'One row'],
              ['all', 'Each land'],
            ]}
            onChange={(lands) => onChange({ lands })}
          />
          <Select
            label="Card names"
            value={options.names}
            choices={[
              ['type', 'Type colors'],
              ['white', 'White'],
            ]}
            onChange={(names) => onChange({ names })}
          />
          {idle}
        </>
      );
    case 'deck':
      return (
        <>
          {order}
          <Select
            label="Lands"
            value={options.lands}
            choices={[
              ['grouped', 'One row'],
              ['all', 'Each land'],
            ]}
            onChange={(lands) => onChange({ lands })}
          />
          {idle}
        </>
      );
    case 'games':
      return (
        <>
          <Select
            label="Games shown"
            value={options.count}
            choices={GAME_COUNTS.map((count) => [count, count === 1 ? 'Last game only' : `Last ${count}`] as [number, string])}
            onChange={(count) => onChange({ count })}
          />
        </>
      );
    case 'matchup':
      return (
        <>
          {idle}
        </>
      );
    case 'scorebug':
      return (
        <>
          {idle}
        </>
      );
    case 'record':
      return null;
    case 'deckstats':
      return idle;
    case 'opponent':
      return (
        <>
          <Select
            label="Lands"
            value={options.lands}
            choices={[
              ['grouped', 'One line'],
              ['all', 'With the cards'],
            ]}
            onChange={(lands) => onChange({ lands })}
          />
          {idle}
        </>
      );
    case 'lands':
      return idle;
    case 'result':
      return (
        <>
          <Select
            label="Show for"
            value={options.seconds}
            choices={SECONDS.map((seconds) => [seconds, `${seconds} seconds`] as [number, string])}
            onChange={(seconds) => onChange({ seconds })}
          />
        </>
      );
    case 'break':
      return (
        <>
          <TextField label="Title" value={options.title} onChange={(title) => onChange({ title })} />
        </>
      );
    case 'spotlight':
      return (
        <>
          <Select
            label="Cards from"
            value={options.who}
            choices={[
              ['both', 'Both players'],
              ['opponent', 'Opponent only'],
              ['you', 'You only'],
            ]}
            onChange={(who) => onChange({ who })}
          />
          <Select
            label="Show for"
            value={options.seconds}
            choices={SECONDS.map((seconds) => [seconds, `${seconds} seconds`] as [number, string])}
            onChange={(seconds) => onChange({ seconds })}
          />
        </>
      );
    default:
      return null;
  }
}

/** Size and background, per widget. The full overlay has its own background slider. */
function LookOptions({
  widget,
  options,
  onChange,
}: {
  widget: WidgetInfo;
  options: StreamOptions;
  onChange: (patch: Partial<StreamOptions>) => void;
}) {
  return (
    <>
      {readsOption(widget, 'scale') ? (
        <Select
          label="Size"
          value={options.scale}
          choices={SCALES.map((scale) => [scale, `${scale}%`] as [number, string])}
          onChange={(scale) => onChange({ scale })}
        />
      ) : null}
      {readsOption(widget, 'bg') ? (
        <Select
          label="Background"
          value={options.bg}
          choices={[
            ['solid', 'Solid'],
            ['glass', 'See-through'],
            ['none', 'None'],
          ]}
          onChange={(bg) => onChange({ bg })}
        />
      ) : null}
    </>
  );
}

function WidgetCard({
  widget,
  options,
  origin,
  onChange,
}: {
  widget: WidgetInfo;
  options: StreamOptions;
  origin: string;
  onChange: (patch: Partial<StreamOptions>) => void;
}) {
  const [copied, setCopied] = useState(false);
  const url = streamUrl(origin, widget.id, options);
  const size = widgetSize(widget, options);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Clipboard refused (permissions): the link stays selectable in the field.
    }
  };

  return (
    <article className={`stream-kit-widget stream-kit-widget-${widget.id}`} aria-label={widget.title}>
      <div className="stream-kit-widget-head">
        <h4>{widget.title}</h4>
        <span className="stream-kit-size" title="Suggested browser-source size">
          {size.width} × {size.height}
        </span>
      </div>
      <p className="settings-hint">{widget.description}</p>
      <div className="stream-kit-options">
        <LookOptions widget={widget} options={options} onChange={onChange} />
        <WidgetOptions widget={widget} options={options} onChange={onChange} />
        <ShowParts widget={widget} options={options} onChange={onChange} />
      </div>
      <div className="stream-kit-link">
        <input
          aria-label={`${widget.title} link`}
          readOnly
          spellCheck={false}
          type="text"
          value={url}
          onFocus={(event) => event.target.select()}
        />
        <button type="button" className="deck-export-button" onClick={() => void copy()}>
          <Copy aria-hidden="true" />
          {copied ? 'Copied' : 'Copy link'}
        </button>
        <a
          className="deck-neutral-button"
          href={streamUrl(origin, widget.id, options, { demo: true, preview: true })}
          rel="noreferrer"
          target="_blank"
          title="Open this widget with sample data"
        >
          <ExternalLink aria-hidden="true" />
          Preview
        </a>
        {readsOption(widget, 'brand') ? (
          <label className="settings-check stream-kit-credit">
            <input checked={options.brand} type="checkbox" onChange={(event) => onChange({ brand: event.target.checked })} />
            Show “Tapps Tracker” credit
          </label>
        ) : null}
      </div>
    </article>
  );
}

export function StreamKitSettings({ origin = window.location.origin }: { origin?: string }) {
  const [saved, setSaved] = useState<Saved>(loadSaved);

  useEffect(() => {
    try {
      localStorage.setItem(STREAM_KIT_STORAGE_KEY, JSON.stringify(saved));
    } catch {
      // Private mode or full storage: the choices just aren't remembered.
    }
  }, [saved]);

  const setWidget = (id: WidgetId, patch: Partial<StreamOptions>) =>
    setSaved((current) => ({ ...current, widgets: { ...current.widgets, [id]: { ...current.widgets[id], ...patch } } }));

  return (
    <>
      <Section
        id="stream-kit-start"
        title="Getting started"
        description="Widgets for OBS and Streamlabs that show viewers your game. Each one is a link you add as a source."
      >
        <div className="stream-kit-start">
          <ol className="stream-kit-steps">
            <li>
              <span className="stream-kit-step-number">1</span>
              <span>
                <strong>Pick a widget</strong>
                <span>Set its size, look and what it shows.</span>
              </span>
            </li>
            <li>
              <span className="stream-kit-step-number">2</span>
              <span>
                <strong>Copy its link</strong>
                <span>With <em>Copy link</em> under the widget.</span>
              </span>
            </li>
            <li>
              <span className="stream-kit-step-number">3</span>
              <span>
                <strong>Add it to OBS</strong>
                <span>As a <em>Browser</em> source, at the size shown.</span>
              </span>
            </li>
          </ol>
          <ul className="stream-kit-tips">
            <li>
              <Eye aria-hidden="true" />
              <span>
                <strong>Preview</strong> shows a widget with sample data and follows your changes while it’s open. Widgets
                are see-through and appear only when there’s something to show.
              </span>
            </li>
            <li>
              <Layers aria-hidden="true" />
              <span>
                <strong>Using more than one widget?</strong> Some show the same thing, like the turn number or your
                record. Untick it in one widget’s <strong>Show</strong> list so it appears on screen only once.
              </span>
            </li>
            <li>
              <Moon aria-hidden="true" />
              <span>
                <strong>Not streaming?</strong> Nothing here runs until a widget is open in OBS or a browser, so it costs
                no memory, CPU or network.
              </span>
            </li>
          </ul>
        </div>
      </Section>
      {WIDGET_GROUPS.map((group) => (
        <div key={group.id} className="settings-group stream-kit-group" id={group.id}>
          <h2 className="settings-group-heading">{group.title}</h2>
          <div className="stream-kit-widgets">
            {group.widgets.map((id) => {
              const widget = widgetInfo(id);
              return (
                <WidgetCard
                  key={id}
                  widget={widget}
                  origin={origin}
                  options={{ ...DEFAULT_OPTIONS, ...saved.shared, ...saved.widgets[id] }}
                  onChange={(patch) => setWidget(id, patch)}
                />
              );
            })}
          </div>
        </div>
      ))}
      <p className="stream-kit-thanks">
        <Heart aria-hidden="true" />
        <span>
          Thank you, <strong>MrNaosu</strong>, for the amazing Stream Kit idea!
        </span>
      </p>
    </>
  );
}
