//! Tapps Overlay — the Tauri shell.
//!
//! One always-on-top, frameless, transparent window that switches between
//! the rail and the panel layout, docks flush to a screen edge, and answers
//! the page's commands. The page (Preact) owns everything that is drawn; this
//! side owns the window, the tray, the global hotkeys, the Arena poll, and
//! the settings file.

mod arena;
mod dock;
mod settings;

use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewWindow, WindowEvent};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

use arena::ArenaStatus;
use dock::{Layout, Rect};
use settings::{Dock, Settings};

const MAIN_WINDOW: &str = "main";
const SETTINGS_FILE: &str = "overlay.json";
const ARENA_POLL: Duration = Duration::from_secs(1);

/// Everything about the window that is not a saved preference.
#[derive(Debug, Clone)]
struct Runtime {
    layout: Layout,
    pinned: bool,
    /// The player hid it (hotkey / tray); stays hidden until they show it.
    hidden_by_user: bool,
    /// Hidden because Arena is not in front.
    hidden_for_focus: bool,
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
    last_arena: ArenaStatus,
}

impl Default for Runtime {
    fn default() -> Self {
        Self {
            layout: Layout::Rail,
            pinned: true,
            hidden_by_user: false,
            hidden_for_focus: false,
            content_height: 620,
            monitor: None,
            snapping: false,
            placed_at: None,
            last_arena: ArenaStatus::default(),
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

/// The monitor the window should dock on: the remembered one when it still
/// exists, else the one under the cursor, else the primary.
fn target_monitor(window: &WebviewWindow, runtime: &Runtime) -> Rect {
    let monitors = monitor_rects(window);
    if monitors.is_empty() {
        return Rect { x: 0, y: 0, width: 1920, height: 1080 };
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
    let area = target_monitor(&window, &runtime);
    let size = dock::size_for(runtime.layout, runtime.content_height, &area);
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
    let _ = window.set_size(LogicalSize::new(size.width, size.height));
    let _ = window.set_position(LogicalPosition::new(x, y));
    runtime.snapping = false;
}

fn refresh_visibility(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else { return };
    let state = app.state::<AppState>();
    let runtime = state.runtime.lock().unwrap();
    let show = !runtime.hidden_by_user && !runtime.hidden_for_focus;
    if show {
        let _ = window.show();
        let _ = window.set_always_on_top(true);
    } else {
        let _ = window.hide();
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
        visible: !runtime.hidden_by_user && !runtime.hidden_for_focus,
        dock: settings.dock,
    };
    let _ = app.emit("overlay-layout", info);
}

fn set_layout_inner(app: &AppHandle, layout: Layout) {
    {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        runtime.layout = layout;
        if layout == Layout::Panel {
            runtime.pinned = state.settings.lock().unwrap().open_pinned;
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
    set_layout_inner(app, next);
}

fn toggle_hidden(app: &AppHandle) {
    {
        let state = app.state::<AppState>();
        let mut runtime = state.runtime.lock().unwrap();
        runtime.hidden_by_user = !runtime.hidden_by_user;
    }
    refresh_visibility(app);
    emit_layout(app);
    sync_tray(app);
}

fn save_settings(app: &AppHandle) {
    let state = app.state::<AppState>();
    let settings = state.settings.lock().unwrap().clone();
    if let Err(err) = settings.save(&state.settings_path) {
        eprintln!("overlay: could not save settings: {err}");
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
        eprintln!("overlay: hotkey {toggle_key} unavailable: {err}");
    }
    let visibility_key = visibility.clone();
    if let Err(err) = shortcuts.on_shortcut(visibility.as_str(), move |app, _shortcut, event| {
        if event.state() == ShortcutState::Pressed {
            toggle_hidden(app);
        }
    }) {
        eprintln!("overlay: hotkey {visibility_key} unavailable: {err}");
    }
}

// ---------------------------------------------------------------------------
// Tray
// ---------------------------------------------------------------------------

const TRAY_SHOW: &str = "tray-show";
const TRAY_DOCK_LEFT: &str = "tray-dock-left";
const TRAY_DOCK_RIGHT: &str = "tray-dock-right";
const TRAY_DOCK_FLOAT: &str = "tray-dock-float";
const TRAY_SETTINGS: &str = "tray-settings";
const TRAY_QUIT: &str = "tray-quit";

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let (dock, visible) = {
        let state = app.state::<AppState>();
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        (settings.dock, !runtime.hidden_by_user)
    };
    let show = CheckMenuItem::with_id(app, TRAY_SHOW, "Show Overlay", true, visible, None::<&str>)?;
    let left = CheckMenuItem::with_id(app, TRAY_DOCK_LEFT, "Left edge", true, dock == Dock::Left, None::<&str>)?;
    let right = CheckMenuItem::with_id(app, TRAY_DOCK_RIGHT, "Right edge", true, dock == Dock::Right, None::<&str>)?;
    let float = CheckMenuItem::with_id(app, TRAY_DOCK_FLOAT, "Floating", true, dock == Dock::Float, None::<&str>)?;
    let dock_menu = Submenu::with_items(app, "Dock", true, &[&left, &right, &float])?;
    let settings_item = MenuItem::with_id(app, TRAY_SETTINGS, "Settings…", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT, "Quit Overlay", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[&show, &PredefinedMenuItem::separator(app)?, &dock_menu, &settings_item, &PredefinedMenuItem::separator(app)?, &quit],
    )?;
    let mut builder = TrayIconBuilder::with_id("main")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .tooltip("Tapps Overlay")
        .on_menu_event(|app, event| match event.id().as_ref() {
            TRAY_SHOW => toggle_hidden(app),
            TRAY_DOCK_LEFT => set_dock(app, Dock::Left),
            TRAY_DOCK_RIGHT => set_dock(app, Dock::Right),
            TRAY_DOCK_FLOAT => set_dock(app, Dock::Float),
            TRAY_SETTINGS => {
                {
                    let state = app.state::<AppState>();
                    let mut runtime = state.runtime.lock().unwrap();
                    runtime.hidden_by_user = false;
                }
                refresh_visibility(app);
                let _ = app.emit("overlay-open-settings", ());
            }
            TRAY_QUIT => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

/// Re-tick the tray's check items after a change from the page or a hotkey.
fn sync_tray(app: &AppHandle) {
    let Some(tray) = app.tray_by_id("main") else { return };
    let (dock, visible) = {
        let state = app.state::<AppState>();
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        (settings.dock, !runtime.hidden_by_user)
    };
    // Rebuilding the small menu is simpler and cheaper than holding item handles.
    if let Ok(show) = CheckMenuItem::with_id(app, TRAY_SHOW, "Show Overlay", true, visible, None::<&str>) {
        if let (Ok(left), Ok(right), Ok(float)) = (
            CheckMenuItem::with_id(app, TRAY_DOCK_LEFT, "Left edge", true, dock == Dock::Left, None::<&str>),
            CheckMenuItem::with_id(app, TRAY_DOCK_RIGHT, "Right edge", true, dock == Dock::Right, None::<&str>),
            CheckMenuItem::with_id(app, TRAY_DOCK_FLOAT, "Floating", true, dock == Dock::Float, None::<&str>),
        ) {
            if let (Ok(dock_menu), Ok(settings_item), Ok(quit), Ok(sep1), Ok(sep2)) = (
                Submenu::with_items(app, "Dock", true, &[&left, &right, &float]),
                MenuItem::with_id(app, TRAY_SETTINGS, "Settings…", true, None::<&str>),
                MenuItem::with_id(app, TRAY_QUIT, "Quit Overlay", true, None::<&str>),
                PredefinedMenuItem::separator(app),
                PredefinedMenuItem::separator(app),
            ) {
                if let Ok(menu) = Menu::with_items(app, &[&show, &sep1, &dock_menu, &settings_item, &sep2, &quit]) {
                    let _ = tray.set_menu(Some(menu));
                }
            }
        }
    }
}

fn set_dock(app: &AppHandle, dock: Dock) {
    {
        let state = app.state::<AppState>();
        state.settings.lock().unwrap().dock = dock;
    }
    save_settings(app);
    apply_geometry(app);
    emit_layout(app);
    sync_tray(app);
}

// ---------------------------------------------------------------------------
// Arena poll
// ---------------------------------------------------------------------------

fn start_arena_poll(app: AppHandle) {
    std::thread::Builder::new()
        .name("arena-poll".into())
        .spawn(move || loop {
            let status = arena::probe();
            let (changed, hide_setting) = {
                let state = app.state::<AppState>();
                let mut runtime = state.runtime.lock().unwrap();
                let changed = runtime.last_arena != status;
                runtime.last_arena = status;
                let hide_setting = state.settings.lock().unwrap().hide_when_arena_not_in_front;
                (changed, hide_setting)
            };
            if changed {
                let _ = app.emit("arena-status", status);
            }
            // Hide only when Arena is running and something else took focus;
            // the overlay itself having focus (the flyout) never hides it.
            let should_hide = hide_setting && status.running && !status.frontmost && !status.overlay_frontmost;
            let flip = {
                let state = app.state::<AppState>();
                let mut runtime = state.runtime.lock().unwrap();
                if runtime.hidden_for_focus != should_hide {
                    runtime.hidden_for_focus = should_hide;
                    true
                } else {
                    false
                }
            };
            if flip {
                refresh_visibility(&app);
                emit_layout(&app);
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
    let (dock_changed, hotkeys_changed, next) = {
        let mut current = state.settings.lock().unwrap();
        let next = settings.clamped();
        let dock_changed = current.dock != next.dock;
        let hotkeys_changed = current.hotkeys() != next.hotkeys();
        *current = next.clone();
        (dock_changed, hotkeys_changed, next)
    };
    save_settings(&app);
    if hotkeys_changed {
        register_hotkeys(&app);
    }
    apply_geometry(&app);
    apply_click_through(&app);
    if dock_changed {
        sync_tray(&app);
    }
    emit_layout(&app);
    next
}

#[tauri::command]
fn set_layout(app: AppHandle, layout: String, content_height: Option<i32>) -> LayoutInfo {
    if let Some(height) = content_height {
        let state = app.state::<AppState>();
        state.runtime.lock().unwrap().content_height = height.max(0);
    }
    let target = if layout == "panel" { Layout::Panel } else { Layout::Rail };
    set_layout_inner(&app, target);
    current_layout(&app)
}

#[tauri::command]
fn set_content_height(app: AppHandle, height: i32) {
    {
        let state = app.state::<AppState>();
        state.runtime.lock().unwrap().content_height = height.max(0);
    }
    let is_panel = {
        let state = app.state::<AppState>();
        let panel = state.runtime.lock().unwrap().layout == Layout::Panel;
        panel
    };
    if is_panel {
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
        visible: !runtime.hidden_by_user && !runtime.hidden_for_focus,
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
    sync_tray(&app);
}

#[tauri::command]
fn quit_overlay(app: AppHandle) {
    app.exit(0);
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
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // A second launch just shows the first one.
            {
                let state = app.state::<AppState>();
                state.runtime.lock().unwrap().hidden_by_user = false;
            }
            refresh_visibility(app);
            emit_layout(app);
            sync_tray(app);
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
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
        ])
        .setup(|app| {
            let settings_path = app
                .path()
                .app_config_dir()
                .map(|dir| dir.join(SETTINGS_FILE))
                .unwrap_or_else(|_| std::path::PathBuf::from(SETTINGS_FILE));
            let mut settings = Settings::load(&settings_path);
            if let Some(url) = api_url_from_args() {
                settings.api_url = url;
            }
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
            // the tray icon is its only chrome.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            let handle = app.handle().clone();
            if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                let _ = window.set_always_on_top(true);
                let _ = window.set_visible_on_all_workspaces(true);
                let _ = window.set_skip_taskbar(true);
                let moved_handle = handle.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::Moved(position) = event {
                        on_moved(&moved_handle, position.x, position.y);
                    }
                });
            }
            apply_geometry(&handle);
            build_tray(&handle)?;
            register_hotkeys(&handle);
            refresh_visibility(&handle);
            start_arena_poll(handle.clone());
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
    }
    let (dock, size, area) = {
        let settings = state.settings.lock().unwrap();
        let runtime = state.runtime.lock().unwrap();
        let area = target_monitor(&window, &runtime);
        (settings.dock, dock::size_for(runtime.layout, runtime.content_height, &area), area)
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
