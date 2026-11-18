import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { HOVER_CARD_WIDTH, RAIL_BOOST, cardImageUrl, tintAlpha } from './App';
import { OpponentPanel } from './components/OpponentPanel';
import { OpponentRail } from './components/OpponentRail';
import { freshPlays, opponentOf } from './opponentModel';
import { OverlayPoller } from './poll';
import { isTauri, log, tauri } from './tauri';
import type { LayoutInfo, OpponentCard, OverlayPayload, Settings } from './types';

/** How long a new play stays highlighted (and the folded rail pulses). */
export const FRESH_MS = 4000;

/** Height of the opponent hover card: the card image plus its two lines. */
const HOVER_CARD_HEIGHT = Math.round((HOVER_CARD_WIDTH * 680) / 488) + 58;

/** The panel's natural height: every block at its own height and the card
    list unscrolled. The panel itself fills the window, so (unlike the deck
    panel's) its height says nothing; summing the blocks lets a short list,
    or nothing played yet, shrink the window. */
export function opponentPanelHeight(panel: HTMLElement): number {
  let total = 0;
  for (const child of Array.from(panel.children) as HTMLElement[]) {
    if (child.classList.contains('list')) {
      const body = child.querySelector<HTMLElement>('.list-body');
      let padding = 0;
      if (typeof getComputedStyle === 'function') {
        const style = getComputedStyle(child);
        padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
      }
      total += (body ? body.offsetHeight : child.scrollHeight) + padding;
    } else {
      total += child.offsetHeight;
    }
  }
  return Math.ceil(total);
}

interface HoverCard {
  card: OpponentCard;
  top: number;
}

/**
 * The opponent window: its rail or its panel, docked on the edge opposite
 * the deck panel. It never polls in the app: the deck page shares each
 * `/api/overlay` body through the shell (`share_payload`), so both windows
 * show the same moment, and the shell shows this window only while a game
 * is on screen. In a browser (vitest, `vite dev`, screenshots) it polls on
 * its own.
 */
export function OpponentApp() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [layout, setLayout] = useState<LayoutInfo>({ layout: 'rail', pinned: true, panelOpen: false, visible: true, dock: 'right' });
  const [payload, setPayload] = useState<OverlayPayload | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [hover, setHover] = useState<HoverCard | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [pulse, setPulse] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const lastHeight = useRef<number | null>(null);

  // --- shell wiring -------------------------------------------------------
  useEffect(() => {
    let disposed = false;
    const unlisteners: Array<() => void> = [];
    (async () => {
      const [initial, current] = await Promise.all([tauri.invoke<Settings>('get_settings'), tauri.invoke<LayoutInfo>('get_layout')]);
      if (disposed) return;
      log(`opponent window ready: layout=${current.layout} visible=${current.visible}`);
      setSettings(initial);
      setLayout(current);
      unlisteners.push(
        await tauri.listen<LayoutInfo>('overlay-layout', (info) => {
          setLayout(info);
          if (info.layout === 'rail') setHover(null);
        }),
        await tauri.listen<{ x: number; y: number } | null>('overlay-cursor', (point) => setCursor(point)),
        await tauri.listen<Settings>('overlay-settings', (next) => setSettings(next)),
        await tauri.listen<OverlayPayload | null>('overlay-payload', (next) => setPayload(next)),
      );
      if (isTauri()) {
        // A window built mid-game starts from the deck page's last body.
        const latest = await tauri.invoke<OverlayPayload | null>('latest_payload');
        if (!disposed && latest) setPayload(latest);
      }
    })();
    return () => {
      disposed = true;
      for (const off of unlisteners) off();
    };
  }, []);

  // Outside the app there is no deck page to share with this one.
  useEffect(() => {
    if (!settings || isTauri()) return;
    const poller = new OverlayPoller(settings.apiUrl, { onPayload: setPayload, onLink: () => undefined });
    poller.start();
    return () => poller.stop();
  }, [settings?.apiUrl]);

  const opponent = opponentOf(payload);

  // --- new plays: a moment's highlight, and a pulse on the folded rail ------
  // Between games the block is gone, so a new game starts from nothing.
  const lastSeen = useRef<OpponentCard[] | null>(null);
  useEffect(() => {
    const cards = opponent?.seen ?? [];
    const before = lastSeen.current;
    lastSeen.current = opponent ? cards : null;
    // The first look at a game is the game so far, not news.
    const changed = freshPlays(before, cards);
    if (changed.length === 0) return undefined;
    const known = new Set(before?.map((card) => card.name));
    setFresh(new Set(changed));
    setPulse(changed.some((name) => !known.has(name)));
    const timer = setTimeout(() => {
      setFresh(new Set());
      setPulse(false);
    }, FRESH_MS);
    return () => clearTimeout(timer);
  }, [opponent?.seen]);

  // --- layout commands -------------------------------------------------------
  const openPanel = useCallback(async () => {
    setLayout(await tauri.invoke<LayoutInfo>('set_layout', { layout: 'panel', contentHeight: lastHeight.current, auto: false }));
  }, []);
  const collapse = useCallback(async () => {
    setHover(null);
    setLayout(await tauri.invoke<LayoutInfo>('set_layout', { layout: 'rail', contentHeight: null, auto: false }));
  }, []);
  const togglePin = useCallback(async () => {
    setLayout(await tauri.invoke<LayoutInfo>('set_pinned', { pinned: !layout.pinned }));
  }, [layout.pinned]);
  const dragStart = useCallback((event: MouseEvent) => {
    if (event.button !== 0) return;
    event.preventDefault();
    void tauri.startDragging();
  }, []);

  // The window follows the panel's natural height (see App).
  useEffect(() => {
    if (layout.layout !== 'panel') return;
    const root = rootRef.current;
    if (!root || typeof ResizeObserver === 'undefined') return;
    const report = () => {
      const panel = root.querySelector<HTMLElement>('.panel');
      if (!panel) return;
      const height = opponentPanelHeight(panel);
      if (height !== lastHeight.current) {
        lastHeight.current = height;
        void tauri.invoke('set_content_height', { height });
      }
    };
    const observer = new ResizeObserver(report);
    for (const selector of ['.panel', '.list-body', '.opp-band']) {
      const el = root.querySelector<HTMLElement>(selector);
      if (el) observer.observe(el);
    }
    report();
    return () => observer.disconnect();
  }, [layout.layout, payload, settings?.lands, settings?.density, settings?.scale]);

  const onHover = useCallback((card: OpponentCard | null, box: { top: number; bottom: number } | null) => {
    setHover((current) => {
      if (!card || !box) return current === null ? current : null;
      if (current && current.card.name === card.name && current.top === box.top) return current;
      return { card, top: box.top };
    });
  }, []);

  const hoverStyle = useMemo(() => {
    if (!hover) return undefined;
    const viewport = typeof window !== 'undefined' ? window.innerHeight : 600;
    return { top: `${Math.max(2, Math.min(hover.top, viewport - HOVER_CARD_HEIGHT - 2))}px` };
  }, [hover]);

  if (!settings) return <div ref={rootRef} class="root" />;

  const dock = layout.dock === 'left' ? 'left' : 'right';
  // The gutter is on the board side, away from the docked edge.
  const side = dock === 'left' ? 'right' : 'left';
  const isPanel = layout.layout === 'panel';
  const alpha = isPanel ? settings.opacity : settings.railOpacity;

  return (
    <div
      ref={rootRef}
      class={`root opp-root dock-${dock} ${isPanel ? 'is-panel' : 'is-rail'} ${alpha > 0 ? 'has-bg' : 'no-bg'} names-${settings.nameColor}`}
      style={{ '--tint-alpha': tintAlpha(settings.opacity), '--rail-alpha': tintAlpha(settings.railOpacity), '--scale': (settings.scale / 100) * (isPanel ? 1 : RAIL_BOOST), '--rail-boost': RAIL_BOOST } as never}
    >
      {isPanel ? (
        <>
          <OpponentPanel
            payload={payload}
            opponent={opponent}
            settings={settings}
            pinned={layout.pinned}
            dock={dock}
            fresh={fresh}
            onCollapse={() => void collapse()}
            onTogglePin={() => void togglePin()}
            onOpenSettings={settings.deckPanel ? undefined : () => void tauri.invoke('open_settings')}
            onDragStart={dragStart}
            onHover={onHover}
            cursor={cursor}
          />
          <div class={`gutter side-${side}`}>
            {hover ? (
              <div class="hover" style={hoverStyle} role="tooltip">
                <img class="card-img" src={cardImageUrl(hover.card.name)} alt="" draggable={false} onError={(event) => ((event.currentTarget as HTMLImageElement).style.display = 'none')} />
                <b>{hover.card.name}</b>
                <div class="r">
                  <span>{hover.card.type}</span>
                  <span>{hover.card.count > 1 ? `Played ×${hover.card.count}` : 'Played'}</span>
                </div>
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <div class="rail-host">
          <OpponentRail opponent={opponent} dock={dock} pulse={pulse} onOpenPanel={() => void openPanel()} onDragStart={dragStart} />
        </div>
      )}
    </div>
  );
}
