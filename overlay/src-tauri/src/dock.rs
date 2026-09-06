//! Dock geometry — pure functions over logical-pixel rectangles.
//!
//! The rail lives *in* a screen edge; the panel takes its place flush to the
//! same edge. Docked windows slide freely up and down the edge and are
//! clamped so they never leave the monitor's work area. Everything here is
//! in logical pixels (Tauri's `LogicalPosition`/`LogicalSize`), so a 4K
//! display at 150% and a 1080p display at 100% produce the same physical
//! rail.

use crate::settings::Dock;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

impl Rect {
    pub fn contains(&self, x: i32, y: i32) -> bool {
        x >= self.x && x < self.x + self.width && y >= self.y && y < self.y + self.height
    }

    fn overlap_area(&self, other: &Rect) -> i64 {
        let w = (self.x + self.width).min(other.x + other.width) - self.x.max(other.x);
        let h = (self.y + self.height).min(other.y + other.height) - self.y.max(other.y);
        if w <= 0 || h <= 0 {
            0
        } else {
            w as i64 * h as i64
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Size {
    pub width: i32,
    pub height: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Layout {
    Rail,
    Panel,
}

/// Fixed rail footprint and the panel's width; the panel's height follows its
/// content and is capped to the work area by `fit_height`.
pub const RAIL_WIDTH: i32 = 44;
pub const RAIL_HEIGHT: i32 = 210;
/// 297 px of content plus 4 px of plain ground on the screen-edge side, so
/// the text never sits hard against the bezel (the page adds that padding).
pub const PANEL_WIDTH: i32 = 301;
/// Transparent strip beside the panel, on the board side, where the hover
/// card and the sideboard fly out to. Part of the window; clicks on the
/// fully transparent pixels fall through on macOS.
pub const PANEL_GUTTER: i32 = 196;
pub const PANEL_MIN_HEIGHT: i32 = 160;

/// Vertical gap kept from the work area's top and bottom when clamping.
const EDGE_MARGIN: i32 = 8;

/// `content_height` is the page's base (unscaled) measurement; `scale_pct`
/// grows the window with the page's transform.
pub fn size_for(layout: Layout, content_height: i32, work_area: &Rect, max_height_pct: u32, scale_pct: u32) -> Size {
    let scaled = |v: i32| (v as i64 * scale_pct.clamp(50, 200) as i64 / 100) as i32;
    match layout {
        Layout::Rail => Size { width: scaled(RAIL_WIDTH), height: scaled(RAIL_HEIGHT) },
        Layout::Panel => Size {
            width: scaled(PANEL_WIDTH + PANEL_GUTTER),
            height: fit_height(scaled(content_height), work_area, max_height_pct),
        },
    }
}

/// The panel's height: its content, between the minimum and the smaller of
/// the work area and `max_height_pct` percent of the screen — a long list
/// scrolls inside rather than running the length of the monitor.
pub fn fit_height(content_height: i32, work_area: &Rect, max_height_pct: u32) -> i32 {
    let pct = max_height_pct.clamp(30, 100) as i64;
    let by_pct = (work_area.height as i64 * pct / 100) as i32;
    let max = by_pct.min(work_area.height - 2 * EDGE_MARGIN).max(PANEL_MIN_HEIGHT);
    content_height.clamp(PANEL_MIN_HEIGHT, max)
}

/// Top-left corner for a window of `size` docked to `dock` on `work_area`.
/// `y` is the remembered vertical offset (top edge, absolute), or None to
/// centre vertically. Float returns `float_at` clamped on screen, or the
/// centre of the work area when nothing was remembered.
pub fn docked_position(
    dock: Dock,
    size: Size,
    work_area: &Rect,
    y: Option<i32>,
    float_at: Option<(i32, i32)>,
) -> (i32, i32) {
    let centred_y = work_area.y + (work_area.height - size.height) / 2;
    let clamp_y = |value: i32| {
        let lo = work_area.y + EDGE_MARGIN;
        let hi = (work_area.y + work_area.height - size.height - EDGE_MARGIN).max(lo);
        value.clamp(lo, hi)
    };
    match dock {
        Dock::Left => (work_area.x, clamp_y(y.unwrap_or(centred_y))),
        Dock::Right => (
            work_area.x + work_area.width - size.width,
            clamp_y(y.unwrap_or(centred_y)),
        ),
        Dock::Float => {
            let (fx, fy) = float_at.unwrap_or((
                work_area.x + (work_area.width - size.width) / 2,
                centred_y,
            ));
            let lo_x = work_area.x;
            let hi_x = (work_area.x + work_area.width - size.width).max(lo_x);
            (fx.clamp(lo_x, hi_x), clamp_y(fy))
        }
    }
}

/// Pick the monitor to dock on: the one containing the point (cursor at
/// game start, or Arena's window centre), else the one overlapping `hint`
/// the most, else the first. Returns an index into `monitors`.
/// The monitor that holds (at least 90 % of) `window`, by overlap. None
/// while the window straddles monitors — a fullscreen Space sliding across
/// during a swipe must not drag the overlay to another screen.
pub fn monitor_holding(monitors: &[Rect], window: &Rect) -> Option<usize> {
    let area = window.width as i64 * window.height as i64;
    if area <= 0 {
        return None;
    }
    let mut best: Option<(usize, i64)> = None;
    for (index, monitor) in monitors.iter().enumerate() {
        let left = window.x.max(monitor.x);
        let top = window.y.max(monitor.y);
        let right = (window.x + window.width).min(monitor.x + monitor.width);
        let bottom = (window.y + window.height).min(monitor.y + monitor.height);
        let overlap = (right - left).max(0) as i64 * (bottom - top).max(0) as i64;
        if overlap > best.map(|(_, o)| o).unwrap_or(0) {
            best = Some((index, overlap));
        }
    }
    let (index, overlap) = best?;
    (overlap * 10 >= area * 9).then_some(index)
}

pub fn choose_monitor(monitors: &[Rect], point: Option<(i32, i32)>, hint: Option<&Rect>) -> Option<usize> {
    if monitors.is_empty() {
        return None;
    }
    if let Some((x, y)) = point {
        if let Some(index) = monitors.iter().position(|m| m.contains(x, y)) {
            return Some(index);
        }
    }
    if let Some(rect) = hint {
        let (index, area) = monitors
            .iter()
            .enumerate()
            .map(|(i, m)| (i, m.overlap_area(rect)))
            .max_by_key(|(_, area)| *area)
            .unwrap_or((0, 0));
        if area > 0 {
            return Some(index);
        }
    }
    Some(0)
}

/// Where a drag should leave a docked window: only the y axis moves.
pub fn constrain_drag(dock: Dock, proposed: (i32, i32), size: Size, work_area: &Rect) -> (i32, i32) {
    match dock {
        Dock::Float => docked_position(Dock::Float, size, work_area, None, Some(proposed)),
        side => docked_position(side, size, work_area, Some(proposed.1), None),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const WORK: Rect = Rect { x: 0, y: 25, width: 1920, height: 1055 };

    #[test]
    fn rail_and_panel_sizes() {
        assert_eq!(size_for(Layout::Rail, 9999, &WORK, 100, 100), Size { width: 44, height: RAIL_HEIGHT });
        assert_eq!(size_for(Layout::Rail, 9999, &WORK, 100, 150), Size { width: 66, height: RAIL_HEIGHT * 3 / 2 });
        assert_eq!(size_for(Layout::Panel, 400, &WORK, 100, 150), Size { width: (301 + 196) * 3 / 2, height: 600 });
        assert_eq!(size_for(Layout::Panel, 620, &WORK, 100, 100), Size { width: 301 + 196, height: 620 });
        // Taller than the screen -> capped with the edge margin.
        assert_eq!(size_for(Layout::Panel, 3000, &WORK, 100, 100).height, 1055 - 16);
        // The max-height setting caps a long list to a share of the screen.
        assert_eq!(size_for(Layout::Panel, 3000, &WORK, 70, 100).height, 1055 * 70 / 100);
        assert_eq!(size_for(Layout::Panel, 500, &WORK, 70, 100).height, 500);
        // Never below the minimum.
        assert_eq!(size_for(Layout::Panel, 10, &WORK, 70, 100).height, PANEL_MIN_HEIGHT);
    }

    #[test]
    fn docked_right_is_flush_and_clamped() {
        let size = Size { width: 44, height: 300 };
        assert_eq!(docked_position(Dock::Right, size, &WORK, None, None), (1876, 25 + (1055 - 300) / 2));
        assert_eq!(docked_position(Dock::Right, size, &WORK, Some(-500), None), (1876, 33));
        assert_eq!(docked_position(Dock::Right, size, &WORK, Some(5000), None), (1876, 25 + 1055 - 300 - 8));
        assert_eq!(docked_position(Dock::Left, size, &WORK, Some(200), None), (0, 200));
    }

    #[test]
    fn float_remembers_and_clamps() {
        let size = Size { width: 301, height: 620 };
        assert_eq!(docked_position(Dock::Float, size, &WORK, None, Some((100, 100))), (100, 100));
        assert_eq!(docked_position(Dock::Float, size, &WORK, None, Some((-50, -50))), (0, 33));
        assert_eq!(docked_position(Dock::Float, size, &WORK, None, Some((5000, 5000))), (1920 - 301, 25 + 1055 - 620 - 8));
    }

    #[test]
    fn drag_on_a_docked_window_only_moves_vertically() {
        let size = Size { width: 44, height: 300 };
        assert_eq!(constrain_drag(Dock::Right, (400, 300), size, &WORK), (1876, 300));
        assert_eq!(constrain_drag(Dock::Left, (400, 300), size, &WORK), (0, 300));
        assert_eq!(constrain_drag(Dock::Float, (400, 300), size, &WORK), (400, 300));
    }

    #[test]
    fn monitor_holding_needs_the_window_inside_one_screen() {
        let monitors = [
            Rect { x: 0, y: 0, width: 3200, height: 1800 },
            Rect { x: 3200, y: 153, width: 2056, height: 1329 },
            Rect { x: -1800, y: -989, width: 1800, height: 3200 },
        ];
        let arena = Rect { x: 0, y: 0, width: 3200, height: 1800 };
        assert_eq!(monitor_holding(&monitors, &arena), Some(0));
        // Mid-swipe: the fullscreen window is sliding between screens.
        assert_eq!(monitor_holding(&monitors, &Rect { x: 1341, y: 0, width: 3200, height: 1800 }), None);
        assert_eq!(monitor_holding(&monitors, &Rect { x: -3237, y: 0, width: 3200, height: 1800 }), None);
        // A small windowed Arena on the second screen.
        assert_eq!(monitor_holding(&monitors, &Rect { x: 3400, y: 300, width: 1600, height: 900 }), Some(1));
        assert_eq!(monitor_holding(&monitors, &Rect { x: 0, y: 0, width: 0, height: 0 }), None);
    }

    #[test]
    fn monitor_choice() {
        let a = Rect { x: 0, y: 0, width: 1920, height: 1080 };
        let b = Rect { x: 1920, y: 0, width: 2560, height: 1440 };
        assert_eq!(choose_monitor(&[a, b], Some((2000, 10)), None), Some(1));
        assert_eq!(choose_monitor(&[a, b], Some((10, 10)), None), Some(0));
        let arena = Rect { x: 1800, y: 0, width: 2000, height: 1000 }; // mostly on b
        assert_eq!(choose_monitor(&[a, b], None, Some(&arena)), Some(1));
        assert_eq!(choose_monitor(&[a, b], Some((-5, -5)), None), Some(0));
        assert_eq!(choose_monitor(&[], None, None), None);
    }
}
