import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { Flyout } from './components/Flyout';
import { Panel } from './components/Panel';
import { Rail } from './components/Rail';
import { formatPct, typeClass, type Row } from './model';
import { ManaCost } from './components/ManaCost';
import { OverlayPoller } from './poll';
import { log, tauri } from './tauri';
import type { Link, LayoutInfo, OverlayPayload, Settings, SortKey } from './types';

/** Dwell on the rail before the panel flies out. */
/** Panel chrome (header + strip + tools) never scrolls; the list does. */
const PANEL_MIN_HEIGHT = 160;

interface HoverCard {
  row: Row;
  /** The hovered row's box, in window coordinates. */
  top: number;
  bottom: number;
}

/** Height of the hover card: the card image (184 wide at 488:680) plus the odds block. */
const HOVER_CARD_HEIGHT = 256 + 98;
/** The hover card hides itself this long after the last row it was shown for. */
export const HOVER_LINGER_MS = 2500;
/** The minimised rail draws a step larger than the panel at the same Scale setting. */
export const RAIL_BOOST = 1.2;

/** Card top: level with the row, kept whole inside the window. */
export function hoverCardTop(rowTop: number, _rowBottom: number, viewportHeight: number): number {
  return Math.max(2, Math.min(rowTop, viewportHeight - HOVER_CARD_HEIGHT - 2));
}

/** Scryfall's image for a card by exact name (the front face of a double-faced card). */
export function cardImageUrl(name: string): string {
  return `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(name)}&format=image&version=normal`;
}

function verticalPadding(element: HTMLElement | null): number {
  if (!element || typeof getComputedStyle !== 'function') return 0;
  try {
    const style = getComputedStyle(element);
    return (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
  } catch {
    return 0;
  }
}

/**
 * The background slider → charcoal alpha. Text is never faded; only the
 * ground is. Tops out at 88 % so the board still shows through a little at
 * 100, and the curve keeps the default (60) reasonably dark (≈72 %) with
 * room above it.
 */
export function tintAlpha(slider: number): number {
  const v = Math.max(0, Math.min(1, slider));
  return Math.round(0.88 * Math.pow(v, 0.4) * 1000) / 1000;
}

/** Where the hover card goes: toward the board, i.e. away from the docked edge. */
export function hoverSide(dock: Settings['dock']): 'left' | 'right' {
  return dock === 'left' ? 'right' : 'left';
}

/**
 * Natural height of the panel: chrome plus the full (unscrolled) list — or,
 * while the settings flyout is open, enough for the flyout to show whole.
 */
export function measureContentHeight(panel: HTMLElement, list: HTMLElement | null, flyout: HTMLElement | null = null): number {
  const listVisible = list ? list.clientHeight : 0;
  // The list's own scrollHeight is never smaller than its visible height,
  // so a window that opened tall would never shrink; measure the rows.
  const body = list?.querySelector<HTMLElement>('.list-body') ?? null;
  const listFull = body ? body.offsetHeight + verticalPadding(list) : list ? list.scrollHeight : 0;
  const chrome = panel.offsetHeight - listVisible;
  const natural = Math.ceil(chrome + listFull);
  const forFlyout = flyout ? Math.ceil(flyout.offsetTop + flyout.scrollHeight + 10) : 0;
  return Math.max(PANEL_MIN_HEIGHT, natural, forFlyout);
}

export function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [platform, setPlatform] = useState('windows');
  const [layout, setLayout] = useState<LayoutInfo>({ layout: 'rail', pinned: true, visible: true, dock: 'right' });
  const [payload, setPayload] = useState<OverlayPayload | null>(null);
  const [link, setLink] = useState<Link>('connecting');
  const [sort, setSort] = useState<SortKey>('odds');
  const [hover, setHover] = useState<HoverCard | null>(null);
  const [flyout, setFlyout] = useState(false);
  const [sideboardOpen, setSideboardOpen] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const pollerRef = useRef<OverlayPoller | null>(null);
  /** Last height reported to the shell, so re-opening the panel lands at the right size at once. */
  const lastHeight = useRef<number | null>(null);
  const layoutRef = useRef(layout);
  layoutRef.current = layout;

  // --- shell wiring -------------------------------------------------------
  useEffect(() => {
    let disposed = false;
    const unlisteners: Array<() => void> = [];
    (async () => {
      const [initial, os, current] = await Promise.all([
        tauri.invoke<Settings>('get_settings'),
        tauri.invoke<string>('platform'),
        tauri.invoke<LayoutInfo>('get_layout'),
      ]);
      if (disposed) return;
      log(`shell ready: platform=${os} layout=${current.layout} visible=${current.visible} api=${initial.apiUrl}`);
      setSettings(initial);
      setPlatform(os);
      setLayout(current);
      unlisteners.push(
        await tauri.listen<LayoutInfo>('overlay-layout', (info) => {
          setLayout(info);
          if (info.layout === 'rail') setHover(null);
        }),
        await tauri.listen<void>('overlay-open-settings', () => {
          setFlyout(true);
          if (layoutRef.current.layout === 'rail') {
            void tauri.invoke<LayoutInfo>('set_layout', { layout: 'panel', contentHeight: null }).then(setLayout);
          }
        }),
      );
    })();
    return () => {
      disposed = true;
      for (const off of unlisteners) off();
    };
  }, []);

  // --- polling --------------------------------------------------------------
  useEffect(() => {
    if (!settings) return;
    if (!pollerRef.current) {
      pollerRef.current = new OverlayPoller(settings.apiUrl, {
        onPayload: setPayload,
        onLink: (next) => {
          log(`tracker link: ${next}`);
          setLink(next);
        },
      });
    } else {
      pollerRef.current.setBaseUrl(settings.apiUrl);
    }
  }, [settings?.apiUrl, settings]);

  useEffect(() => {
    const poller = pollerRef.current;
    if (!poller) return;
    // A hidden overlay does no work at all; a shown one resumes immediately.
    if (layout.visible) {
      poller.start();
      poller.kick();
    } else {
      poller.stop();
    }
  }, [layout.visible, settings]);

  useEffect(() => () => pollerRef.current?.stop(), []);

  // --- layout commands -------------------------------------------------------
  const contentHeight = useCallback(() => {
    const root = rootRef.current;
    const panel = root?.querySelector<HTMLElement>('.panel');
    if (!panel) return null;
    return measureContentHeight(panel, panel.querySelector<HTMLElement>('.list'), root?.querySelector<HTMLElement>('.fly') ?? null);
  }, []);

  /** Open the panel; `pinned` overrides the "open pinned" setting (null = follow it). */
  const openPanel = useCallback(async (pinned: boolean | null = null) => {
    const info = await tauri.invoke<LayoutInfo>('set_layout', { layout: 'panel', contentHeight: lastHeight.current, pinned });
    setLayout(info);
  }, []);

  const collapse = useCallback(async () => {
    setHover(null);
    setFlyout(false);
    setSideboardOpen(false);
    const info = await tauri.invoke<LayoutInfo>('set_layout', { layout: 'rail', contentHeight: null });
    setLayout(info);
  }, []);

  const togglePin = useCallback(async () => {
    const info = await tauri.invoke<LayoutInfo>('set_pinned', { pinned: !layoutRef.current.pinned });
    setLayout(info);
  }, []);

  const updateSettings = useCallback(async (next: Settings) => {
    setSettings(next);
    const saved = await tauri.invoke<Settings>('update_settings', { settings: next });
    setSettings(saved);
  }, []);

  const quit = useCallback(() => void tauri.invoke('quit_overlay'), []);

  const dragStart = useCallback((event: MouseEvent) => {
    if (event.button !== 0) return;
    event.preventDefault();
    void tauri.startDragging();
  }, []);

  // Report the panel's natural height whenever its content changes so the
  // window grows with the decklist and shrinks between games.
  useEffect(() => {
    if (layout.layout !== 'panel') return;
    const root = rootRef.current;
    if (!root || typeof ResizeObserver === 'undefined') return;
    const report = () => {
      const height = contentHeight();
      // Only a real change reaches the shell: every report re-docks the window.
      if (height !== null && height !== lastHeight.current) {
        lastHeight.current = height;
        void tauri.invoke('set_content_height', { height });
      }
    };
    const observer = new ResizeObserver(report);
    const list = root.querySelector<HTMLElement>('.list');
    const body = root.querySelector<HTMLElement>('.list-body');
    const panel = root.querySelector<HTMLElement>('.panel');
    const fly = root.querySelector<HTMLElement>('.fly');
    if (panel) observer.observe(panel);
    if (fly) observer.observe(fly);
    if (body) observer.observe(body);
    else if (list) for (const child of Array.from(list.children)) observer.observe(child);
    report();
    return () => observer.disconnect();
  }, [layout.layout, payload, settings?.lands, settings?.density, settings?.scale, sort, flyout, contentHeight]);

  // Between games the panel folds back into the rail on its own; when the
  // next game starts it comes back the way it was (open, and pinned or not).
  const restoreAfterGame = useRef<{ pinned: boolean } | null>(null);
  const wasActive = useRef<boolean | null>(null);
  // "Active" for the fold-away rule includes the results screen: the
  // final library stays up until Arena leaves it (game_over clears).
  const gameActive = Boolean(payload?.state && (payload.state.game_active || payload.state.game_over) && !payload.state.mid_game_attach);
  useEffect(() => {
    const before = wasActive.current;
    wasActive.current = gameActive;
    if (before === null || before === gameActive) return;
    if (!gameActive) {
      if (layoutRef.current.layout === 'panel') {
        restoreAfterGame.current = { pinned: layoutRef.current.pinned };
        void collapse();
      }
    } else if (restoreAfterGame.current) {
      const { pinned } = restoreAfterGame.current;
      restoreAfterGame.current = null;
      void openPanel(pinned);
    }
  }, [gameActive, collapse, openPanel]);

  // The shell owns hovering: it watches the real cursor (the page's mouse
  // events are unreliable in a never-key overlay window), opens the panel
  // unpinned when the rail is hovered and folds an unpinned panel away once
  // the cursor has been off it for the return delay. It needs to know what
  // the page has flown out: the ⚙ flyout holds the panel open, and the
  // sideboard makes the gutter count as "over the panel". The flyout
  // closing also hands a window the tracker's menu forced open back to the
  // Arena rule.
  useEffect(() => {
    void tauri.invoke('set_page_open', { flyout, sideboard: sideboardOpen });
  }, [flyout, sideboardOpen]);

  const onPointerLeave = useCallback(() => setHover(null), []);

  // --- hover card ----------------------------------------------------------
  // Shown for the row under the cursor and gone HOVER_LINGER_MS after the
  // last row it was shown for: mouseleave is not reliable in this window,
  // so the card must not depend on it to go away.
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onHover = useCallback((row: Row | null, box: { top: number; bottom: number } | null) => {
    if (hoverTimer.current) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    if (row && box) {
      setHover({ row, top: box.top, bottom: box.bottom });
      hoverTimer.current = setTimeout(() => {
        hoverTimer.current = null;
        setHover(null);
      }, HOVER_LINGER_MS);
    } else {
      setHover(null);
    }
  }, []);
  useEffect(() => () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
  }, []);

  const hoverStyle = useMemo(() => {
    if (!hover) return undefined;
    const viewport = typeof window !== 'undefined' ? window.innerHeight : 600;
    return { top: `${hoverCardTop(hover.top, hover.bottom, viewport)}px` };
  }, [hover]);

  const landsInPlay = useMemo(() => {
    const state = payload?.state;
    if (!state) return null;
    // The overlay state carries lands drawn, not lands on the battlefield;
    // drawn is an upper bound on played, which is what the danger tone needs.
    return Math.max(0, state.lands_total - state.lands_left);
  }, [payload]);

  if (!settings) return <div ref={rootRef} class="root" />;

  const dockClass = `dock-${settings.dock}`;
  const side = hoverSide(settings.dock);

  return (
    <div
      ref={rootRef}
      class={`root ${dockClass} ${layout.layout === 'panel' ? 'is-panel' : 'is-rail'} ${(layout.layout === 'panel' ? settings.opacity : settings.railOpacity) > 0 ? 'has-bg' : 'no-bg'} names-${settings.nameColor}`}
      style={{ '--tint-alpha': tintAlpha(settings.opacity), '--rail-alpha': tintAlpha(settings.railOpacity), '--scale': (settings.scale / 100) * (layout.layout === 'rail' ? RAIL_BOOST : 1) } as never}
      onMouseLeave={onPointerLeave}
    >
      {layout.layout === 'panel' ? (
        <>
          <Panel
            payload={payload}
            link={link}
            settings={settings}
            pinned={layout.pinned}
            dock={settings.dock}
            sort={sort}
            onSort={setSort}
            onCollapse={collapse}
            onTogglePin={togglePin}
            onOpenSettings={() => setFlyout((v) => !v)}
            onDragStart={dragStart}
            onHover={onHover}
            sideboardOpen={sideboardOpen}
            onToggleSideboard={() => setSideboardOpen((v) => !v)}
          />
          {/* The transparent strip on the board side: the hover card and the
              sideboard fly out here, beside the panel rather than over it. */}
          <div class={`gutter side-${side}`}>
            {hover ? (
              <div class="hover" style={hoverStyle} role="tooltip">
                <img class="card-img" src={cardImageUrl(hover.row.name)} alt="" draggable={false} onError={(event) => ((event.currentTarget as HTMLImageElement).style.display = 'none')} />
                <b>{hover.row.name}</b>
                <div class="r">
                  <span>Next draw</span>
                  <span>{formatPct(hover.row.odds['1'])}</span>
                </div>
                <div class="r">
                  <span>Within 2</span>
                  <span>{formatPct(hover.row.odds['2'])}</span>
                </div>
                <div class="r">
                  <span>Within 3</span>
                  <span>{formatPct(hover.row.odds['3'])}</span>
                </div>
                <div class="r">
                  <span>Left</span>
                  <span>
                    {hover.row.left} of {hover.row.total}
                  </span>
                </div>
              </div>
            ) : null}
            {sideboardOpen && payload?.state?.sideboard?.length ? (
              <div class="sideboard" role="dialog" aria-label="Sideboard">
                <div class="sb-head">Sideboard</div>
                {payload.state.sideboard.map((card) => (
                  <div key={card.name} class="sb-row">
                    <span class="body">
                      <span class={`nm ${typeClass(card.type_category)}`} title={card.name}>
                        {card.name}
                      </span>
                      <ManaCost cost={card.mana_cost} />
                    </span>
                    <span class="cnt">
                      <b>{card.count}</b>
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <div class="rail-host">
          <Rail
            payload={payload}
            link={link}
            dock={settings.dock}
            landsInPlay={landsInPlay}
            onOpenPanel={() => void openPanel()}
            onOpenSettings={() => {
              setFlyout(true);
              void openPanel();
            }}
            onDragStart={dragStart}
          />
        </div>
      )}
      {flyout ? (
        <Flyout
          settings={settings}
          platform={platform}
          onChange={updateSettings}
          onClose={() => setFlyout(false)}
          onQuit={quit}
        />
      ) : null}
    </div>
  );
}
