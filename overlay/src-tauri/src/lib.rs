//! Tapps Overlay — the Tauri shell.
//!
//! One always-on-top, frameless, transparent window that switches between
//! the rail and the panel layout, docks flush to a screen edge, and answers
//! the page's commands. The page (Preact) owns everything that is drawn; this
//! side owns the window, the global hotkeys, the Arena poll, and
//! the settings file.

mod arena;
mod diag;
mod dock;
mod settings;

use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewWindow, WindowEvent};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

use arena::ArenaStatus;
use dock::{Layout, Rect};
use settings::{Dock, Settings};

const MAIN_WINDOW: &str = "main";
const SETTINGS_FILE: &str = "overlay.json";
const ARENA_POLL: Duration = Duration::from_secs(1);
/// The cursor watch (rail hover opens the panel; an unpinned panel folds
/// away after the cursor has been off it for the return delay). Done here
/// from the real cursor position rather than from the page's mouse events:
/// a non-activating overlay is never the key window, and WebKit does not
/// deliver hover / mouseleave reliably to one.
const CURSOR_POLL: Duration = Duration::from_millis(100);
const RAIL_HOVER_OPEN: Duration = Duration::from_millis(300);

/// Everything about the window that is not a saved preference.
#[derive(Debug, Clone)]
struct Runtime {
    layout: Layout,
    pinned: bool,
    /// The player hid it (hotkey / tracker menu); stays hidden until they show it.
    hidden_by_user: bool,
    /// Hidden because Arena is not running, or not in front (setting).
    hidden_for_arena: bool,
    /// Shown regardless of Arena while a flyout opened from the tracker's menu is up.
    force_show: bool,
    /// The monitor the window was last placed on. Sticky: it only changes
    /// when Arena's window turns up on another one.
    area: Option<Rect>,
    /// The panel's content height as measured by the page (logical px).
    content_height: i32,
    /// Monitor name the window is docked on, when known.
    monitor: Option<String>,
    /// Set while we move the window ourselves so the Moved handler doesn't re-snap.
    snapping: bool,
    /// Where we last put the window (logical). A Moved event that lands
    /// exactly there is the echo of our own placement, not a user drag —
    /// otherwise the panel's clamped y would overwrite the rail's.
    placed_at: Option<(i32, i32)>,
    /// When we last placed the window. A resize can move the window's origin
    /// before our set_position lands (macOS keeps the bottom edge put), and
    /// that intermediate Moved must not be mistaken for a drag and saved.
    placed_when: Option<std::time::Instant>,
    last_arena: ArenaStatus,
    /// The page's ⚙ flyout is open: an unpinned panel must not fold away.
    flyout_open: bool,
    /// The sideboard flies out into the transparent gutter: while it shows,
    /// the whole window counts as "over the panel" for the cursor watch.
    sideboard_open: bool,
    /// Hovering the rail opens the panel — but not straight after the panel
    /// folded away under the cursor (game end, return timer): the cursor has
    /// to leave the rail once first, or it would spring back open.
    rail_hover_armed: bool,
}

impl Default for Runtime {
    fn default() -> Self {
        Self {
            layout: Layout::Rail,
            pinned: true,
            hidden_by_user: false,
            hidden_for_arena: true,
            force_show: false,
            area: None,
            content_height: 620,
            monitor: None,
            snapping: false,
            placed_at: None,
            placed_when: None,
            last_arena: ArenaStatus::default(),
            flyout_open: false,
            sideboard_open: false,
            rail_hover_armed: true,
        }
    }
}

struct AppState {
    settings: Mutex<Settings>,
    runtime: Mutex<Runtime>,
    settings_path: std::path::PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LayoutInfo {
    layout: String,
    pinned: bool,
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
fn target_monitor(window: &WebviewWindow, runtime: &Runtime, follow_arena: bool) -> Rect {
    let monitors = monitor_rects(window);
    if monitors.is_empty() {
        return Rect { x: 0, y: 0, width: 1920, height: 1080 };
    }
    if follow_arena {
        if let Some(index) = runtime.last_arena.bounds.and_then(|b| arena_monitor_index(window, b)) {
            if let Some((rect, _)) = monitors.get(index) {
                return *rect;
            }
        }
    }
    if let Some(area) = runtime.area {
        if monitors.iter().any(|(rect, _)| *rect == area) {
            return area;
        }
    }
    if let Some(name) = runtime.monitor.as_ref() {
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

/// Size and place the window for the current layout / dock / remembered offset.
fn apply_geometry(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else { return };
    let state = app.state::<AppState>();
    let settings = state.settings.lock().unwrap().clone();
    let mut runtime = state.runtime.lock().unwrap();
    let area = target_monitor(&window, &runtime, settings.follow_arena);
    runtime.area = Some(area);
    let size = dock::size_for(runtime.layout, runtime.content_height, &area, settings.panel_max_height_pct, settings.scale);
    let y = match settings.dock {
        Dock::Left => settings.positions.left_y,
        Dock::Right => settings.positions.right_y,
        Dock::Float => None,
    };
    let float_at = match (settings.positions.float_x, settings.positions.float_y) {
        (Some(x), Some(y)) => Some((x, y)),
        _ => None,
    };
    let (x, y) = dock::docked_position(settings.dock, size, &area, y, float_at);
    runtime.snapping = true;
    runtime.placed_at = Some((x, y));
    runtime.placed_when = Some(std::time::Instant::now());
    let sized = window.set_size(LogicalSize::new(size.width, size.height));
    let placed = window.set_position(LogicalPosition::new(x, y));
    runtime.snapping = false;
    diag::log(format!(
        "geometry: layout={:?} dock={:?} monitor={:?} size={}x{} at ({}, {}) set_size={:?} set_position={:?}",
        runtime.layout, settings.dock, area, size.width, size.height, x, y, sized.err(), placed.err()
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
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else { return };
    let state = app.state::<AppState>();
    let runtime = state.runtime.lock().unwrap();
    let show = !runtime.hidden_by_user && (runtime.force_show || !runtime.hidden_for_arena);
    if show {
        let shown = window.show();
        let top = window.set_always_on_top(true);
        raise_above_fullscreen(&window);
        diag::log(format!(
            "show: show={:?} always_on_top={:?} is_visible={:?}",
            shown.err(), top.err(), window.is_visible().ok()
        ));
    } else {
        let hidden = window.hide();
        diag::log(format!(
            "hide: by_user={} for_arena={} hide={:?}",
            runtime.hidden_by_user, runtime.hidden_for_arena, hidden.err()
        ));
    }
}

fn emit_layout(app: &AppHandle) {
    let state = app.state::<AppState>();
    let settings = state.settings.lock().unwrap();
    let runtime = state.runtime.lock().unwrap();
    let info = LayoutInfo {
        layout: match runtime.layout {
            Layout::Rail => "rail".into(),
            Layout::Panel => "panel".into(),
        },
        pinned: runtime.pinned,
        visible: !runtime.hidden_by_user && (runtime.force_show || !runtime.hidden_for_arena),
        dock: settings.dock,
    };
    let _ = app.emit("overlay-layout", info);
}

/// Switch layouts. Opening the panel pins it per the "open pinned" setting
/// unless `pinned` says otherwise (a hover-opened panel is never pinned: it
/// came out because the cursor is there and goes back when it leaves).
fn set_layout_inner(app: &AppHandle, layout: Layout, pinned: Option<bool>) {
    {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        runtime.layout = layout;
        match layout {
            Layout::Panel => {
                runtime.pinned = pinned.unwrap_or_else(|| state.settings.lock().unwrap().open_pinned);
            }
            Layout::Rail => {
                runtime.rail_hover_armed = false;
            }
        }
    }
    apply_geometry(app);
    apply_click_through(app);
    emit_layout(app);
}

fn apply_click_through(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else { return };
    let state = app.state::<AppState>();
    let settings = state.settings.lock().unwrap();
    let runtime = state.runtime.lock().unwrap();
    let through = runtime.layout == Layout::Panel && runtime.pinned && settings.click_through_when_pinned;
    let _ = window.set_ignore_cursor_events(through);
}

fn toggle_layout(app: &AppHandle) {
    let next = {
        let state = app.state::<AppState>();
        let runtime = state.runtime.lock().unwrap();
        match runtime.layout {
            Layout::Rail => Layout::Panel,
            Layout::Panel => Layout::Rail,
        }
    };
    set_layout_inner(app, next, None);
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

/// Register (or re-register) the two global hotkeys from the settings.
fn register_hotkeys(app: &AppHandle) {
    let shortcuts = app.global_shortcut();
    let _ = shortcuts.unregister_all();
    let (toggle, visibility) = {
        let state = app.state::<AppState>();
        let settings = state.settings.lock().unwrap();
        let keys = settings.hotkeys();
        (keys.toggle.clone(), keys.visibility.clone())
    };
    let toggle_key = toggle.clone();
    if let Err(err) = shortcuts.on_shortcut(toggle.as_str(), move |app, _shortcut, event| {
        if event.state() == ShortcutState::Pressed {
            toggle_layout(app);
        }
    }) {
        diag::log(format!("hotkey {toggle_key} unavailable: {err}"));
    } else {
        diag::log(format!("hotkey {toggle_key} registered (toggle)"));
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
}

// ---------------------------------------------------------------------------
// Requests from the tracker (a second launch with flags; see run())
// ---------------------------------------------------------------------------

/// The tracker's menu bar drives the overlay by starting a second instance
/// with a flag; the single-instance plugin hands those arguments here and
/// the second instance exits. No tray of our own — one menu-bar icon.
fn handle_request(app: &AppHandle, args: &[String]) {
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
                let _ = app.emit("overlay-open-settings", ());
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
                let mut runtime = state.runtime.lock().unwrap();
                let changed = runtime.last_arena != status;
                let moved = status.bounds.is_some() && runtime.last_arena.bounds != status.bounds;
                runtime.last_arena = status;
                let settings = state.settings.lock().unwrap();
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
                if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                    raise_above_fullscreen(&window);
                }
            }
            std::thread::sleep(ARENA_POLL);
        })
        .expect("arena poll thread");
}

// ---------------------------------------------------------------------------
// Commands (the page's API)
// ---------------------------------------------------------------------------

#[tauri::command]
fn get_settings(state: tauri::State<AppState>) -> Settings {
    state.settings.lock().unwrap().clone()
}

#[tauri::command]
fn update_settings(app: AppHandle, state: tauri::State<AppState>, settings: Settings) -> Settings {
    let (hotkeys_changed, next) = {
        let mut current = state.settings.lock().unwrap();
        let next = settings.clamped();
        let hotkeys_changed = current.hotkeys() != next.hotkeys();
        *current = next.clone();
        (hotkeys_changed, next)
    };
    save_settings(&app);
    if hotkeys_changed {
        register_hotkeys(&app);
    }
    apply_geometry(&app);
    apply_click_through(&app);
    emit_layout(&app);
    next
}

#[tauri::command]
fn set_layout(app: AppHandle, layout: String, content_height: Option<i32>, pinned: Option<bool>) -> LayoutInfo {
    if let Some(height) = content_height {
        let state = app.state::<AppState>();
        state.runtime.lock().unwrap().content_height = height.max(0);
    }
    let target = if layout == "panel" { Layout::Panel } else { Layout::Rail };
    set_layout_inner(&app, target, pinned);
    current_layout(&app)
}

#[tauri::command]
fn set_content_height(app: AppHandle, height: i32) {
    let resize = {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        let next = height.max(0);
        let changed = runtime.content_height != next;
        runtime.content_height = next;
        changed && runtime.layout == Layout::Panel
    };
    if resize {
        apply_geometry(&app);
    }
}

#[tauri::command]
fn set_pinned(app: AppHandle, pinned: bool) -> LayoutInfo {
    {
        let state = app.state::<AppState>();
        state.runtime.lock().unwrap().pinned = pinned;
    }
    apply_click_through(&app);
    emit_layout(&app);
    current_layout(&app)
}

#[tauri::command]
fn get_layout(app: AppHandle) -> LayoutInfo {
    current_layout(&app)
}

fn current_layout(app: &AppHandle) -> LayoutInfo {
    let state = app.state::<AppState>();
    let settings = state.settings.lock().unwrap();
    let runtime = state.runtime.lock().unwrap();
    LayoutInfo {
        layout: match runtime.layout {
            Layout::Rail => "rail".into(),
            Layout::Panel => "panel".into(),
        },
        pinned: runtime.pinned,
        visible: !runtime.hidden_by_user && (runtime.force_show || !runtime.hidden_for_arena),
        dock: settings.dock,
    }
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
    app.exit(0);
}

/// What the page has flown out (the ⚙ flyout, the sideboard). The flyout
/// closing also hands a window the tracker's menu forced open back to the
/// Arena rule.
#[tauri::command]
fn set_page_open(app: AppHandle, flyout: bool, sideboard: bool) {
    let was_forced = {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        runtime.flyout_open = flyout;
        runtime.sideboard_open = sideboard;
        !flyout && std::mem::replace(&mut runtime.force_show, false)
    };
    if was_forced {
        refresh_visibility(&app);
        emit_layout(&app);
    }
}

/// Is the cursor over the overlay? In the panel layout the transparent
/// gutter beside the panel does not count (it is the board) unless the
/// sideboard is flown out into it. Compared in logical coordinates: on
/// macOS the cursor and the window can be scaled by different monitors.
fn cursor_over_overlay(window: &WebviewWindow, layout: Layout, dock: Dock, scale_pct: u32, whole_window: bool) -> bool {
    let (Ok(cursor), Ok(position), Ok(size)) = (window.cursor_position(), window.outer_position(), window.outer_size()) else {
        return false;
    };
    let window_scale = window.scale_factor().unwrap_or(1.0);
    let cursor_scale = window
        .primary_monitor()
        .ok()
        .flatten()
        .map(|m| m.scale_factor())
        .unwrap_or(window_scale);
    let (cx, cy) = (cursor.x / cursor_scale, cursor.y / cursor_scale);
    let (mut x0, y0) = (position.x as f64 / window_scale, position.y as f64 / window_scale);
    let (mut x1, y1) = (x0 + size.width as f64 / window_scale, y0 + size.height as f64 / window_scale);
    if layout == Layout::Panel && !whole_window {
        let gutter = dock::PANEL_GUTTER as f64 * scale_pct.clamp(50, 200) as f64 / 100.0;
        // The gutter sits on the board side: right of a left-docked panel, left otherwise.
        match dock {
            Dock::Left => x1 -= gutter,
            Dock::Right | Dock::Float => x0 += gutter,
        }
    }
    cx >= x0 && cx < x1 && cy >= y0 && cy < y1
}

fn start_cursor_watch(app: AppHandle) {
    std::thread::Builder::new()
        .name("cursor-watch".into())
        .spawn(move || {
            let mut inside_since: Option<std::time::Instant> = None;
            let mut outside_since: Option<std::time::Instant> = None;
            loop {
                std::thread::sleep(CURSOR_POLL);
                let Some(window) = app.get_webview_window(MAIN_WINDOW) else { continue };
                let (layout, pinned, visible, flyout, sideboard, dock, scale, return_after) = {
                    let state = app.state::<AppState>();
                    let runtime = state.runtime.lock().unwrap();
                    let settings = state.settings.lock().unwrap();
                    (
                        runtime.layout,
                        runtime.pinned,
                        !runtime.hidden_by_user && (runtime.force_show || !runtime.hidden_for_arena),
                        runtime.flyout_open,
                        runtime.sideboard_open,
                        settings.dock,
                        settings.scale,
                        Duration::from_secs(u64::from(settings.return_after_seconds.max(1))),
                    )
                };
                if !visible {
                    inside_since = None;
                    outside_since = None;
                    continue;
                }
                let now = std::time::Instant::now();
                let inside = cursor_over_overlay(&window, layout, dock, scale, flyout || sideboard);
                if inside {
                    outside_since = None;
                    inside_since.get_or_insert(now);
                } else {
                    inside_since = None;
                    outside_since.get_or_insert(now);
                    let state = app.state::<AppState>();
                    state.runtime.lock().unwrap().rail_hover_armed = true;
                }
                match layout {
                    Layout::Rail => {
                        let armed = app.state::<AppState>().runtime.lock().unwrap().rail_hover_armed;
                        if inside && armed && inside_since.map_or(false, |t| now.duration_since(t) >= RAIL_HOVER_OPEN) {
                            diag::log("cursor: over the rail — opening the panel (unpinned)");
                            set_layout_inner(&app, Layout::Panel, Some(false));
                        }
                    }
                    Layout::Panel => {
                        if !pinned && !flyout && !inside && outside_since.map_or(false, |t| now.duration_since(t) >= return_after) {
                            diag::log("cursor: off the unpinned panel — folding back into the rail");
                            set_layout_inner(&app, Layout::Rail, None);
                        }
                    }
                }
            }
        })
        .expect("cursor watch thread");
}

/// The page's console for things worth keeping (errors, link changes).
#[tauri::command]
fn page_log(message: String) {
    diag::log(format!("page: {message}"));
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
            diag::log(format!("webview {:?}: {:?}", payload.event(), payload.url().as_str()));
            let _ = webview;
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
            diag::log(format!("settings: dock={:?} api={} hide_when_arena_not_in_front={}", settings.dock, settings.api_url, settings.hide_when_arena_not_in_front));
            let runtime = Runtime {
                monitor: settings.monitor.clone(),
                ..Runtime::default()
            };
            app.manage(AppState {
                settings: Mutex::new(settings),
                runtime: Mutex::new(runtime),
                settings_path,
            });
            // No Dock icon, no app switcher entry: the overlay is a HUD, and
            // the tracker's menu bar is its only chrome.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let handle = app.handle().clone();
            if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                let _ = window.set_always_on_top(true);
                let _ = window.set_visible_on_all_workspaces(true);
                let _ = window.set_skip_taskbar(true);
                raise_above_fullscreen(&window);
                let moved_handle = handle.clone();
                window.on_window_event(move |event| match event {
                    WindowEvent::Moved(position) => on_moved(&moved_handle, position.x, position.y),
                    WindowEvent::Focused(focused) => diag::log(format!("window focused={focused}")),
                    WindowEvent::Destroyed => diag::log("window destroyed"),
                    _ => {}
                });
            }
            if app.get_webview_window(MAIN_WINDOW).is_none() {
                diag::log("no main window — the window failed to build");
            }
            apply_geometry(&handle);
            register_hotkeys(&handle);
            refresh_visibility(&handle);
            start_arena_poll(handle.clone());
            start_cursor_watch(handle.clone());
            diag::log("setup complete");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Tapps Overlay");
}

/// After a drag: keep a docked window on its edge (only y moves) and
/// remember where it ended up.
fn on_moved(app: &AppHandle, physical_x: i32, physical_y: i32) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else { return };
    let state = app.state::<AppState>();
    let scale = window.scale_factor().unwrap_or(1.0);
    let logical = tauri::PhysicalPosition::new(physical_x, physical_y).to_logical::<i32>(scale);
    {
        let runtime = state.runtime.lock().unwrap();
        if runtime.snapping {
            return;
        }
        if let Some((px, py)) = runtime.placed_at {
            // Allow a pixel of rounding between logical and physical.
            if (px - logical.x).abs() <= 1 && (py - logical.y).abs() <= 1 {
                return;
            }
        }
        if let Some(when) = runtime.placed_when {
            // The echo of a resize we just made, not a drag.
            if when.elapsed() < Duration::from_millis(500) {
                return;
            }
        }
    }
    let (dock, size, area) = {
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        let area = target_monitor(&window, &runtime, settings.follow_arena);
        (
            settings.dock,
            dock::size_for(runtime.layout, runtime.content_height, &area, settings.panel_max_height_pct, settings.scale),
            area,
        )
    };
    let (x, y) = dock::constrain_drag(dock, (logical.x, logical.y), size, &area);
    {
        let mut settings = state.settings.lock().unwrap();
        match dock {
            Dock::Left => settings.positions.left_y = Some(y),
            Dock::Right => settings.positions.right_y = Some(y),
            Dock::Float => {
                settings.positions.float_x = Some(x);
                settings.positions.float_y = Some(y);
            }
        }
    }
    {
        let mut runtime = state.runtime.lock().unwrap();
        runtime.placed_at = Some((x, y));
        if (x, y) != (logical.x, logical.y) {
            runtime.snapping = true;
            let _ = window.set_position(LogicalPosition::new(x, y));
            runtime.snapping = false;
        }
    }
    save_settings(app);
}
