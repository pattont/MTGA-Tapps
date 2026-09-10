"""Where to open the tray icon's menu (no Qt here, so it can be tested cold).

The cursor is at the bottom edge of the screen when someone right-clicks a
Windows tray icon, and a menu opened downward from there runs under the
taskbar — its last item, Quit, becomes unreachable. Open it upward (and
leftward, at the right edge) whenever it would not fit.
"""

from __future__ import annotations

from typing import Tuple

Rect = Tuple[int, int, int, int]  # left, top, right, bottom (inclusive edges)


def tray_menu_origin(cursor: Tuple[int, int], menu_size: Tuple[int, int], available: Rect) -> Tuple[int, int]:
    """Top-left corner for a menu of ``menu_size`` opened at ``cursor`` so that
    the whole menu stays inside ``available`` (the screen minus the taskbar).

    Below/right of the cursor when it fits, otherwise flipped above/left of
    it; a menu taller than the space is pinned to the top edge so at least
    its first items and the scroll arrows show.
    """
    cx, cy = cursor
    width, height = menu_size
    left, top, right, bottom = available
    x = cx if cx + width <= right else cx - width
    y = cy if cy + height <= bottom else cy - height
    x = max(left, min(x, right - width))
    y = max(top, min(y, bottom - height))
    return int(x), int(y)
