//! Overlay preferences: `overlay.json` in the app's config directory.
//!
//! Everything the ⚙ flyout can change lives here and is written the moment
//! it changes. Hotkeys are stored per platform so a settings file copied
//! between machines never binds a Command chord on Windows.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Dock {
    Left,
    Right,
    Float,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Lands {
    Grouped,
    All,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum NameColor {
    /// Card names in their type colour (creature, instant, ...).
    Type,
    White,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Density {
    Comfortable,
    Compact,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Hotkeys {
    /// Toggle rail ↔ panel.
    pub toggle: String,
    /// Hide / show the overlay.
    pub visibility: String,
}

impl Default for Hotkeys {
    fn default() -> Self {
        // Same physical chord on both platforms: the key left of the space
        // bar (Option / Alt) + Shift + letter. `Alt` is the accelerator
        // spelling the global-shortcut plugin maps to Option on macOS.
        Self {
            toggle: "Alt+Shift+T".into(),
            visibility: "Alt+Shift+H".into(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Positions {
    /// Vertical offset of the top edge, per docked side (logical px).
    pub left_y: Option<i32>,
    pub right_y: Option<i32>,
    /// Free position when floating.
    pub float_x: Option<i32>,
    pub float_y: Option<i32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Settings {
    /// The background slider, 0.0–1.0. Text, lines and numbers are always
    /// fully visible; this only drives the charcoal ground, which tops out
    /// at about 88 % at 1.0 and is gone at 0.0.
    pub opacity: f64,
    /// The same slider for the minimized rail alone; it is small enough that
    /// people want it darker (or lighter) than the panel.
    pub rail_opacity: f64,
    /// Size of everything, percent (50–200). The page lays out at its base
    /// size and is scaled; the window grows to match.
    pub scale: u32,
    /// The panel never grows taller than this (logical pixels, before
    /// Scale); the list scrolls inside it instead. Always capped by the
    /// screen as well.
    pub panel_max_height: u32,
    pub dock: Dock,
    pub return_after_seconds: u32,
    /// The deck panel is "on": the player opened it (arrow / hotkey) and has
    /// not closed it (chevron / hotkey). Remembered across games and
    /// launches. Off means the rail is just a rail — hovering it does nothing.
    pub panel_open: bool,
    /// Pinned stays out; unpinned slides out when the rail is hovered and
    /// folds back after the cursor leaves. Toggled by the pin button,
    /// remembered.
    pub panel_pinned: bool,
    pub click_through_when_pinned: bool,
    pub lands: Lands,
    pub density: Density,
    pub name_color: NameColor,
    pub follow_arena: bool,
    pub hide_when_arena_not_in_front: bool,
    pub api_url: String,
    pub hotkeys_macos: Hotkeys,
    pub hotkeys_windows: Hotkeys,
    pub positions: Positions,
    /// Which monitor (by name) the overlay last docked to, for multi-monitor setups.
    pub monitor: Option<String>,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            opacity: 0.8,
            rail_opacity: 0.9,
            scale: 100,
            panel_max_height: 800,
            dock: Dock::Left,
            return_after_seconds: 4,
            panel_open: false,
            // Pinned by default: an opened panel stays until it is unpinned.
            // (Unpinned it folds back to the rail seconds after the cursor
            // leaves, which reads as "it disappeared" the first time.)
            panel_pinned: true,
            // Off by default: with it on, the panel can only be driven by the
            // hotkeys and the tray (every click reaches Arena instead).
            click_through_when_pinned: false,
            lands: Lands::Grouped,
            density: Density::Comfortable,
            name_color: NameColor::Type,
            follow_arena: true,
            hide_when_arena_not_in_front: true,
            api_url: "http://127.0.0.1:8765".into(),
            hotkeys_macos: Hotkeys::default(),
            hotkeys_windows: Hotkeys::default(),
            positions: Positions::default(),
            monitor: None,
        }
    }
}

impl Settings {
    /// The hotkeys for the platform this binary runs on.
    pub fn hotkeys(&self) -> &Hotkeys {
        if cfg!(target_os = "macos") {
            &self.hotkeys_macos
        } else {
            &self.hotkeys_windows
        }
    }

    pub fn clamped(mut self) -> Self {
        let defaults = Settings::default();
        if !(0.0..=1.0).contains(&self.opacity) || self.opacity.is_nan() {
            self.opacity = defaults.opacity;
        }
        if !(0.0..=1.0).contains(&self.rail_opacity) || self.rail_opacity.is_nan() {
            self.rail_opacity = defaults.rail_opacity;
        }
        self.return_after_seconds = self.return_after_seconds.clamp(1, 60);
        if self.scale == 0 {
            self.scale = 100;
        }
        self.scale = self.scale.clamp(50, 200);
        if self.panel_max_height == 0 {
            self.panel_max_height = defaults.panel_max_height;
        }
        self.panel_max_height = self.panel_max_height.clamp(200, 4000);
        if self.api_url.trim().is_empty() {
            self.api_url = Settings::default().api_url;
        }
        self
    }

    pub fn load(path: &PathBuf) -> Self {
        match std::fs::read(path) {
            Ok(bytes) => serde_json::from_slice::<Settings>(&bytes)
                .map(Settings::clamped)
                .unwrap_or_default(),
            Err(_) => Settings::default(),
        }
    }

    pub fn save(&self, path: &PathBuf) -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, serde_json::to_vec_pretty(self).unwrap_or_default())?;
        std::fs::rename(&tmp, path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_round_trip_and_clamp() {
        let json = serde_json::to_string(&Settings::default()).unwrap();
        let back: Settings = serde_json::from_str(&json).unwrap();
        assert_eq!(back, Settings::default());

        let weird: Settings = serde_json::from_str(r#"{"opacity": 7, "returnAfterSeconds": 0, "apiUrl": " "}"#).unwrap();
        let fixed = weird.clamped();
        assert_eq!(fixed.opacity, 0.8);
        assert_eq!(fixed.rail_opacity, 0.9);
        assert_eq!(fixed.panel_max_height, 800);
        assert_eq!(fixed.return_after_seconds, 1);
        assert_eq!(fixed.api_url, "http://127.0.0.1:8765");
        // Missing fields take defaults (a file from an older version keeps working).
        assert_eq!(fixed.dock, Dock::Left);
        assert_eq!(fixed.lands, Lands::Grouped);
    }

    #[test]
    fn old_percent_height_files_fall_back_to_the_pixel_default() {
        // A settings file written before the height became pixels carries
        // panelMaxHeightPct, which is simply unknown now.
        let old: Settings = serde_json::from_str(r#"{"panelMaxHeightPct": 70}"#).unwrap();
        assert_eq!(old.clamped().panel_max_height, 800);
        let tiny: Settings = serde_json::from_str(r#"{"panelMaxHeight": 10}"#).unwrap();
        assert_eq!(tiny.clamped().panel_max_height, 200);
    }

    #[test]
    fn hotkeys_are_stored_per_platform() {
        let mut s = Settings::default();
        s.hotkeys_windows.toggle = "Ctrl+Alt+T".into();
        let json = serde_json::to_string(&s).unwrap();
        assert!(json.contains("hotkeysWindows"));
        assert!(json.contains("hotkeysMacos"));
        let back: Settings = serde_json::from_str(&json).unwrap();
        assert_eq!(back.hotkeys_windows.toggle, "Ctrl+Alt+T");
        assert_eq!(back.hotkeys_macos.toggle, "Alt+Shift+T");
    }
}
