from pathlib import Path

from mtga_tracker.rendering import ANSI_STYLES, apply_style, display_path_without_username


def test_apply_style_respects_color_flag():
    assert apply_style("Draw", "draw", use_colors=False) == "Draw"
    assert apply_style("Draw", "draw", use_colors=True) == f"{ANSI_STYLES['draw']}Draw\033[0m"


def test_display_path_without_username_redacts_home():
    import os

    from mtga_tracker.rendering import HOME_PLACEHOLDER

    home_path = Path.home() / "Library" / "Logs" / "Wizards Of The Coast" / "MTGA" / "Player.log"

    displayed = display_path_without_username(home_path)
    assert displayed.startswith(HOME_PLACEHOLDER + os.sep)
    assert str(Path.home()) not in displayed
    # Windows must show %USERPROFILE% (Explorer/cmd expand it); Unix shows ~.
    expected = "%USERPROFILE%" if os.name == "nt" else "~"
    assert HOME_PLACEHOLDER == expected

