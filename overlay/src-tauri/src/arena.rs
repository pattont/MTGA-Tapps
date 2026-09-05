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
    /// Arena's window rectangle (x, y, width, height) when known: logical
    /// points on macOS (what CGWindowList reports), physical pixels on
    /// Windows (what GetWindowRect reports). `lib.rs` compares each against
    /// monitors in the same units.
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
    use std::ffi::{c_char, c_void, CString};
    use std::process::Command;

    const BUNDLE_ID: &str = "com.wizards.mtga";

    /// `lsappinfo` ships with macOS, needs no Automation/Accessibility
    /// permission (unlike System Events or CGWindowList names), and answers
    /// in a few milliseconds — the right trade for a once-a-second poll.
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

    /// Arena's process id, when it is running.
    fn arena_pid() -> Option<i32> {
        let out = Command::new("/usr/bin/pgrep").args(["-x", "MTGA"]).output().ok()?;
        if !out.status.success() {
            return None;
        }
        String::from_utf8_lossy(&out.stdout).lines().next()?.trim().parse().ok()
    }

    // --- CGWindowList: the bounds of Arena's window without any permission
    // prompt (window *names* need Screen Recording; owner pid, layer and
    // bounds do not). Declared by hand so the crate needs no framework
    // bindings for four C calls.

    #[repr(C)]
    #[derive(Clone, Copy, Default)]
    struct CGRect {
        x: f64,
        y: f64,
        width: f64,
        height: f64,
    }

    const K_CG_WINDOW_LIST_OPTION_ON_SCREEN_ONLY: u32 = 1 << 0;
    const K_CG_WINDOW_LIST_EXCLUDE_DESKTOP_ELEMENTS: u32 = 1 << 4;
    const K_CG_NULL_WINDOW_ID: u32 = 0;
    const K_CF_NUMBER_SINT32_TYPE: isize = 3;
    const K_CF_STRING_ENCODING_UTF8: u32 = 0x0800_0100;

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGWindowListCopyWindowInfo(option: u32, relative_to_window: u32) -> *const c_void;
        fn CGRectMakeWithDictionaryRepresentation(dict: *const c_void, rect: *mut CGRect) -> bool;
    }

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        fn CFArrayGetCount(array: *const c_void) -> isize;
        fn CFArrayGetValueAtIndex(array: *const c_void, index: isize) -> *const c_void;
        fn CFDictionaryGetValue(dict: *const c_void, key: *const c_void) -> *const c_void;
        fn CFStringCreateWithCString(alloc: *const c_void, cstr: *const c_char, encoding: u32) -> *const c_void;
        fn CFNumberGetValue(number: *const c_void, number_type: isize, out: *mut c_void) -> bool;
        fn CFRelease(cf: *const c_void);
    }

    struct CfKey(*const c_void);

    impl CfKey {
        fn new(name: &str) -> Self {
            let c = CString::new(name).expect("static key");
            CfKey(unsafe { CFStringCreateWithCString(std::ptr::null(), c.as_ptr(), K_CF_STRING_ENCODING_UTF8) })
        }
    }

    impl Drop for CfKey {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe { CFRelease(self.0) };
            }
        }
    }

    fn number_i32(value: *const c_void) -> Option<i32> {
        if value.is_null() {
            return None;
        }
        let mut out: i32 = 0;
        let ok = unsafe { CFNumberGetValue(value, K_CF_NUMBER_SINT32_TYPE, &mut out as *mut i32 as *mut c_void) };
        ok.then_some(out)
    }

    /// The largest on-screen, layer-0 window owned by `pid`, in points with
    /// a top-left origin — the same frame Tauri reports monitors in.
    fn window_bounds(pid: i32) -> Option<(i32, i32, i32, i32)> {
        let list = unsafe {
            CGWindowListCopyWindowInfo(
                K_CG_WINDOW_LIST_OPTION_ON_SCREEN_ONLY | K_CG_WINDOW_LIST_EXCLUDE_DESKTOP_ELEMENTS,
                K_CG_NULL_WINDOW_ID,
            )
        };
        if list.is_null() {
            return None;
        }
        let owner_key = CfKey::new("kCGWindowOwnerPID");
        let layer_key = CfKey::new("kCGWindowLayer");
        let bounds_key = CfKey::new("kCGWindowBounds");
        let mut best: Option<(i32, i32, i32, i32)> = None;
        let count = unsafe { CFArrayGetCount(list) };
        for index in 0..count {
            let dict = unsafe { CFArrayGetValueAtIndex(list, index) };
            if dict.is_null() {
                continue;
            }
            let owner = number_i32(unsafe { CFDictionaryGetValue(dict, owner_key.0) });
            if owner != Some(pid) {
                continue;
            }
            if number_i32(unsafe { CFDictionaryGetValue(dict, layer_key.0) }) != Some(0) {
                continue;
            }
            let bounds = unsafe { CFDictionaryGetValue(dict, bounds_key.0) };
            if bounds.is_null() {
                continue;
            }
            let mut rect = CGRect::default();
            if !unsafe { CGRectMakeWithDictionaryRepresentation(bounds, &mut rect) } {
                continue;
            }
            let candidate = (rect.x as i32, rect.y as i32, rect.width as i32, rect.height as i32);
            let area = candidate.2 as i64 * candidate.3 as i64;
            let best_area = best.map(|b| b.2 as i64 * b.3 as i64).unwrap_or(-1);
            if area > best_area {
                best = Some(candidate);
            }
        }
        unsafe { CFRelease(list) };
        best
    }

    static LAST_FRONT: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);

    pub fn probe() -> ArenaStatus {
        let front = frontmost_bundle_id();
        if let Ok(mut last) = LAST_FRONT.lock() {
            if *last != front {
                crate::diag::log(format!("arena: front app is now {front:?}"));
                *last = front.clone();
            }
        }
        let frontmost = front.as_deref() == Some(BUNDLE_ID);
        let pid = arena_pid();
        ArenaStatus {
            running: frontmost || pid.is_some(),
            frontmost,
            bounds: pid.and_then(window_bounds),
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
