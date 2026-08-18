"""Tests for processing/watcher.py (--watch mode's supervisor loop).

run_watch_loop() is a blocking synchronous loop: no thread of its own, it
just is the blocked call `facet.py --watch` makes. These tests drive it
directly on the test thread, replacing watchdog's Observer/PollingObserver
with small fakes and time.sleep with a controlled side effect that injects
filesystem events and eventually stops the loop, either via
KeyboardInterrupt or via the loop's own MAX_CONSECUTIVE_FAILURES exit.
subprocess.run is replaced so no real scan ever spawns.
"""

import logging
import os
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("watchdog.observers", exc_type=ImportError)
import watchdog.observers  # noqa: E402
import watchdog.observers.polling  # noqa: E402

import processing.watcher as watcher  # noqa: E402
from processing.watcher import (  # noqa: E402
    MAX_CONSECUTIVE_FAILURES,
    WATCH_SUFFIXES,
    _build_scan_command,
    _PendingChanges,
)

FACET_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(watcher.__file__))), "facet.py",
)


class _FakeObserver:
    def __init__(self):
        self.scheduled = []
        self.start_calls = 0
        self.stop_calls = 0
        self.join_timeout = None

    def schedule(self, handler, directory, recursive=True):
        self.scheduled.append((handler, directory, recursive))

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1

    def join(self, timeout=None):
        self.join_timeout = timeout


class _RaisingObserver(_FakeObserver):
    def start(self):
        self.start_calls += 1
        raise OSError("inotify watch limit reached")


class TestPendingChangesAdd:
    def test_only_watch_suffixes_are_accepted(self):
        pending = _PendingChanges()
        pending.add("/library/img.jpg")
        pending.add("/library/notes.txt")
        assert pending.take_if_settled(0) == {"/library/img.jpg"}

    def test_suffix_match_is_case_insensitive(self):
        pending = _PendingChanges()
        pending.add("/library/IMG_0001.CR2")
        assert pending.take_if_settled(0) == {"/library/IMG_0001.CR2"}

    def test_every_documented_suffix_is_accepted(self):
        pending = _PendingChanges()
        expected = {f"/library/file{suffix}" for suffix in WATCH_SUFFIXES}
        for suffix in WATCH_SUFFIXES:
            pending.add(f"/library/file{suffix}")
        assert pending.take_if_settled(0) == expected

    def test_extensionless_paths_are_ignored(self):
        pending = _PendingChanges()
        pending.add("/library/README")
        assert pending.take_if_settled(0) is None


class TestPendingChangesSettle:
    def test_empty_queue_returns_none(self):
        assert _PendingChanges().take_if_settled(30) is None

    def test_does_not_settle_before_the_debounce_window_elapses(self):
        pending = _PendingChanges()
        pending.add("/library/img.jpg")
        assert pending.take_if_settled(30) is None

    def test_settles_once_the_debounce_window_has_elapsed(self):
        pending = _PendingChanges()
        pending.add("/library/img.jpg")
        pending._last_event -= 31
        assert pending.take_if_settled(30) == {"/library/img.jpg"}

    def test_settled_batch_is_cleared(self):
        pending = _PendingChanges()
        pending.add("/library/img.jpg")
        pending._last_event -= 31
        pending.take_if_settled(30)
        assert pending.take_if_settled(30) is None

    def test_a_new_event_resets_the_debounce_window(self):
        pending = _PendingChanges()
        pending.add("/library/a.jpg")
        pending._last_event -= 31
        pending.add("/library/b.jpg")
        assert pending.take_if_settled(30) is None


class TestBuildScanCommand:
    def test_without_config(self):
        cmd = _build_scan_command(["/a", "/b"], "/data/photos.db", None)
        assert cmd == [sys.executable, FACET_SCRIPT, "/a", "/b", "--db", "/data/photos.db"]

    def test_with_config(self):
        cmd = _build_scan_command(["/a"], "/data/photos.db", "/data/scoring_config.json")
        assert cmd == [
            sys.executable, FACET_SCRIPT, "/a", "--db", "/data/photos.db",
            "--config", "/data/scoring_config.json",
        ]


class TestRunWatchLoopMissingWatchdog:
    def test_missing_watchdog_package_exits(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "watchdog.observers", None)
        with caplog.at_level(logging.ERROR, logger="facet.watcher"):
            with pytest.raises(SystemExit) as exc_info:
                watcher.run_watch_loop(["/library"], "/tmp/does-not-matter.db")
        assert exc_info.value.code == 1
        assert "watchdog" in caplog.text


class TestRunWatchLoopObserverSelection:
    def test_observer_is_scheduled_for_every_directory(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())
        monkeypatch.setattr(watcher.subprocess, "run", lambda cmd, *a, **kw: SimpleNamespace(returncode=0))
        monkeypatch.setattr(watcher.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt))

        watcher.run_watch_loop(["/library/a", "/library/b"], str(tmp_path / "photos.db"), initial_scan=False)

        directories = [directory for _, directory, _ in native.scheduled]
        assert directories == ["/library/a", "/library/b"]
        assert all(recursive is True for _, _, recursive in native.scheduled)

    def test_falls_back_to_polling_when_the_native_observer_fails(self, monkeypatch, tmp_path):
        native = _RaisingObserver()
        polling = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: polling)
        monkeypatch.setattr(watcher.subprocess, "run", lambda cmd, *a, **kw: SimpleNamespace(returncode=0))
        monkeypatch.setattr(watcher.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt))

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), initial_scan=False)

        assert native.start_calls == 1
        assert native.stop_calls == 0
        assert polling.start_calls == 1
        assert polling.stop_calls == 1


class TestRunWatchLoopInitialScan:
    def test_initial_scan_runs_once_before_the_loop(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        runs = []
        monkeypatch.setattr(
            watcher.subprocess, "run",
            lambda cmd, *a, **kw: runs.append(cmd) or SimpleNamespace(returncode=0),
        )
        monkeypatch.setattr(watcher.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt))

        db_path = str(tmp_path / "photos.db")
        watcher.run_watch_loop(["/library"], db_path, initial_scan=True)

        assert runs == [_build_scan_command(["/library"], db_path, None)]
        assert native.start_calls == 1
        assert native.stop_calls == 1

    def test_initial_scan_false_skips_the_immediate_scan(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        runs = []
        monkeypatch.setattr(
            watcher.subprocess, "run",
            lambda cmd, *a, **kw: runs.append(cmd) or SimpleNamespace(returncode=0),
        )
        monkeypatch.setattr(watcher.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt))

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), initial_scan=False)

        assert runs == []


class TestRunWatchLoopScanSpawning:
    def test_no_scan_when_nothing_changes(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        runs = []
        monkeypatch.setattr(
            watcher.subprocess, "run",
            lambda cmd, *a, **kw: runs.append(cmd) or SimpleNamespace(returncode=0),
        )

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] >= 3:
                raise KeyboardInterrupt

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert runs == []

    def test_directory_events_do_not_spawn_a_scan(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        runs = []
        monkeypatch.setattr(
            watcher.subprocess, "run",
            lambda cmd, *a, **kw: runs.append(cmd) or SimpleNamespace(returncode=0),
        )

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                handler, _, _ = native.scheduled[0]
                handler.on_created(SimpleNamespace(is_directory=True, src_path="/library/newdir"))
                return
            raise KeyboardInterrupt

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert runs == []

    def test_settled_batch_spawns_a_scan(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        runs = []
        monkeypatch.setattr(
            watcher.subprocess, "run",
            lambda cmd, *a, **kw: runs.append(cmd) or SimpleNamespace(returncode=0),
        )

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                handler, _, _ = native.scheduled[0]
                handler.on_created(SimpleNamespace(is_directory=False, src_path="/library/new.jpg"))
                return
            raise KeyboardInterrupt

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        db_path = str(tmp_path / "photos.db")
        watcher.run_watch_loop(["/library"], db_path, debounce_seconds=0, initial_scan=False)

        assert runs == [_build_scan_command(["/library"], db_path, None)]

    def test_on_moved_uses_the_destination_path(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        runs = []
        monkeypatch.setattr(
            watcher.subprocess, "run",
            lambda cmd, *a, **kw: runs.append(cmd) or SimpleNamespace(returncode=0),
        )

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                handler, _, _ = native.scheduled[0]
                handler.on_moved(SimpleNamespace(is_directory=False, dest_path="/library/moved.jpg"))
                return
            raise KeyboardInterrupt

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert len(runs) == 1


class TestRunWatchLoopFailureHandling:
    def test_stops_after_max_consecutive_failures(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        runs = []
        monkeypatch.setattr(
            watcher.subprocess, "run",
            lambda cmd, *a, **kw: runs.append(cmd) or SimpleNamespace(returncode=1),
        )

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] > MAX_CONSECUTIVE_FAILURES + 2:
                raise AssertionError("watch loop did not stop after MAX_CONSECUTIVE_FAILURES")
            handler, _, _ = native.scheduled[0]
            handler.on_created(SimpleNamespace(is_directory=False, src_path=f"/library/f{calls['n']}.jpg"))

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert len(runs) == MAX_CONSECUTIVE_FAILURES

    def test_a_success_after_failures_resets_the_counter(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        returncodes = iter([1, 1, 0, 1, 1, 1])
        runs = []

        def fake_run(cmd, *a, **kw):
            runs.append(cmd)
            return SimpleNamespace(returncode=next(returncodes))

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] > len(runs) + 8:
                raise AssertionError("watch loop did not stop after MAX_CONSECUTIVE_FAILURES")
            handler, _, _ = native.scheduled[0]
            handler.on_created(SimpleNamespace(is_directory=False, src_path=f"/library/f{calls['n']}.jpg"))

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert len(runs) == 6
