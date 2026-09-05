//! A small append-only log for "why isn't it showing?" questions.
//!
//! Every notable step (placement, show/hide and why, the Arena probe
//! flipping, hotkey and tray setup, page errors) writes one timestamped line.
//! The tracker passes `--log <path>` so the file lands in its own data folder;
//! standalone runs log next to overlay.json. Truncated on every launch.

use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

static SINK: Mutex<Option<File>> = Mutex::new(None);

pub fn open(path: &Path) -> bool {
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    match File::create(path) {
        Ok(file) => {
            *SINK.lock().unwrap() = Some(file);
            log(format!("log opened at {}", path.display()));
            true
        }
        Err(err) => {
            eprintln!("overlay: could not open log {}: {err}", path.display());
            false
        }
    }
}

pub fn path_from_args() -> Option<PathBuf> {
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == "--log" {
            return args.next().map(PathBuf::from);
        }
        if let Some(rest) = arg.strip_prefix("--log=") {
            return Some(PathBuf::from(rest));
        }
    }
    None
}

pub fn log(message: impl AsRef<str>) {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let secs = millis / 1000;
    let line = format!("{:>10}.{:03} {}\n", secs, millis % 1000, message.as_ref());
    eprint!("{line}");
    if let Ok(mut guard) = SINK.lock() {
        if let Some(file) = guard.as_mut() {
            let _ = file.write_all(line.as_bytes());
            let _ = file.flush();
        }
    }
}
