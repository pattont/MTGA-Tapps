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
    /// Paint the tinted ground behind the rail and panel (a fixed charcoal
    /// wash, hairlines between rows); off leaves text with a shadow over
    /// the board.
    pub background: bool,
    /// Opacity of the whole overlay, 0.2–1.0: the slider fades everything —
    /// tint, text, controls — not just the ground.
    pub opacity: f64,
    /// The panel never grows past this share of the screen's height (30–100);
    /// the list scrolls inside it instead.
    pub panel_max_height_pct: u32,
    pub dock: Dock,
    pub return_after_seconds: u32,
    pub open_pinned: bool,
    pub click_through_when_pinned: bool,
    pub lands: Lands,
    pub density: Density,
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
            background: true,
            opacity: 1.0,
            panel_max_height_pct: 70,
            dock: Dock::Right,
            return_after_seconds: 4,
            open_pinned: true,
            // Off by default: with it on, the panel can only be driven by the
            // hotkeys and the tray (every click reaches Arena instead).
            click_through_when_pinned: false,
            lands: Lands::Grouped,
            density: Density::Comfortable,
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
        if !(0.2..=1.0).contains(&self.opacity) || self.opacity.is_nan() {
            self.opacity = 1.0;
        }
        self.return_after_seconds = self.return_after_seconds.clamp(1, 60);
        if self.panel_max_height_pct == 0 {
            self.panel_max_height_pct = 70;
        }
        self.panel_max_height_pct = self.panel_max_height_pct.clamp(30, 100);
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
        assert_eq!(fixed.opacity, 1.0);
        assert_eq!(fixed.return_after_seconds, 1);
        assert_eq!(fixed.api_url, "http://127.0.0.1:8765");
        // Missing fields take defaults (a file from an older version keeps working).
        assert_eq!(fixed.dock, Dock::Right);
        assert_eq!(fixed.lands, Lands::Grouped);
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
