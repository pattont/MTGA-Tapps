"""Offline checks for the native bridge wrapper. Never attaches to Arena."""

import sys
from types import SimpleNamespace

import pytest

from mtga_tracker import native_deck_bridge as nb


def fake_exports(calls, refresh=lambda account: True):
    return SimpleNamespace(
        open=lambda: {"account_id": "account"},
        createprepared=lambda account, arena_id: calls.append("create") or {},
        remove=lambda account, snapshot: calls.append("remove") or True,
        roster=lambda account: calls.append("roster")
        or {"account_id": account, "roster_refreshed": True},
        refreshscreen=lambda account, select: calls.append(("refreshscreen", select))
        or refresh(account),
        close=lambda: calls.append("close"),
    )


def test_decks_screen_is_redrawn_only_after_an_arena_write():
    calls = []
    bridge = nb.ArenaBridge(fake_exports(calls))
    bridge.roster()
    assert bridge.refresh_screen() is False
    assert not [call for call in calls if call[0] == "refreshscreen"]
    bridge.create_prepared("new-deck")
    assert bridge.refresh_screen() is True
    # The redraw selects the deck this job created.
    assert calls[-1] == ("refreshscreen", "new-deck")


def test_a_failed_decks_redraw_never_fails_the_transfer():
    def fail(account):
        raise RuntimeError("Decks screen closed")

    bridge = nb.ArenaBridge(fake_exports([], fail))
    bridge.remove({"arena_id": "old"})
    assert bridge.refresh_screen() is False


@pytest.fixture
def fake_frida(monkeypatch):
    calls = []
    script = SimpleNamespace(load=lambda: None, exports_sync=fake_exports(calls))
    session = SimpleNamespace(create_script=lambda _: script, detach=lambda: calls.append("detach"))
    device = SimpleNamespace(
        enumerate_processes=lambda: [SimpleNamespace(pid=7, name="MTGA")],
        attach=lambda pid: session,
    )
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_local_device=lambda: device))
    monkeypatch.setattr(nb, "availability", lambda: (True, ""))
    monkeypatch.setattr(
        nb,
        "Timer",
        lambda *args: SimpleNamespace(daemon=False, start=lambda: None, cancel=lambda: None),
    )
    return calls


def test_closing_a_job_redraws_decks_before_detaching_even_after_a_failure(fake_frida):
    with pytest.raises(RuntimeError, match="second deck"):
        with nb.attach() as bridge:
            bridge.remove({"arena_id": "first"})
            raise RuntimeError("second deck failed")
    # A removal has no new deck to select.
    assert fake_frida == ["remove", ("refreshscreen", None), "close", "detach"]


def test_read_only_jobs_leave_the_decks_screen_alone(fake_frida):
    with nb.attach() as bridge:
        bridge.roster()
    assert fake_frida == ["roster", "close", "detach"]


@pytest.mark.parametrize(
    "system, machine, supported",
    [
        ("Darwin", "arm64", True),
        ("Darwin", "x86_64", False),
        ("Windows", "AMD64", True),
        ("Windows", "ARM64", False),
        ("Windows", "x86", False),
        ("Linux", "x86_64", False),
    ],
)
def test_native_transfers_run_on_apple_silicon_and_x64_windows(
    monkeypatch, system, machine, supported
):
    from mtga_tracker import paths

    monkeypatch.setattr(paths.platform, "system", lambda: system)
    monkeypatch.setattr(paths.platform, "machine", lambda: machine)
    assert paths.native_deck_platform_supported() is supported


def test_windows_arena_process_is_found_by_its_exe_name(fake_frida, monkeypatch):
    attached = []
    frida = sys.modules["frida"]
    device = frida.get_local_device()
    original = device.attach
    device.enumerate_processes = lambda: [
        SimpleNamespace(pid=3, name="explorer.exe"),
        SimpleNamespace(pid=9, name="MTGA.exe"),
    ]
    device.attach = lambda pid: attached.append(pid) or original(pid)
    with nb.attach():
        pass
    assert attached == [9]
