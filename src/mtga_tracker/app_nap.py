"""Keep macOS from putting the tracker into App Nap.

The tracker is a menu-bar app with no window, which is exactly what macOS
naps: every thread of the process drops to the background band and runs on the
efficiency cores. Measured on an M4 Max on 2026-11-10, the same Overview took
95 ms in a terminal process and 500 ms inside the napped app, and every other
dashboard page slowed by the same factor. The log reader and the overlay's
data are served by those same throttled threads.

``stay_awake`` tells macOS the process is doing work the user asked for
(``NSProcessInfo.beginActivityWithOptions:reason:``), the documented way out
of App Nap. The activity allows idle system sleep: it never keeps the Mac
awake. It is held for the life of the process.

Foundation is reached through ctypes so the app needs no Objective-C bridge.
Anything that goes wrong leaves the app napped, as it was before.
"""

from __future__ import annotations

import sys
from typing import Any, Optional

#: NSActivityUserInitiated without NSActivityIdleSystemSleepDisabled (1 << 20):
#: no App Nap, no sudden or automatic termination, the Mac may still sleep.
ACTIVITY_OPTIONS = 0x00FFFFFF & ~(1 << 20)
REASON = "Tracking Arena games and serving the dashboard"

#: The activity token, kept so the activity never ends.
_activity: Optional[int] = None


def _load(ctypes: Any, name: str, path: str) -> Any:
    from ctypes import util

    return ctypes.CDLL(util.find_library(name) or path)


def stay_awake(reason: str = REASON) -> bool:
    """Opt this process out of App Nap. True when macOS accepted the activity
    (now or on an earlier call); False on other systems and on any failure."""
    global _activity
    if sys.platform != "darwin":
        return False
    if _activity is not None:
        return True
    try:
        import ctypes

        objc = _load(ctypes, "objc", "/usr/lib/libobjc.A.dylib")
        _load(ctypes, "Foundation", "/System/Library/Frameworks/Foundation.framework/Foundation")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        # objc_msgSend has no prototype of its own: each call casts it to the
        # signature of the method it sends.
        send = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        pointer = ctypes.c_void_p
        plain = ctypes.CFUNCTYPE(pointer, pointer, pointer)(send)
        with_text = ctypes.CFUNCTYPE(pointer, pointer, pointer, ctypes.c_char_p)(send)
        with_options = ctypes.CFUNCTYPE(pointer, pointer, pointer, ctypes.c_uint64, pointer)(send)

        process_info = plain(
            objc.objc_getClass(b"NSProcessInfo"), objc.sel_registerName(b"processInfo")
        )
        text = with_text(
            objc.objc_getClass(b"NSString"),
            objc.sel_registerName(b"stringWithUTF8String:"),
            reason.encode("utf-8"),
        )
        if not process_info or not text:
            return False
        token = with_options(
            process_info,
            objc.sel_registerName(b"beginActivityWithOptions:reason:"),
            ACTIVITY_OPTIONS,
            text,
        )
        if not token:
            return False
        # The token comes back autoreleased; keep it for good.
        plain(token, objc.sel_registerName(b"retain"))
        _activity = int(token)
        return True
    except Exception:
        return False
