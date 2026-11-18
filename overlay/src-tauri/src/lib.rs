//! Tapps Overlay — the Tauri shell.
//!
//! Always-on-top, frameless, transparent windows that switch between the rail
//! and the panel layout, dock flush to a screen edge, and answer the page's
//! commands: the deck window (`main`, always there) and the opponent window
//! (`opponent`, only while Settings → Opponent panel is on, docked on the
//! other edge). The page (Preact) owns everything that is drawn; this side
//! owns the windows, the global hotkeys, the Arena poll, and the settings
//! file.

mod arena;
mod diag;
mod dock;
mod parent;
mod settings;

use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, EventTarget, LogicalPosition, LogicalSize, Manager, WebviewWindow, WindowEvent};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

use arena::ArenaStatus;
use dock::{Layout, Rect};
use settings::{Dock, Settings};

const MAIN_WINDOW: &str = "main";
const OPPONENT_WINDOW: &str = "opponent";
const SETTINGS_FILE: &str = "overlay.json";
const ARENA_POLL: Duration = Duration::from_secs(1);
/// With Arena closed there is nothing to dock to or hide from: look half as often.
const ARENA_POLL_IDLE: Duration = Duration::from_secs(2);
/// The cursor watch (rail hover opens the panel; an unpinned panel folds
/// away after the cursor has been off it for the return delay). Done here
/// from the real cursor position rather than from the page's mouse events:
/// a non-activating overlay is never the key window, and WebKit does not
/// deliver hover / mouseleave reliably to one.
const CURSOR_POLL: Duration = Duration::from_millis(100);
const RAIL_HOVER_OPEN: Duration = Duration::from_millis(250);

/// The overlay's two windows. The deck window always exists; the opponent
/// window exists only while its setting is on.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Pane {
    Deck,
    Opponent,
}

impl Pane {
    const ALL: [Pane; 2] = [Pane::Deck, Pane::Opponent];

    fn label(self) -> &'static str {
        match self {
            Pane::Deck => MAIN_WINDOW,
            Pane::Opponent => OPPONENT_WINDOW,
        }
    }

    fn of(window: &WebviewWindow) -> Pane {
        if window.label() == OPPONENT_WINDOW {
            Pane::Opponent
        } else {
            Pane::Deck
        }
    }
}

/// Everything about the windows that is not a saved preference: what both
/// share (visibility, the monitor, Arena), and each window's own state.
#[derive(Debug, Clone)]
struct Runtime {
    /// The player hid it (hotkey / tracker menu); stays hidden until they show it.
    hidden_by_user: bool,
    /// Hidden because Arena is not running, or not in front (setting).
    hidden_for_arena: bool,
    /// Shown regardless of Arena while a flyout opened from the tracker's menu is up.
    force_show: bool,
    /// The monitor the windows were last placed on. Sticky: it only changes
    /// when Arena's window turns up on another one.
    area: Option<Rect>,
    /// Monitor name the windows are docked on, when known.
    monitor: Option<String>,
    last_arena: ArenaStatus,
    /// The deck page's last `/api/overlay` body carries an opponent block: a
    /// game is on screen, so the opponent window has something to show.
    opponent_live: bool,
    deck: PaneRuntime,
    opponent: PaneRuntime,
}

impl Runtime {
    fn pane(&self, pane: Pane) -> &PaneRuntime {
        match pane {
            Pane::Deck => &self.deck,
            Pane::Opponent => &self.opponent,
        }
    }

    fn pane_mut(&mut self, pane: Pane) -> &mut PaneRuntime {
        match pane {
            Pane::Deck => &mut self.deck,
            Pane::Opponent => &mut self.opponent,
        }
    }

    /// Shown or hidden, per window. The opponent window also needs its
    /// setting on and a game on screen, and is never forced up by the
    /// tracker's menu (that only opens the deck window's settings).
    fn visible(&self, pane: Pane, settings: &Settings) -> bool {
        match pane {
            Pane::Deck => !self.hidden_by_user && (self.force_show || !self.hidden_for_arena),
            Pane::Opponent => settings.opponent_panel && self.opponent_live && !self.hidden_by_user && !self.hidden_for_arena,
        }
    }
}

/// One window's own state.
#[derive(Debug, Clone)]
struct PaneRuntime {
    layout: Layout,
    /// The panel's content height as measured by the page (logical px).
    content_height: i32,
    /// Where we last put the window (logical). A Moved event that lands
    /// exactly there is the echo of our own placement, not a user drag —
    /// otherwise the panel's clamped y would overwrite the rail's. (There is
    /// deliberately no "moving it ourselves" flag: on Windows the Moved
    /// event is delivered synchronously inside set_position, on the same
    /// thread, so the handler must never depend on a lock its caller holds.)
    placed_at: Option<(i32, i32)>,
    /// When we last placed the window. A resize can move the window's origin
    /// before our set_position lands (macOS keeps the bottom edge put), and
    /// that intermediate Moved must not be mistaken for a drag and saved.
    placed_when: Option<std::time::Instant>,
    /// A drag in progress: the last position the window was seen at and
    /// when. Windows delivers Moved continuously while the mouse button is
    /// down, so the snap to the edge waits until the stream has gone quiet
    /// (the button was released) rather than fighting the drag.
    drag: Option<((i32, i32), std::time::Instant)>,
    /// The page's ⚙ flyout is open: an unpinned panel must not fold away.
    flyout_open: bool,
    /// The sideboard flies out into the transparent gutter: while it shows,
    /// the whole window counts as "over the panel" for the cursor watch.
    sideboard_open: bool,
    /// The cursor watch's last answer: the cursor is on the rail or panel
    /// (or anywhere in the window while something is flown out).
    cursor_on_overlay: bool,
    /// What the window was last told about ignoring the mouse.
    click_through: Option<bool>,
    /// Hovering the rail opens the panel — but not straight after the panel
    /// folded away under the cursor (game end, return timer): the cursor has
    /// to leave the rail once first, or it would spring back open.
    rail_hover_armed: bool,
}

impl Default for PaneRuntime {
    fn default() -> Self {
        Self {
            layout: Layout::Rail,
            content_height: 620,
            placed_at: None,
            placed_when: None,
            drag: None,
            flyout_open: false,
            sideboard_open: false,
            cursor_on_overlay: false,
            click_through: None,
            rail_hover_armed: true,
        }
    }
}

impl Default for Runtime {
    fn default() -> Self {
        Self {
            hidden_by_user: false,
            hidden_for_arena: true,
            force_show: false,
            area: None,
            monitor: None,
            last_arena: ArenaStatus::default(),
            opponent_live: false,
            deck: PaneRuntime::default(),
            opponent: PaneRuntime::default(),
        }
    }
}

struct AppState {
    settings: Mutex<Settings>,
    runtime: Mutex<Runtime>,
    settings_path: std::path::PathBuf,
    /// The deck page's last `/api/overlay` body, handed to the opponent page
    /// (one poller for both windows, so they always show the same moment).
    latest_payload: Mutex<serde_json::Value>,
}

/// A window's preferences: whether its panel is on and pinned, the edge it
/// docks to, and its remembered offset on that edge.
struct PanePrefs {
    open: bool,
    pinned: bool,
    dock: Dock,
    y: Option<i32>,
    float_at: Option<(i32, i32)>,
}

fn pane_prefs(settings: &Settings, pane: Pane) -> PanePrefs {
    // With the deck panel off the Dock setting places the opponent panel
    // and the deck window takes the other edge (`dock::pane_docks`).
    let (deck_dock, opponent_dock) = dock::pane_docks(settings.dock, settings.deck_panel);
    match pane {
        Pane::Deck => PanePrefs {
            open: settings.panel_open,
            pinned: settings.panel_pinned,
            dock: deck_dock,
            y: match deck_dock {
                Dock::Left => settings.positions.left_y,
                Dock::Right => settings.positions.right_y,
                Dock::Float => None,
            },
            float_at: match (settings.positions.float_x, settings.positions.float_y) {
                (Some(x), Some(y)) => Some((x, y)),
                _ => None,
            },
        },
        Pane::Opponent => {
            let dock = opponent_dock;
            PanePrefs {
                open: settings.opponent_open,
                pinned: settings.opponent_pinned,
                dock,
                y: match dock {
                    Dock::Left => settings.positions.opponent_left_y,
                    _ => settings.positions.opponent_right_y,
                },
                float_at: None,
            }
        }
    }
}

fn set_pane_open(settings: &mut Settings, pane: Pane, open: bool) {
    match pane {
        Pane::Deck => settings.panel_open = open,
        Pane::Opponent => settings.opponent_open = open,
    }
}

fn set_pane_pinned(settings: &mut Settings, pane: Pane, pinned: bool) {
    match pane {
        Pane::Deck => settings.panel_pinned = pinned,
        Pane::Opponent => settings.opponent_pinned = pinned,
    }
}

/// The window's size for its layout (the deck window also widens for the
/// settings flyout beside its rail).
fn pane_size(settings: &Settings, runtime: &Runtime, pane: Pane, area: &Rect) -> dock::Size {
    let own = runtime.pane(pane);
    match pane {
        Pane::Deck => dock::size_for(own.layout, own.content_height, area, settings.panel_max_height, settings.scale, own.flyout_open),
        Pane::Opponent => dock::opponent_size_for(own.layout, own.content_height, area, settings.panel_max_height, settings.scale),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LayoutInfo {
    layout: String,
    pinned: bool,
    /// The deck panel is "on" (see Settings::panel_open).
    panel_open: bool,
    visible: bool,
    dock: Dock,
}

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/// Monitors as logical-pixel rects, in Tauri's enumeration order, plus names.
fn monitor_rects(window: &WebviewWindow) -> Vec<(Rect, Option<String>)> {
    let Ok(monitors) = window.available_monitors() else {
        return Vec::new();
    };
    monitors
        .iter()
        .map(|m| {
            let scale = m.scale_factor();
            let pos = m.position().to_logical::<i32>(scale);
            let size = m.size().to_logical::<i32>(scale);
            (
                Rect { x: pos.x, y: pos.y, width: size.width, height: size.height },
                m.name().cloned(),
            )
        })
        .collect()
}

/// Index of the monitor holding the centre of Arena's window, in
/// `available_monitors()` order. Units differ per platform (see
/// `ArenaStatus::bounds`), so the comparison is done in the matching ones.
fn arena_monitor_index(window: &WebviewWindow, bounds: (i32, i32, i32, i32)) -> Option<usize> {
    let (x, y, w, h) = bounds;
    if w <= 0 || h <= 0 {
        return None;
    }
    let arena = Rect { x, y, width: w, height: h };
    #[cfg(target_os = "macos")]
    let rects: Vec<Rect> = monitor_rects(window).into_iter().map(|(r, _)| r).collect();
    #[cfg(not(target_os = "macos"))]
    let rects: Vec<Rect> = window
        .available_monitors()
        .ok()?
        .iter()
        .map(|m| {
            let p = m.position();
            let s = m.size();
            Rect { x: p.x, y: p.y, width: s.width as i32, height: s.height as i32 }
        })
        .collect();
    dock::monitor_holding(&rects, &arena)
}

/// The monitor the window should dock on: Arena's (when it has a window and
/// "follow Arena" is on), else the one it is already on, else the remembered
/// one when it still exists, else the one under the cursor, else the primary.
/// The cursor only ever decides the very first placement — a window that
/// re-docked to wherever the mouse happened to be would wander between
/// screens every time its size changed.
/// What target_monitor needs from the runtime, copied out under the lock
/// so the window can be asked about monitors and the cursor WITHOUT any
/// lock held: on Windows every window getter is a blocking round-trip to
/// the main thread, and a background thread holding a lock across one
/// deadlocks with a main-thread command waiting for that lock.
#[derive(Clone)]
struct MonitorHint {
    follow_arena: bool,
    arena_bounds: Option<(i32, i32, i32, i32)>,
    area: Option<Rect>,
    monitor: Option<String>,
}

impl MonitorHint {
    fn take(state: &AppState) -> Self {
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        Self {
            follow_arena: settings.follow_arena,
            arena_bounds: runtime.last_arena.bounds,
            area: runtime.area,
            monitor: runtime.monitor.clone(),
        }
    }
}

fn target_monitor(window: &WebviewWindow, hint: &MonitorHint) -> Rect {
    let monitors = monitor_rects(window);
    if monitors.is_empty() {
        return Rect { x: 0, y: 0, width: 1920, height: 1080 };
    }
    if hint.follow_arena {
        if let Some(index) = hint.arena_bounds.and_then(|b| arena_monitor_index(window, b)) {
            if let Some((rect, _)) = monitors.get(index) {
                return *rect;
            }
        }
    }
    if let Some(area) = hint.area {
        if monitors.iter().any(|(rect, _)| *rect == area) {
            return area;
        }
    }
    if let Some(name) = hint.monitor.as_ref() {
        if let Some((rect, _)) = monitors.iter().find(|(_, n)| n.as_deref() == Some(name.as_str())) {
            return *rect;
        }
    }
    let cursor = window
        .cursor_position()
        .ok()
        .map(|p| (p.x as i32, p.y as i32));
    let rects: Vec<Rect> = monitors.iter().map(|(r, _)| *r).collect();
    let index = dock::choose_monitor(&rects, cursor, None).unwrap_or(0);
    rects[index]
}

/// Size and place every window that exists.
fn apply_geometry(app: &AppHandle) {
    for pane in Pane::ALL {
        apply_pane_geometry(app, pane);
    }
}

/// Size and place one window for its layout / dock / remembered offset.
///
/// Everything is decided under the locks and the locks are released BEFORE
/// the window is touched: on Windows, set_size / set_position deliver the
/// Moved event synchronously on this very thread, and its handler takes
/// the same locks — holding them across the call deadlocks the main thread
/// ("Not Responding" on the first click of the arrow).
fn apply_pane_geometry(app: &AppHandle, pane: Pane) {
    let Some(window) = app.get_webview_window(pane.label()) else { return };
    let state = app.state::<AppState>();
    // Monitor and cursor queries first, with nothing locked.
    let area = target_monitor(&window, &MonitorHint::take(&state));
    let (layout, dock, area, size, x, y) = {
        let settings = state.settings.lock().unwrap().clone();
        let mut runtime = state.runtime.lock().unwrap();
        runtime.area = Some(area);
        let size = pane_size(&settings, &runtime, pane, &area);
        let prefs = pane_prefs(&settings, pane);
        let (x, y) = dock::docked_position(prefs.dock, size, &area, prefs.y, prefs.float_at);
        let own = runtime.pane_mut(pane);
        own.placed_at = Some((x, y));
        own.placed_when = Some(std::time::Instant::now());
        (own.layout, prefs.dock, area, size, x, y)
    };
    let sized = window.set_size(LogicalSize::new(size.width, size.height));
    let placed = window.set_position(LogicalPosition::new(x, y));
    diag::log(format!(
        "geometry: window={} layout={:?} dock={:?} monitor={:?} size={}x{} at ({}, {}) set_size={:?} set_position={:?}",
        pane.label(), layout, dock, area, size.width, size.height, x, y, sized.err(), placed.err()
    ));
}

/// Over a fullscreen Arena (its own Space) a floating NSWindow is not
/// enough on current macOS: even with `canJoinAllSpaces` and
/// `fullScreenAuxiliary` set, the window stays on the desktop Space. What
/// does work — the same trick as the tauri-nspanel plugin — is turning the
/// window into a non-activating NSPanel, giving it those collection
/// behaviours and a level above the fullscreen window, and ordering it
/// front "regardless" (without activating the overlay). NSPanel adds no
/// instance variables, so swapping the class of the live window is safe.
/// Tauri's `set_always_on_top` resets the level, so this runs after every
/// show.
#[cfg(target_os = "macos")]
fn raise_above_fullscreen(window: &WebviewWindow) {
    use objc2::runtime::{AnyClass, AnyObject};

    // NSWindowCollectionBehavior
    const CAN_JOIN_ALL_SPACES: usize = 1 << 0;
    const STATIONARY: usize = 1 << 4;
    const IGNORES_CYCLE: usize = 1 << 6;
    const FULL_SCREEN_AUXILIARY: usize = 1 << 8;
    // NSWindowStyleMask
    const NONACTIVATING_PANEL: usize = 1 << 7;

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGShieldingWindowLevel() -> i32;
    }
    #[link(name = "objc", kind = "dylib")]
    extern "C" {
        fn object_setClass(obj: *mut AnyObject, cls: *const AnyClass) -> *const AnyClass;
    }

    let target = window.clone();
    let _ = window.run_on_main_thread(move || {
        let Ok(ptr) = target.ns_window() else {
            diag::log("macos: no NSWindow to raise");
            return;
        };
        let ns: &AnyObject = unsafe { &*(ptr as *const AnyObject) };
        let panel_class: &AnyClass = objc2::class!(NSPanel);
        let is_panel: bool = unsafe { objc2::msg_send![ns, isKindOfClass: panel_class] };
        if !is_panel {
            unsafe { object_setClass(ptr as *mut AnyObject, panel_class) };
            diag::log("macos: window turned into an NSPanel");
        }
        // The shielding level is the one level above a captured
        // (exclusive-fullscreen) display as well as above fullscreen
        // Spaces; the window is only ever shown while Arena is running.
        let level = unsafe { CGShieldingWindowLevel() } as isize;
        let behavior = CAN_JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULL_SCREEN_AUXILIARY;
        let (level_now, behavior_now, style_now, on_active_space, visible): (isize, usize, usize, bool, bool) = unsafe {
            let style: usize = objc2::msg_send![ns, styleMask];
            let _: () = objc2::msg_send![ns, setStyleMask: style | NONACTIVATING_PANEL];
            let _: () = objc2::msg_send![ns, setHidesOnDeactivate: false];
            let _: () = objc2::msg_send![ns, setCollectionBehavior: behavior];
            let _: () = objc2::msg_send![ns, setLevel: level];
            let visible: bool = objc2::msg_send![ns, isVisible];
            if visible {
                let _: () = objc2::msg_send![ns, orderFrontRegardless];
            }
            (
                objc2::msg_send![ns, level],
                objc2::msg_send![ns, collectionBehavior],
                objc2::msg_send![ns, styleMask],
                objc2::msg_send![ns, isOnActiveSpace],
                visible,
            )
        };
        diag::log(format!(
            "macos: window level={level_now} (asked {level}) behavior={behavior_now:#x} (asked {behavior:#x}) style={style_now:#x} visible={visible} on_active_space={on_active_space}"
        ));
    });
}

#[cfg(not(target_os = "macos"))]
fn raise_above_fullscreen(_window: &WebviewWindow) {}

fn refresh_visibility(app: &AppHandle) {
    for pane in Pane::ALL {
        refresh_pane_visibility(app, pane);
    }
}

fn refresh_pane_visibility(app: &AppHandle, pane: Pane) {
    let Some(window) = app.get_webview_window(pane.label()) else { return };
    // Decided under the lock, done without it (see apply_pane_geometry).
    let (show, by_user, for_arena) = {
        let state = app.state::<AppState>();
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        (runtime.visible(pane, &settings), runtime.hidden_by_user, runtime.hidden_for_arena)
    };
    if show {
        let shown = window.show();
        let top = window.set_always_on_top(true);
        raise_above_fullscreen(&window);
        diag::log(format!(
            "show {}: show={:?} always_on_top={:?} is_visible={:?}",
            pane.label(), shown.err(), top.err(), window.is_visible().ok()
        ));
    } else {
        let hidden = window.hide();
        diag::log(format!("hide {}: by_user={} for_arena={} hide={:?}", pane.label(), by_user, for_arena, hidden.err()));
    }
}

/// Tell each window's page its own layout.
fn emit_layout(app: &AppHandle) {
    for pane in Pane::ALL {
        emit_pane_layout(app, pane);
    }
}

fn emit_pane_layout(app: &AppHandle, pane: Pane) {
    if app.get_webview_window(pane.label()).is_none() {
        return;
    }
    let info = current_layout(app, pane);
    let _ = app.emit_to(EventTarget::webview_window(pane.label()), "overlay-layout", info);
}

fn current_layout(app: &AppHandle, pane: Pane) -> LayoutInfo {
    let state = app.state::<AppState>();
    let settings = state.settings.lock().unwrap();
    let runtime = state.runtime.lock().unwrap();
    let prefs = pane_prefs(&settings, pane);
    LayoutInfo {
        layout: match runtime.pane(pane).layout {
            Layout::Rail => "rail".into(),
            Layout::Panel => "panel".into(),
        },
        pinned: prefs.pinned,
        panel_open: prefs.open,
        visible: runtime.visible(pane, &settings),
        dock: prefs.dock,
    }
}

/// Why a layout change happened: the player asked (arrow, chevron, hotkey)
/// or the overlay did it on its own (hover, the return delay, a game
/// ending). Only the player's choice is remembered as the panel being on.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Why {
    User,
    Auto,
}

/// Switch a window's layout. A user-opened panel turns it "on" and a
/// user-closed one turns it off (both saved); automatic moves leave that
/// alone, so a panel that folded away between games is still "on" and
/// comes back.
fn set_layout_inner(app: &AppHandle, pane: Pane, layout: Layout, why: Why) {
    let save = {
        let state = app.state::<AppState>();
        // Settings before runtime, like every other place holding both.
        let mut settings = state.settings.lock().unwrap();
        let mut runtime = state.runtime.lock().unwrap();
        // The deck panel is off: its window stays the empty rail whatever
        // asks, and the panel's remembered on/off is left as it was.
        let off = pane == Pane::Deck && !settings.deck_panel;
        let layout = if off { Layout::Rail } else { layout };
        let own = runtime.pane_mut(pane);
        own.layout = layout;
        if layout == Layout::Rail {
            own.rail_hover_armed = false;
        }
        let open = layout == Layout::Panel;
        if !off && why == Why::User && pane_prefs(&settings, pane).open != open {
            set_pane_open(&mut settings, pane, open);
            true
        } else {
            false
        }
    };
    if save {
        save_settings(app);
    }
    apply_pane_geometry(app, pane);
    apply_click_through(app, pane);
    emit_pane_layout(app, pane);
}

/// Tells a window whether to ignore the mouse (`dock::click_through`), when
/// that changed. The cursor watch calls this on every pass, so the panel's
/// gutter never keeps clicks, drags and hovers from the cards under it.
fn apply_click_through(app: &AppHandle, pane: Pane) {
    let Some(window) = app.get_webview_window(pane.label()) else { return };
    let state = app.state::<AppState>();
    // One lock at a time, and none across the window call (see apply_pane_geometry).
    let (always, deck_off) = {
        let settings = state.settings.lock().unwrap();
        (
            pane_prefs(&settings, pane).pinned && settings.click_through_when_pinned,
            pane == Pane::Deck && !settings.deck_panel,
        )
    };
    let through = {
        let mut runtime = state.runtime.lock().unwrap();
        let own = runtime.pane_mut(pane);
        let through = if deck_off {
            // Nothing is drawn in it: only the settings take the mouse.
            dock::hidden_click_through(own.flyout_open)
        } else {
            dock::click_through(
                own.layout,
                always,
                own.cursor_on_overlay,
                own.flyout_open || own.sideboard_open,
                own.drag.is_some(),
            )
        };
        if own.click_through == Some(through) {
            return;
        }
        own.click_through = Some(through);
        through
    };
    let _ = window.set_ignore_cursor_events(through);
}

fn apply_click_through_all(app: &AppHandle) {
    for pane in Pane::ALL {
        apply_click_through(app, pane);
    }
}

fn toggle_layout(app: &AppHandle, pane: Pane) {
    let next = {
        let state = app.state::<AppState>();
        let runtime = state.runtime.lock().unwrap();
        match runtime.pane(pane).layout {
            Layout::Rail => Layout::Panel,
            Layout::Panel => Layout::Rail,
        }
    };
    set_layout_inner(app, pane, next, Why::User);
}

fn toggle_hidden(app: &AppHandle) {
    {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        runtime.hidden_by_user = !runtime.hidden_by_user;
    }
    refresh_visibility(app);
    emit_layout(app);
}

fn save_settings(app: &AppHandle) {
    let state = app.state::<AppState>();
    let settings = state.settings.lock().unwrap().clone();
    if let Err(err) = settings.save(&state.settings_path) {
        diag::log(format!("could not save settings: {err}"));
    }
}

/// Register (or re-register) the global hotkeys from the settings: show /
/// hide, and each panel's toggle while that panel is on (off, its chord is
/// left free for other apps).
fn register_hotkeys(app: &AppHandle) {
    let shortcuts = app.global_shortcut();
    let _ = shortcuts.unregister_all();
    let (toggle, visibility, opponent) = {
        let state = app.state::<AppState>();
        let settings = state.settings.lock().unwrap();
        let keys = settings.hotkeys();
        (
            settings.deck_panel.then(|| keys.toggle.clone()),
            keys.visibility.clone(),
            settings.opponent_panel.then(|| keys.opponent.clone()),
        )
    };
    if let Some(toggle_key) = toggle.clone() {
        if let Err(err) = shortcuts.on_shortcut(toggle_key.as_str(), move |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                toggle_layout(app, Pane::Deck);
            }
        }) {
            diag::log(format!("hotkey {toggle_key} unavailable: {err}"));
        } else {
            diag::log(format!("hotkey {toggle_key} registered (toggle)"));
        }
    }
    let visibility_key = visibility.clone();
    if let Err(err) = shortcuts.on_shortcut(visibility.as_str(), move |app, _shortcut, event| {
        if event.state() == ShortcutState::Pressed {
            toggle_hidden(app);
        }
    }) {
        diag::log(format!("hotkey {visibility_key} unavailable: {err}"));
    } else {
        diag::log(format!("hotkey {visibility_key} registered (visibility)"));
    }
    if let Some(opponent) = opponent {
        if Some(&opponent) == toggle.as_ref() || opponent == visibility {
            diag::log(format!("hotkey {opponent} already used; opponent toggle not registered"));
            return;
        }
        let opponent_key = opponent.clone();
        if let Err(err) = shortcuts.on_shortcut(opponent.as_str(), move |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                toggle_layout(app, Pane::Opponent);
            }
        }) {
            diag::log(format!("hotkey {opponent_key} unavailable: {err}"));
        } else {
            diag::log(format!("hotkey {opponent_key} registered (opponent)"));
        }
    }
}

// ---------------------------------------------------------------------------
// The opponent window
// ---------------------------------------------------------------------------

/// What every overlay window needs once built: on top of everything
/// (fullscreen Arena included), on every Space, out of the taskbar, and its
/// drags noticed.
fn configure_window(app: &AppHandle, window: &WebviewWindow, pane: Pane) {
    let _ = window.set_always_on_top(true);
    let _ = window.set_visible_on_all_workspaces(true);
    let _ = window.set_skip_taskbar(true);
    raise_above_fullscreen(window);
    let moved_handle = app.clone();
    let label = pane.label();
    window.on_window_event(move |event| match event {
        WindowEvent::Moved(position) => on_moved(&moved_handle, pane, position.x, position.y),
        WindowEvent::Focused(focused) => diag::log(format!("window {label} focused={focused}")),
        WindowEvent::Destroyed => diag::log(format!("window {label} destroyed")),
        _ => {}
    });
}

/// Build the opponent window when its setting is on, destroy it when off.
/// Window creation waits on the event loop, so this never runs inside a
/// synchronous command on the main thread (WebView2 deadlocks there): the
/// command hands it to a thread of its own.
fn sync_opponent_window(app: &AppHandle) {
    let enabled = app.state::<AppState>().settings.lock().unwrap().opponent_panel;
    let existing = app.get_webview_window(OPPONENT_WINDOW);
    match (enabled, existing) {
        (true, None) => {
            let built = tauri::WebviewWindowBuilder::new(app, OPPONENT_WINDOW, tauri::WebviewUrl::App("index.html".into()))
                .title("Tapps Tracker — Opponent")
                // The page picks its view from this, before its first render.
                .initialization_script("window.__TAPPS_VIEW__ = 'opponent';")
                .inner_size(dock::RAIL_WIDTH as f64, dock::OPPONENT_RAIL_HEIGHT as f64)
                .decorations(false)
                .transparent(true)
                .shadow(false)
                .always_on_top(true)
                .skip_taskbar(true)
                .resizable(false)
                .maximizable(false)
                .minimizable(false)
                .closable(false)
                .focused(false)
                .visible(false)
                .accept_first_mouse(true)
                .visible_on_all_workspaces(true)
                .build();
            match built {
                Ok(window) => {
                    diag::log("opponent window built");
                    configure_window(app, &window, Pane::Opponent);
                    // Turned on mid-game with its panel left on and pinned:
                    // open, as it would have come up at the game's start.
                    let reopen = {
                        let state = app.state::<AppState>();
                        let settings = state.settings.lock().unwrap();
                        let mut runtime = state.runtime.lock().unwrap();
                        let reopen = runtime.opponent_live && settings.opponent_open && settings.opponent_pinned;
                        if reopen {
                            runtime.opponent.layout = Layout::Panel;
                        }
                        reopen
                    };
                    if reopen {
                        diag::log("opponent window: a game is on, opening its pinned panel");
                    }
                    apply_pane_geometry(app, Pane::Opponent);
                    apply_click_through(app, Pane::Opponent);
                    refresh_pane_visibility(app, Pane::Opponent);
                }
                Err(err) => diag::log(format!("opponent window failed to build: {err}")),
            }
        }
        (false, Some(window)) => {
            let destroyed = window.destroy();
            diag::log(format!("opponent window closed: {:?}", destroyed.err()));
            // A fresh window starts from the rail with nothing measured.
            let state = app.state::<AppState>();
            state.runtime.lock().unwrap().opponent = PaneRuntime::default();
        }
        _ => {}
    }
}

/// Whether the overlay body shows a game the opponent window can show: the
/// tracker sends an `opponent` block only then (and none while offline).
fn payload_has_opponent(payload: &serde_json::Value) -> bool {
    payload.get("opponent").map_or(false, |block| block.is_object())
}

// ---------------------------------------------------------------------------
// Requests from the tracker (a second launch with flags; see run())
// ---------------------------------------------------------------------------

/// `--panels both|deck|opponent` on the command line: the tracker's Settings
/// → In-game overlay → Panels choice, sent at every launch and on a change.
fn panels_from_args(args: impl Iterator<Item = String>) -> Option<(bool, bool)> {
    let mut args = args;
    while let Some(arg) = args.next() {
        if arg == "--panels" {
            return args.next().and_then(|value| settings::panels_from_arg(&value));
        }
        if let Some(rest) = arg.strip_prefix("--panels=") {
            return settings::panels_from_arg(rest);
        }
    }
    None
}

/// Turn the deck panel and the opponent panel on or off while running. The
/// deck window is never destroyed (it holds the poller and the settings):
/// off, it goes back to an empty rail that lets every click through. The
/// opponent window is built or destroyed on a thread of its own, as window
/// creation must never run inside the caller on the main thread.
fn set_panels(app: &AppHandle, deck: bool, opponent: bool) {
    let next = {
        let state = app.state::<AppState>();
        let mut settings = state.settings.lock().unwrap();
        if settings.deck_panel == deck && settings.opponent_panel == opponent {
            return;
        }
        settings.deck_panel = deck;
        settings.opponent_panel = opponent;
        if !deck {
            state.runtime.lock().unwrap().deck.layout = Layout::Rail;
        }
        settings.clone()
    };
    diag::log(format!("panels: deck={deck} opponent={opponent}"));
    save_settings(app);
    register_hotkeys(app);
    let handle = app.clone();
    std::thread::spawn(move || sync_opponent_window(&handle));
    for pane in Pane::ALL {
        let _ = app.emit_to(EventTarget::webview_window(pane.label()), "overlay-settings", next.clone());
    }
    apply_geometry(app);
    apply_click_through_all(app);
    emit_layout(app);
}

/// The tracker's menu bar drives the overlay by starting a second instance
/// with a flag; the single-instance plugin hands those arguments here and
/// the second instance exits. No tray of our own — one menu-bar icon.
fn handle_request(app: &AppHandle, args: &[String]) {
    // A tracker that reuses this overlay takes over as the process it lives with.
    if let Some(pid) = parent::pid_from_args(args) {
        parent::watch(pid);
    }
    if let Some((deck, opponent)) = panels_from_args(args.iter().cloned()) {
        set_panels(app, deck, opponent);
    }
    for arg in args {
        match arg.as_str() {
            "--open-settings" => {
                {
                    let state = app.state::<AppState>();
                    let mut runtime = state.runtime.lock().unwrap();
                    runtime.hidden_by_user = false;
                    // Reachable without Arena: shown until the flyout closes.
                    runtime.force_show = true;
                }
                refresh_visibility(app);
                emit_layout(app);
                let _ = app.emit_to(EventTarget::webview_window(MAIN_WINDOW), "overlay-open-settings", ());
            }
            "--show" => {
                {
                    let state = app.state::<AppState>();
                    state.runtime.lock().unwrap().hidden_by_user = false;
                }
                refresh_visibility(app);
                emit_layout(app);
            }
            "--hide" => {
                {
                    let state = app.state::<AppState>();
                    state.runtime.lock().unwrap().hidden_by_user = true;
                }
                refresh_visibility(app);
                emit_layout(app);
            }
            _ => {}
        }
    }
}

// ---------------------------------------------------------------------------
// Arena poll
// ---------------------------------------------------------------------------

fn start_arena_poll(app: AppHandle) {
    std::thread::Builder::new()
        .name("arena-poll".into())
        .spawn(move || loop {
            let status = arena::probe();
            let (changed, moved, hide_setting) = {
                let state = app.state::<AppState>();
                let settings = state.settings.lock().unwrap();
                let mut runtime = state.runtime.lock().unwrap();
                let changed = runtime.last_arena != status;
                let moved = status.bounds.is_some() && runtime.last_arena.bounds != status.bounds;
                runtime.last_arena = status;
                (changed, moved && settings.follow_arena, settings.hide_when_arena_not_in_front)
            };
            if changed {
                diag::log(format!("arena: {status:?}"));
                let _ = app.emit("arena-status", status);
            }
            if moved {
                // Arena's window appeared or moved: dock on its monitor.
                apply_geometry(&app);
            }
            // The overlay belongs to Arena: no Arena, no overlay. With the
            // setting on it also steps aside while something else is in
            // front — the overlay itself having focus (the flyout) never
            // counts as "something else".
            let should_hide = !status.running
                || (hide_setting && !status.frontmost && !status.overlay_frontmost);
            let flip = {
                let state = app.state::<AppState>();
                let mut runtime = state.runtime.lock().unwrap();
                if runtime.hidden_for_arena != should_hide {
                    runtime.hidden_for_arena = should_hide;
                    true
                } else {
                    false
                }
            };
            if flip {
                refresh_visibility(&app);
                emit_layout(&app);
            } else if changed && status.running && status.frontmost {
                // Arena (re)took the front: make sure we are still above it.
                for pane in Pane::ALL {
                    if let Some(window) = app.get_webview_window(pane.label()) {
                        raise_above_fullscreen(&window);
                    }
                }
            }
            std::thread::sleep(if status.running { ARENA_POLL } else { ARENA_POLL_IDLE });
        })
        .expect("arena poll thread");
}

// ---------------------------------------------------------------------------
// Commands (the page's API; each window's page calls them for itself)
// ---------------------------------------------------------------------------

#[tauri::command]
fn get_settings(state: tauri::State<AppState>) -> Settings {
    state.settings.lock().unwrap().clone()
}

#[tauri::command]
fn update_settings(app: AppHandle, state: tauri::State<AppState>, settings: Settings) -> Settings {
    let (hotkeys_changed, next) = {
        let mut current = state.settings.lock().unwrap();
        let mut next = settings.clamped();
        // Which panels are on is the tracker's setting (`set_panels`); the
        // flyout has no control for it and its copy can be stale.
        next.deck_panel = current.deck_panel;
        next.opponent_panel = current.opponent_panel;
        // The page edits preferences; each panel's on/off and pin state are
        // owned here (arrow, chevron, pin button, hotkey) and the page's
        // copy can be stale — never let a slider save overwrite them.
        next.panel_open = current.panel_open;
        next.panel_pinned = current.panel_pinned;
        next.opponent_open = current.opponent_open;
        next.opponent_pinned = current.opponent_pinned;
        // The page's Restore defaults builds its own object without the
        // version; what is saved from here is always current.
        next.settings_version = settings::SETTINGS_VERSION;
        let hotkeys_changed = current.hotkeys() != next.hotkeys();
        *current = next.clone();
        (hotkeys_changed, next)
    };
    save_settings(&app);
    if hotkeys_changed {
        register_hotkeys(&app);
    }
    // The opponent page draws with the same scale, background and rows.
    let _ = app.emit_to(EventTarget::webview_window(OPPONENT_WINDOW), "overlay-settings", next.clone());
    apply_geometry(&app);
    apply_click_through_all(&app);
    emit_layout(&app);
    next
}

#[tauri::command]
fn set_layout(app: AppHandle, window: WebviewWindow, layout: String, content_height: Option<i32>, auto: Option<bool>) -> LayoutInfo {
    let pane = Pane::of(&window);
    if let Some(height) = content_height {
        let state = app.state::<AppState>();
        state.runtime.lock().unwrap().pane_mut(pane).content_height = height.max(0);
    }
    let target = if layout == "panel" { Layout::Panel } else { Layout::Rail };
    let why = if auto.unwrap_or(false) { Why::Auto } else { Why::User };
    set_layout_inner(&app, pane, target, why);
    current_layout(&app, pane)
}

#[tauri::command]
fn set_content_height(app: AppHandle, window: WebviewWindow, height: i32) {
    let pane = Pane::of(&window);
    let resize = {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        let own = runtime.pane_mut(pane);
        let next = height.max(0);
        let changed = own.content_height != next;
        own.content_height = next;
        // The rail's window only follows the content while the settings
        // flyout is open beside it.
        changed && (own.layout == Layout::Panel || own.flyout_open)
    };
    if resize {
        apply_pane_geometry(&app, pane);
    }
}

#[tauri::command]
fn set_pinned(app: AppHandle, window: WebviewWindow, pinned: bool) -> LayoutInfo {
    let pane = Pane::of(&window);
    {
        let state = app.state::<AppState>();
        set_pane_pinned(&mut state.settings.lock().unwrap(), pane, pinned);
    }
    save_settings(&app);
    apply_click_through(&app, pane);
    emit_pane_layout(&app, pane);
    current_layout(&app, pane)
}

#[tauri::command]
fn get_layout(app: AppHandle, window: WebviewWindow) -> LayoutInfo {
    current_layout(&app, Pane::of(&window))
}

#[tauri::command]
fn arena_status(state: tauri::State<AppState>) -> ArenaStatus {
    state.runtime.lock().unwrap().last_arena
}

#[tauri::command]
fn platform() -> String {
    std::env::consts::OS.to_string()
}

#[tauri::command]
fn hide_overlay(app: AppHandle) {
    {
        let state = app.state::<AppState>();
        state.runtime.lock().unwrap().hidden_by_user = true;
    }
    refresh_visibility(&app);
    emit_layout(&app);
}

#[tauri::command]
fn quit_overlay(app: AppHandle) {
    diag::log("quit requested by the page");
    // The Python supervisor distinguishes an explicit player choice from a
    // successful second-instance handoff (0) and from a crash. Keep this in
    // sync with overlay_launcher.USER_QUIT_EXIT_CODE.
    app.exit(23);
}

/// What the page has flown out (the ⚙ flyout, the sideboard). The flyout
/// closing also hands a window the tracker's menu forced open back to the
/// Arena rule.
#[tauri::command]
fn set_page_open(app: AppHandle, window: WebviewWindow, flyout: bool, sideboard: bool) {
    let pane = Pane::of(&window);
    let (was_forced, resize) = {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        let own = runtime.pane_mut(pane);
        let flyout_changed = own.flyout_open != flyout;
        own.flyout_open = flyout;
        own.sideboard_open = sideboard;
        let resize = flyout_changed && own.layout == Layout::Rail;
        (
            pane == Pane::Deck && !flyout && std::mem::replace(&mut runtime.force_show, false),
            // The settings flyout opens beside the rail: the rail window
            // widens by the gutter while it is open and shrinks back after.
            resize,
        )
    };
    if resize {
        apply_pane_geometry(&app, pane);
    }
    // The gutter takes clicks only while something is flown out into it.
    apply_click_through(&app, pane);
    if was_forced {
        refresh_visibility(&app);
        emit_layout(&app);
    }
}

/// The deck page hands each new `/api/overlay` body (or null once the
/// tracker link is lost) to the opponent page, so one poller feeds both
/// windows. The body also says whether a game is on screen, which is when
/// the opponent window shows: it comes up with the game, opened when its
/// panel is on and pinned, and folds and hides once the game is gone.
#[tauri::command]
fn share_payload(app: AppHandle, payload: serde_json::Value) {
    let live = payload_has_opponent(&payload);
    let (changed, reopen) = {
        let state = app.state::<AppState>();
        *state.latest_payload.lock().unwrap() = payload.clone();
        let settings = state.settings.lock().unwrap();
        let mut runtime = state.runtime.lock().unwrap();
        let changed = runtime.opponent_live != live;
        runtime.opponent_live = live;
        (changed, settings.opponent_open && settings.opponent_pinned)
    };
    if app.get_webview_window(OPPONENT_WINDOW).is_none() {
        return;
    }
    if changed {
        let layout = if live && reopen { Layout::Panel } else { Layout::Rail };
        set_layout_inner(&app, Pane::Opponent, layout, Why::Auto);
        refresh_pane_visibility(&app, Pane::Opponent);
        emit_pane_layout(&app, Pane::Opponent);
    }
    let _ = app.emit_to(EventTarget::webview_window(OPPONENT_WINDOW), "overlay-payload", payload);
}

/// The opponent panel's ⚙, shown while the deck panel is off: the settings
/// open in the deck window, which is otherwise empty then.
#[tauri::command]
fn open_settings(app: AppHandle) {
    let _ = app.emit_to(EventTarget::webview_window(MAIN_WINDOW), "overlay-open-settings", ());
}

/// The last body the deck page shared, for an opponent page that just loaded.
#[tauri::command]
fn latest_payload(state: tauri::State<AppState>) -> serde_json::Value {
    state.latest_payload.lock().unwrap().clone()
}

/// The cursor's position inside the window, in the window's logical
/// pixels (the page's CSS pixels), or None when it is outside. Compared in
/// logical coordinates: on macOS the cursor and the window can be scaled
/// by different monitors.
fn cursor_in_window(window: &WebviewWindow) -> Option<(f64, f64)> {
    let (Ok(cursor), Ok(position), Ok(size)) = (window.cursor_position(), window.outer_position(), window.outer_size()) else {
        return None;
    };
    let window_scale = window.scale_factor().unwrap_or(1.0);
    let cursor_scale = window
        .primary_monitor()
        .ok()
        .flatten()
        .map(|m| m.scale_factor())
        .unwrap_or(window_scale);
    let (cx, cy) = (cursor.x / cursor_scale, cursor.y / cursor_scale);
    let (x0, y0) = (position.x as f64 / window_scale, position.y as f64 / window_scale);
    let (w, h) = (size.width as f64 / window_scale, size.height as f64 / window_scale);
    let (rx, ry) = (cx - x0, cy - y0);
    (rx >= 0.0 && rx < w && ry >= 0.0 && ry < h).then_some((rx, ry))
}

/// Is the cursor over the overlay? In the panel layout the transparent
/// gutter beside the panel does not count (it is the board) unless the
/// sideboard or the settings are flown out into it.
fn cursor_over_overlay(window: &WebviewWindow, point: Option<(f64, f64)>, layout: Layout, dock: Dock, scale_pct: u32, whole_window: bool) -> bool {
    let Some((rx, _)) = point else { return false };
    if layout != Layout::Panel || whole_window {
        return true;
    }
    let Ok(size) = window.outer_size() else { return false };
    let width = size.width as f64 / window.scale_factor().unwrap_or(1.0);
    let gutter = dock::PANEL_GUTTER as f64 * scale_pct.clamp(50, 200) as f64 / 100.0;
    // The gutter sits on the board side: right of a left-docked panel, left otherwise.
    match dock {
        Dock::Left => rx < width - gutter,
        Dock::Right | Dock::Float => rx >= gutter,
    }
}

/// Where the cursor is over the page, for the page's own hover handling:
/// WebKit does not deliver mouse-move events to this never-key window
/// until it is clicked, so the page cannot see hovering on its own.
#[derive(Clone, Copy, PartialEq, serde::Serialize)]
struct CursorPoint {
    x: i32,
    y: i32,
}

/// One window's hover timers, kept by the cursor watch between passes.
#[derive(Default)]
struct HoverTrack {
    inside_since: Option<std::time::Instant>,
    outside_since: Option<std::time::Instant>,
    last_point: Option<Option<CursorPoint>>,
}

fn start_cursor_watch(app: AppHandle) {
    std::thread::Builder::new()
        .name("cursor-watch".into())
        .spawn(move || {
            let mut tracks = [HoverTrack::default(), HoverTrack::default()];
            loop {
                std::thread::sleep(CURSOR_POLL);
                for (pane, track) in Pane::ALL.into_iter().zip(tracks.iter_mut()) {
                    finish_drag(&app, pane);
                    watch_pane(&app, pane, track);
                }
            }
        })
        .expect("cursor watch thread");
}

/// One pass of the cursor watch for one window: tell its page where the
/// cursor is, hand the mouse to Arena off the panel, unfold a hovered rail
/// and fold an unpinned panel the cursor has left.
fn watch_pane(app: &AppHandle, pane: Pane, track: &mut HoverTrack) {
    let Some(window) = app.get_webview_window(pane.label()) else {
        *track = HoverTrack::default();
        return;
    };
    let (layout, pinned, panel_on, visible, flyout, sideboard, dock, scale, return_after) = {
        let state = app.state::<AppState>();
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        let own = runtime.pane(pane);
        let prefs = pane_prefs(&settings, pane);
        (
            own.layout,
            prefs.pinned,
            // A deck panel that is off has no rail to hover.
            prefs.open && (pane != Pane::Deck || settings.deck_panel),
            runtime.visible(pane, &settings),
            own.flyout_open,
            own.sideboard_open,
            prefs.dock,
            settings.scale,
            Duration::from_secs(u64::from(settings.return_after_seconds.max(1))),
        )
    };
    if !visible {
        track.inside_since = None;
        track.outside_since = None;
        return;
    }
    let now = std::time::Instant::now();
    let point = cursor_in_window(&window);
    // The page hit-tests the panel's rows itself; tell it where the cursor
    // is whenever that changes (and once when it leaves).
    let page_point = if layout == Layout::Panel {
        point.map(|(x, y)| CursorPoint { x: x.round() as i32, y: y.round() as i32 })
    } else {
        None
    };
    if track.last_point != Some(page_point) {
        track.last_point = Some(page_point);
        let _ = app.emit_to(EventTarget::webview_window(pane.label()), "overlay-cursor", page_point);
    }
    let inside = cursor_over_overlay(&window, point, layout, dock, scale, flyout || sideboard);
    if inside {
        track.outside_since = None;
        track.inside_since.get_or_insert(now);
    } else {
        track.inside_since = None;
        track.outside_since.get_or_insert(now);
    }
    let armed = {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        let own = runtime.pane_mut(pane);
        own.cursor_on_overlay = inside;
        if !inside {
            own.rail_hover_armed = true;
        }
        own.rail_hover_armed
    };
    // Off the panel the window hands the mouse to Arena; back on it (or
    // once a drag has settled) it takes it again.
    apply_click_through(app, pane);
    match layout {
        // Hover only means something once the player has turned the panel
        // on and left it unpinned: then the rail is the folded panel and
        // hovering it unfolds it. A rail that was never opened, or was
        // closed, stays a rail.
        Layout::Rail => {
            // With the settings open beside the rail the player is in the
            // settings, not asking for the deck.
            if panel_on && !pinned && !flyout && inside && armed && track.inside_since.map_or(false, |t| now.duration_since(t) >= RAIL_HOVER_OPEN) {
                diag::log(format!("cursor: over the {} rail — unfolding the panel", pane.label()));
                set_layout_inner(app, pane, Layout::Panel, Why::Auto);
            }
        }
        Layout::Panel => {
            if !pinned && !flyout && !inside && track.outside_since.map_or(false, |t| now.duration_since(t) >= return_after) {
                diag::log(format!("cursor: off the unpinned {} panel — folding back into the rail", pane.label()));
                set_layout_inner(app, pane, Layout::Rail, Why::Auto);
            }
        }
    }
}

/// The page's console for things worth keeping (errors, link changes).
#[tauri::command]
fn page_log(window: WebviewWindow, message: String) {
    if Pane::of(&window) == Pane::Opponent {
        diag::log(format!("page (opponent): {message}"));
    } else {
        diag::log(format!("page: {message}"));
    }
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

/// `--api URL` on the command line overrides the saved API URL (the
/// menu-bar app passes the dashboard's actual port).
fn api_url_from_args() -> Option<String> {
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == "--api" {
            return args.next();
        }
        if let Some(rest) = arg.strip_prefix("--api=") {
            return Some(rest.to_string());
        }
    }
    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            diag::log(format!("request from a second launch: {args:?}"));
            handle_request(app, &args);
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .on_page_load(|webview, payload| {
            diag::log(format!("webview {} {:?}: {:?}", webview.label(), payload.event(), payload.url().as_str()));
        })
        .invoke_handler(tauri::generate_handler![
            get_settings,
            update_settings,
            set_layout,
            set_content_height,
            set_pinned,
            get_layout,
            arena_status,
            platform,
            hide_overlay,
            quit_overlay,
            set_page_open,
            share_payload,
            latest_payload,
            open_settings,
            page_log,
        ])
        .setup(|app| {
            let settings_path = app
                .path()
                .app_config_dir()
                .map(|dir| dir.join(SETTINGS_FILE))
                .unwrap_or_else(|_| std::path::PathBuf::from(SETTINGS_FILE));
            let log_path = diag::path_from_args()
                .unwrap_or_else(|| settings_path.with_file_name("overlay.log"));
            diag::open(&log_path);
            diag::log(format!(
                "Tapps Overlay {} starting: settings={} args={:?}",
                env!("CARGO_PKG_VERSION"),
                settings_path.display(),
                std::env::args().skip(1).collect::<Vec<_>>()
            ));
            let mut settings = Settings::load(&settings_path);
            if let Some(url) = api_url_from_args() {
                settings.api_url = url;
            }
            if let Some((deck, opponent)) = panels_from_args(std::env::args().skip(1)) {
                settings.deck_panel = deck;
                settings.opponent_panel = opponent;
            }
            diag::log(format!(
                "settings: dock={:?} api={} hide_when_arena_not_in_front={} deck_panel={} opponent_panel={}",
                settings.dock, settings.api_url, settings.hide_when_arena_not_in_front, settings.deck_panel, settings.opponent_panel
            ));
            let runtime = Runtime {
                monitor: settings.monitor.clone(),
                ..Runtime::default()
            };
            app.manage(AppState {
                settings: Mutex::new(settings),
                runtime: Mutex::new(runtime),
                settings_path,
                latest_payload: Mutex::new(serde_json::Value::Null),
            });
            // No Dock icon, no app switcher entry: the overlay is a HUD, and
            // the tracker's menu bar is its only chrome.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let handle = app.handle().clone();
            if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                configure_window(&handle, &window, Pane::Deck);
            } else {
                diag::log("no main window — the window failed to build");
            }
            sync_opponent_window(&handle);
            apply_geometry(&handle);
            register_hotkeys(&handle);
            refresh_visibility(&handle);
            start_arena_poll(handle.clone());
            start_cursor_watch(handle.clone());
            let args: Vec<String> = std::env::args().skip(1).collect();
            if let Some(pid) = parent::pid_from_args(&args) {
                parent::watch(pid);
            }
            parent::start(handle.clone());
            diag::log("setup complete");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Tapps Overlay");
}

/// After a drag: keep a docked window on its edge (only y moves) and
/// remember where it ended up.
fn on_moved(app: &AppHandle, pane: Pane, physical_x: i32, physical_y: i32) {
    let Some(window) = app.get_webview_window(pane.label()) else { return };
    let state = app.state::<AppState>();
    let scale = window.scale_factor().unwrap_or(1.0);
    let logical = tauri::PhysicalPosition::new(physical_x, physical_y).to_logical::<i32>(scale);
    {
        let runtime = state.runtime.lock().unwrap();
        let own = runtime.pane(pane);
        if let Some((px, py)) = own.placed_at {
            // Allow a pixel of rounding between logical and physical.
            if (px - logical.x).abs() <= 1 && (py - logical.y).abs() <= 1 {
                return;
            }
        }
        if let Some(when) = own.placed_when {
            // The echo of a resize we just made, not a drag.
            if when.elapsed() < Duration::from_millis(500) {
                return;
            }
        }
    }
    // A drag: remember where it is now; finish_drag snaps and saves once
    // the Moved events stop coming (see PaneRuntime::drag).
    state.runtime.lock().unwrap().pane_mut(pane).drag = Some(((logical.x, logical.y), std::time::Instant::now()));
}

/// How long after the last Moved event a drag counts as finished.
const DRAG_SETTLE: Duration = Duration::from_millis(150);

/// Called from the cursor watch: once a drag has been quiet for
/// DRAG_SETTLE, put the window back on its edge (docked: x is the edge, only
/// y moves; float: kept on screen) and remember the position.
fn finish_drag(app: &AppHandle, pane: Pane) {
    let Some(window) = app.get_webview_window(pane.label()) else { return };
    let state = app.state::<AppState>();
    let dropped = {
        let mut runtime = state.runtime.lock().unwrap();
        let own = runtime.pane_mut(pane);
        match own.drag {
            Some((pos, when)) if when.elapsed() >= DRAG_SETTLE => {
                own.drag = None;
                Some(pos)
            }
            _ => None,
        }
    };
    let Some((dx, dy)) = dropped else { return };
    let area = target_monitor(&window, &MonitorHint::take(&state));
    let (dock, size) = {
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        (pane_prefs(&settings, pane).dock, pane_size(&settings, &runtime, pane, &area))
    };
    let (x, y) = dock::constrain_drag(dock, (dx, dy), size, &area);
    {
        let mut settings = state.settings.lock().unwrap();
        match (pane, dock) {
            (Pane::Deck, Dock::Left) => settings.positions.left_y = Some(y),
            (Pane::Deck, Dock::Right) => settings.positions.right_y = Some(y),
            (Pane::Deck, Dock::Float) => {
                settings.positions.float_x = Some(x);
                settings.positions.float_y = Some(y);
            }
            (Pane::Opponent, Dock::Left) => settings.positions.opponent_left_y = Some(y),
            (Pane::Opponent, _) => settings.positions.opponent_right_y = Some(y),
        }
        let mut runtime = state.runtime.lock().unwrap();
        let own = runtime.pane_mut(pane);
        own.placed_at = Some((x, y));
        own.placed_when = Some(std::time::Instant::now());
    }
    if (x, y) != (dx, dy) {
        diag::log(format!("drag {}: dropped at ({dx}, {dy}), snapped to ({x}, {y})", pane.label()));
        // No lock held: the Moved this produces is our own placement (placed_at).
        let _ = window.set_position(LogicalPosition::new(x, y));
    }
    save_settings(app);
}
