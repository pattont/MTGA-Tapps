//! The overlay lives only as long as the tracker that launched it.
//!
//! The tracker passes `--parent-pid <pid>`. A watchdog thread checks that
//! process every couple of seconds and quits the overlay once it is gone, so
//! a tracker that crashed, was ended from Task Manager, or was removed by an
//! uninstaller never leaves an orphaned overlay floating over Arena. A later
//! tracker that reuses this overlay (single-instance handoff) passes its own
//! pid the same way and the watchdog follows it instead. Runs without the
//! flag (development) are never watched.

use std::sync::Mutex;
use std::time::Duration;

use tauri::AppHandle;

use crate::diag;

const POLL: Duration = Duration::from_secs(2);

static WATCHED: Mutex<Option<u32>> = Mutex::new(None);

/// `--parent-pid <pid>` or `--parent-pid=<pid>`; the last one wins.
pub fn pid_from_args<S: AsRef<str>>(args: &[S]) -> Option<u32> {
    let mut found = None;
    let mut iter = args.iter().map(|a| a.as_ref());
    while let Some(arg) = iter.next() {
        let value = if arg == "--parent-pid" {
            iter.next()
        } else {
            arg.strip_prefix("--parent-pid=")
        };
        if let Some(pid) = value.and_then(|v| v.trim().parse::<u32>().ok()) {
            if pid != 0 {
                found = Some(pid);
            }
        }
    }
    found
}

/// Follow this process from now on (first launch or a later handoff).
pub fn watch(pid: u32) {
    let mut watched = WATCHED.lock().unwrap();
    if *watched != Some(pid) {
        diag::log(format!("watching tracker pid {pid}"));
        *watched = Some(pid);
    }
}

pub fn start(app: AppHandle) {
    std::thread::Builder::new()
        .name("parent-watch".into())
        .spawn(move || loop {
            std::thread::sleep(POLL);
            let pid = *WATCHED.lock().unwrap();
            if let Some(pid) = pid {
                if !alive(pid) {
                    diag::log(format!("tracker pid {pid} is gone; quitting"));
                    app.exit(0);
                    return;
                }
            }
        })
        .expect("parent watch thread");
}

#[cfg(unix)]
fn alive(pid: u32) -> bool {
    extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
    }
    const ESRCH: i32 = 3; // the same on macOS and Linux
    let Ok(pid) = i32::try_from(pid) else { return true };
    // Signal 0 only checks that the process exists. EPERM means it exists
    // but belongs to someone else: still alive.
    if unsafe { kill(pid, 0) } == 0 {
        return true;
    }
    std::io::Error::last_os_error().raw_os_error() != Some(ESRCH)
}

#[cfg(windows)]
fn alive(pid: u32) -> bool {
    use windows::Win32::Foundation::{CloseHandle, ERROR_INVALID_PARAMETER, WAIT_TIMEOUT};
    use windows::Win32::System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE};

    match unsafe { OpenProcess(PROCESS_SYNCHRONIZE, false, pid) } {
        Ok(handle) => {
            // An exited process stays openable while anyone holds a handle
            // to it; it is alive only while the wait times out.
            let running = unsafe { WaitForSingleObject(handle, 0) } == WAIT_TIMEOUT;
            let _ = unsafe { CloseHandle(handle) };
            running
        }
        // No such process. Anything else (access denied) means it exists.
        Err(err) => err.code() != ERROR_INVALID_PARAMETER.to_hresult(),
    }
}

#[cfg(not(any(unix, windows)))]
fn alive(_pid: u32) -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_both_spellings_and_ignores_junk() {
        assert_eq!(pid_from_args(&["--parent-pid", "42"]), Some(42));
        assert_eq!(pid_from_args(&["x", "--parent-pid=7"]), Some(7));
        assert_eq!(pid_from_args(&["--parent-pid", "nope"]), None);
        assert_eq!(pid_from_args(&["--parent-pid", "0"]), None);
        assert_eq!(pid_from_args(&["--parent-pid"]), None);
        assert_eq!(pid_from_args(&["--parent-pid", "1", "--parent-pid", "2"]), Some(2));
        assert_eq!(pid_from_args::<&str>(&[]), None);
    }

    #[test]
    fn this_process_is_alive() {
        assert!(alive(std::process::id()));
    }

    #[cfg(unix)]
    #[test]
    fn an_exited_child_is_not() {
        let mut child = std::process::Command::new("true").spawn().unwrap();
        let pid = child.id();
        child.wait().unwrap();
        assert!(!alive(pid));
    }
}
