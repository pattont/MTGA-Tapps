from mtga_tracker.tray_menu import tray_menu_origin

SCREEN = (0, 0, 2559, 1391)  # 2560x1440 minus a 48 px taskbar at the bottom


def test_menu_opens_upward_from_a_taskbar_cursor():
    # Right-click on a tray icon: the cursor is at the very bottom.
    assert tray_menu_origin((2400, 1420), (220, 300), SCREEN) == (2180, 1091)


def test_menu_opens_downward_when_there_is_room():
    assert tray_menu_origin((100, 100), (220, 300), SCREEN) == (100, 100)


def test_menu_flips_left_at_the_right_edge():
    x, y = tray_menu_origin((2500, 100), (220, 300), SCREEN)
    assert (x, y) == (2280, 100)


def test_menu_taller_than_the_screen_pins_to_the_top():
    assert tray_menu_origin((100, 1420), (220, 5000), SCREEN)[1] == 0
