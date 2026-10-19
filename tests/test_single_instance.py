import os
import sys
import uuid

import pytest

from mtga_tracker.single_instance import SingleInstanceGuard


@pytest.mark.skipif(sys.platform == "win32", reason="exercises the POSIX flock backend")
def test_guard_rejects_a_second_holder_and_recovers_after_release(tmp_path):
    lock_path = tmp_path / "tracker.lock"
    first = SingleInstanceGuard(lock_path=lock_path)
    second = SingleInstanceGuard(lock_path=lock_path)

    assert first.acquire() is True
    assert lock_path.read_text(encoding="utf-8") == f"{os.getpid()}\n"
    assert second.acquire() is False

    first.release()
    assert second.acquire() is True
    second.release()


@pytest.mark.skipif(sys.platform == "win32", reason="exercises the POSIX flock backend")
def test_guard_release_is_idempotent(tmp_path):
    guard = SingleInstanceGuard(lock_path=tmp_path / "tracker.lock")

    assert guard.acquire() is True
    guard.release()
    guard.release()


@pytest.mark.skipif(sys.platform != "win32", reason="exercises the Windows mutex backend")
def test_windows_mutex_rejects_a_second_holder_and_recovers_after_release():
    mutex_name = rf"Local\TappsTracker.Test.{uuid.uuid4()}"
    first = SingleInstanceGuard(mutex_name=mutex_name)
    second = SingleInstanceGuard(mutex_name=mutex_name)

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()
    assert second.acquire() is True
    second.release()


def test_acquire_with_retry_waits_then_gives_up():
    from mtga_tracker.single_instance import acquire_with_retry

    class Guard:
        def __init__(self, free_after):
            self.calls = 0
            self.free_after = free_after

        def acquire(self):
            self.calls += 1
            return self.calls > self.free_after

    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    guard = Guard(free_after=2)
    assert acquire_with_retry(guard, 60, sleep=sleep, clock=lambda: now[0]) is True
    assert guard.calls == 3 and sleeps == [0.5, 0.5]

    never = Guard(free_after=10**6)
    now[0] = 0.0
    assert acquire_with_retry(never, 2.0, sleep=sleep, clock=lambda: now[0]) is False
    assert never.calls == 5
