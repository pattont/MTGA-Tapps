//! Where is Arena? One cheap OS query per second, no hooks, no injection.
//!
//! Answers two things the window manager needs: is Arena the frontmost
//! application (so the overlay can get out of the way when the player
//! alt-tabs), and — on Windows, where the API hands it over for free — the
//! bounds of its window (so the overlay docks to the same monitor).
//! Whether a *game* is happening is not decided here; that comes from the
//! tracker's log-derived state.

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ArenaStatus {
    /// Arena's process exists.
    pub running: bool,
    /// Arena's window has keyboard focus.
    pub frontmost: bool,
    /// Arena's window rectangle in physical screen pixels, when known.
    pub bounds: Option<(i32, i32, i32, i32)>,
    /// The overlay itself has focus (the player is using the flyout) — never
    /// a reason to hide.
    pub overlay_frontmost: bool,
}

/// The overlay's own bundle identifier (macOS) — must match tauri.conf.json.
#[allow(dead_code)]
pub const OVERLAY_BUNDLE_ID: &str = "com.tappstracker.overlay";

pub fn probe() -> ArenaStatus {
    platform::probe()
}

#[cfg(target_os = "macos")]
mod platform {
    use super::ArenaStatus;
    use std::process::Command;

    const BUNDLE_ID: &str = "com.wizards.mtga";

    /// `lsappinfo` ships with macOS, needs no Automation/Accessibility
    /// permission (unlike System Events or CGWindowList), and answers in a
    /// few milliseconds — the right trade for a once-a-second poll.
    fn frontmost_bundle_id() -> Option<String> {
        let front = Command::new("/usr/bin/lsappinfo").arg("front").output().ok()?;
        let asn = String::from_utf8_lossy(&front.stdout).trim().to_string();
        if asn.is_empty() {
            return None;
        }
        let info = Command::new("/usr/bin/lsappinfo")
            .args(["info", "-only", "bundleid", &asn])
            .output()
            .ok()?;
        let text = String::from_utf8_lossy(&info.stdout);
        // "CFBundleIdentifier"="com.wizards.mtga"
        let value = text.split('=').nth(1)?.trim().trim_matches('"').to_string();
        if value.is_empty() {
            None
        } else {
            Some(value)
        }
    }

    fn running() -> bool {
        Command::new("/usr/bin/pgrep")
            .args(["-x", "MTGA"])
            .output()
            .map(|out| out.status.success())
            .unwrap_or(false)
    }

    pub fn probe() -> ArenaStatus {
        let front = frontmost_bundle_id();
        let frontmost = front.as_deref() == Some(BUNDLE_ID);
        ArenaStatus {
            running: frontmost || running(),
            frontmost,
            bounds: None,
            overlay_frontmost: front.as_deref() == Some(super::OVERLAY_BUNDLE_ID),
        }
    }
}

#[cfg(target_os = "windows")]
mod platform {
    use super::ArenaStatus;
    use windows::Win32::Foundation::{CloseHandle, HWND, RECT};
    use windows::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
        TH32CS_SNAPPROCESS,
    };
    use windows::Win32::System::Threading::{
        OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
        PROCESS_QUERY_LIMITED_INFORMATION,
    };
    use windows::Win32::UI::WindowsAndMessaging::{
        GetForegroundWindow, GetWindowRect, GetWindowThreadProcessId,
    };
    use windows::core::PWSTR;

    const EXE_NAME: &str = "mtga.exe";

    fn image_name_of(pid: u32) -> Option<String> {
        unsafe {
            let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
            let mut buffer = [0u16; 1024];
            let mut length = buffer.len() as u32;
            let result = QueryFullProcessImageNameW(
                handle,
                PROCESS_NAME_WIN32,
                PWSTR(buffer.as_mut_ptr()),
                &mut length,
            );
            let _ = CloseHandle(handle);
            result.ok()?;
            Some(String::from_utf16_lossy(&buffer[..length as usize]))
        }
    }

    fn is_arena_path(path: &str) -> bool {
        path.rsplit(['\\', '/'])
            .next()
            .map(|name| name.eq_ignore_ascii_case(EXE_NAME))
            .unwrap_or(false)
    }

    /// (arena is foreground, arena bounds, overlay is foreground)
    fn foreground() -> (bool, Option<(i32, i32, i32, i32)>, bool) {
        unsafe {
            let hwnd: HWND = GetForegroundWindow();
            if hwnd.0.is_null() {
                return (false, None, false);
            }
            let mut pid = 0u32;
            GetWindowThreadProcessId(hwnd, Some(&mut pid));
            if pid == 0 {
                return (false, None, false);
            }
            if pid == std::process::id() {
                return (false, None, true);
            }
            let is_arena = image_name_of(pid).map(|p| is_arena_path(&p)).unwrap_or(false);
            if !is_arena {
                return (false, None, false);
            }
            let mut rect = RECT::default();
            let bounds = GetWindowRect(hwnd, &mut rect)
                .ok()
                .map(|_| (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top));
            (true, bounds, false)
        }
    }

    fn running() -> bool {
        unsafe {
            let Ok(snapshot) = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) else {
                return false;
            };
            let mut entry = PROCESSENTRY32W {
                dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
                ..Default::default()
            };
            let mut found = false;
            if Process32FirstW(snapshot, &mut entry).is_ok() {
                loop {
                    let end = entry.szExeFile.iter().position(|&c| c == 0).unwrap_or(entry.szExeFile.len());
                    let name = String::from_utf16_lossy(&entry.szExeFile[..end]);
                    if name.eq_ignore_ascii_case(EXE_NAME) {
                        found = true;
                        break;
                    }
                    if Process32NextW(snapshot, &mut entry).is_err() {
                        break;
                    }
                }
            }
            let _ = CloseHandle(snapshot);
            found
        }
    }

    pub fn probe() -> ArenaStatus {
        let (frontmost, bounds, overlay_frontmost) = foreground();
        ArenaStatus {
            running: frontmost || running(),
            frontmost,
            bounds,
            overlay_frontmost,
        }
    }
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
mod platform {
    use super::ArenaStatus;

    /// Development builds on Linux: Arena does not run here, so the overlay
    /// behaves as if "hide when Arena isn't in front" were off.
    pub fn probe() -> ArenaStatus {
        ArenaStatus::default()
    }
}
