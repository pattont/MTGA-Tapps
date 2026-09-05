import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { Flyout } from './components/Flyout';
import { Panel } from './components/Panel';
import { Rail } from './components/Rail';
import { formatPct, type Row } from './model';
import { OverlayPoller } from './poll';
import { log, tauri } from './tauri';
import type { Link, LayoutInfo, OverlayPayload, Settings, SortKey } from './types';

/** Dwell on the rail before the panel flies out. */
const RAIL_HOVER_MS = 320;
/** Panel chrome (header + strip + tools) never scrolls; the list does. */
const PANEL_MIN_HEIGHT = 160;

interface HoverCard {
  row: Row;
  /** The hovered row's box, in window coordinates. */
  top: number;
  bottom: number;
}

/** Approximate height of the hover card (title + four lines). */
const HOVER_CARD_HEIGHT = 98;

/** Card top: below the row, or above it when there is no room below. */
export function hoverCardTop(rowTop: number, rowBottom: number, viewportHeight: number): number {
  if (rowBottom + 2 + HOVER_CARD_HEIGHT <= viewportHeight) return rowBottom + 2;
  return Math.max(2, rowTop - 2 - HOVER_CARD_HEIGHT);
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

  const rootRef = useRef<HTMLDivElement>(null);
  const pollerRef = useRef<OverlayPoller | null>(null);
  const returnTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Last height reported to the shell, so re-opening the panel lands at the right size at once. */
  const lastHeight = useRef<number | null>(null);
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const flyoutRef = useRef(flyout);
  flyoutRef.current = flyout;
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

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

  const openPanel = useCallback(async () => {
    const info = await tauri.invoke<LayoutInfo>('set_layout', { layout: 'panel', contentHeight: lastHeight.current });
    setLayout(info);
  }, []);

  const collapse = useCallback(async () => {
    setHover(null);
    setFlyout(false);
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

  // --- unpinned return -------------------------------------------------------
  const clearReturn = useCallback(() => {
    if (returnTimer.current) {
      clearTimeout(returnTimer.current);
      returnTimer.current = null;
    }
  }, []);

  const armReturn = useCallback(() => {
    clearReturn();
    const current = layoutRef.current;
    const prefs = settingsRef.current;
    if (current.layout !== 'panel' || current.pinned || !prefs || flyoutRef.current) return;
    returnTimer.current = setTimeout(() => {
      returnTimer.current = null;
      const now = layoutRef.current;
      if (now.layout === 'panel' && !now.pinned && !flyoutRef.current) void collapse();
    }, Math.max(1, prefs.returnAfterSeconds) * 1000);
  }, [clearReturn, collapse]);

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
      void (async () => {
        const info = await tauri.invoke<LayoutInfo>('set_layout', { layout: 'panel', contentHeight: lastHeight.current });
        setLayout(info.pinned === pinned ? info : await tauri.invoke<LayoutInfo>('set_pinned', { pinned }));
      })();
    }
  }, [gameActive, collapse]);

  // The tray's Settings… shows the window even without Arena; closing the
  // flyout hands visibility back to the Arena rule.
  const flyoutWasOpen = useRef(false);
  useEffect(() => {
    if (flyoutWasOpen.current && !flyout) void tauri.invoke('flyout_closed');
    flyoutWasOpen.current = flyout;
  }, [flyout]);

  useEffect(() => {
    // An unpinned panel opened by hotkey or hover starts its clock at once;
    // the pointer entering cancels it and leaving re-arms it. Closing the
    // settings flyout re-arms it too.
    if (layout.layout === 'panel' && !layout.pinned && !flyout) armReturn();
    else clearReturn();
    return clearReturn;
  }, [layout.layout, layout.pinned, flyout, armReturn, clearReturn]);

  const onPointerEnter = useCallback(() => {
    clearReturn();
  }, [clearReturn]);

  const onPointerLeave = useCallback(() => {
    setHover(null);
    if (hoverTimer.current) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    armReturn();
  }, [armReturn]);

  // --- rail hover opens the panel -----------------------------------------
  const onRailEnter = useCallback(() => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => {
      hoverTimer.current = null;
      if (layoutRef.current.layout === 'rail' && !flyout) void openPanel();
    }, RAIL_HOVER_MS);
  }, [openPanel, flyout]);

  const onRailLeave = useCallback(() => {
    if (hoverTimer.current) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  }, []);

  // --- hover card ----------------------------------------------------------
  const onHover = useCallback((row: Row | null, box: { top: number; bottom: number } | null) => {
    setHover(row && box ? { row, top: box.top, bottom: box.bottom } : null);
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
      class={`root ${dockClass} ${layout.layout === 'panel' ? 'is-panel' : 'is-rail'} ${settings.opacity > 0 ? 'has-bg' : 'no-bg'}`}
      style={{ '--tint-alpha': tintAlpha(settings.opacity), '--scale': settings.scale / 100 } as never}
      onMouseEnter={onPointerEnter}
      onMouseLeave={onPointerLeave}
    >
      {layout.layout === 'panel' ? (
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
        />
      ) : (
        <div class="rail-host" onMouseEnter={onRailEnter} onMouseLeave={onRailLeave}>
          <Rail
            payload={payload}
            link={link}
            landsInPlay={landsInPlay}
            onOpenPanel={openPanel}
            onOpenSettings={() => {
              setFlyout(true);
              void openPanel();
            }}
            onDragStart={dragStart}
          />
        </div>
      )}
      {hover && layout.layout === 'panel' ? (
        <div class={`hover side-${side}`} style={hoverStyle} role="tooltip">
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
