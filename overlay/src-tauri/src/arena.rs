//! Where is Arena? One cheap OS query a second (two when it is closed), no
//! hooks, no injection, and never a spawned process.
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
    use objc2::rc::autoreleasepool;
    use objc2_app_kit::{NSRunningApplication, NSWorkspace};
    use objc2_foundation::NSString;
    use std::ffi::{c_char, c_void, CString};
    use std::sync::Mutex;

    const BUNDLE_ID: &str = "com.wizards.mtga";

    /// The foreground application's bundle id: NSWorkspace is the native,
    /// permission-free source (`lsappinfo front` returned `[ NULL ]`
    /// intermittently on macOS 27, including for an active Arena window).
    fn frontmost_bundle_id() -> Option<String> {
        // `lsappinfo front` returns `[ NULL ]` intermittently on macOS 27,
        // including for an active Arena window. NSWorkspace is the native,
        // permission-free source for the foreground application.
        let workspace = NSWorkspace::sharedWorkspace();
        let application = workspace.frontmostApplication()?;
        application.bundleIdentifier().map(|id| id.to_string())
    }

    /// Arena's process id, as last seen. Checked first through LaunchServices
    /// (one API call, no spawn) while Arena stays up.
    static ARENA_PID: Mutex<Option<i32>> = Mutex::new(None);

    /// Is `pid` still Arena? Pids are reused, so the remembered one must
    /// resolve to a running application with Arena's bundle id, not merely
    /// to a live process.
    fn pid_is_arena(pid: i32) -> bool {
        NSRunningApplication::runningApplicationWithProcessIdentifier(pid)
            .filter(|app| !app.isTerminated())
            .and_then(|app| app.bundleIdentifier())
            .map(|id| id.to_string() == BUNDLE_ID)
            .unwrap_or(false)
    }

    /// Arena's process id, when it is running: the remembered pid while it
    /// is still alive, otherwise LaunchServices' list of running
    /// applications with Arena's bundle id (covers a renamed executable).
    /// Earlier builds spawned `pgrep` and `lsappinfo` for this every second,
    /// the overlay's largest idle cost.
    fn arena_pid() -> Option<i32> {
        let remembered = ARENA_PID.lock().ok().and_then(|pid| *pid);
        if let Some(pid) = remembered {
            if pid_is_arena(pid) {
                return Some(pid);
            }
        }
        let bundle_id = NSString::from_str(BUNDLE_ID);
        let apps = NSRunningApplication::runningApplicationsWithBundleIdentifier(&bundle_id);
        let pid = apps
            .iter()
            .find(|app| !app.isTerminated())
            .map(|app| app.processIdentifier() as i32)
            .filter(|pid| *pid > 0);
        if let Ok(mut slot) = ARENA_PID.lock() {
            if *slot != pid {
                crate::diag::log(format!("arena: pid is now {pid:?}"));
                *slot = pid;
            }
        }
        pid
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
        // This thread never returns to a run loop, so AppKit's autoreleased
        // objects need a pool of their own or they pile up for ever.
        autoreleasepool(|_| {
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
        })
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

    /// Arena's process id, as last seen: checked with one handle open before
    /// the Toolhelp walk over every process runs.
    static ARENA_PID: std::sync::Mutex<Option<u32>> = std::sync::Mutex::new(None);

    fn remember_pid(pid: Option<u32>) {
        if let Ok(mut slot) = ARENA_PID.lock() {
            *slot = pid;
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
            remember_pid(Some(pid));
            let mut rect = RECT::default();
            let bounds = GetWindowRect(hwnd, &mut rect)
                .ok()
                .map(|_| (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top));
            (true, bounds, false)
        }
    }

    fn running() -> bool {
        let remembered = ARENA_PID.lock().ok().and_then(|pid| *pid);
        if let Some(pid) = remembered {
            if crate::parent::alive(pid)
                && image_name_of(pid).map(|p| is_arena_path(&p)).unwrap_or(false)
            {
                return true;
            }
            remember_pid(None);
        }
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
                        remember_pid(Some(entry.th32ProcessID));
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
