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
from utils.exit_codes import LIBRARY_LOCK_HELD_EXIT_CODE, SAVED_NOTHING_EXIT_CODE  # noqa: E402
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

    def test_canon_hif_events_are_accepted(self):
        # Canon HDR PQ stills use the .HIF extension; watch mode must not drop
        # their create/modify events the way the old hard-coded list did. NOT
        # skipped without pillow-heif: watch mode observes the KNOWN container
        # set, so the decoder-less job is the one this most needs to run in.
        pending = _PendingChanges()
        pending.add("/library/IMG_0001.HIF")
        assert pending.take_if_settled(0) == {"/library/IMG_0001.HIF"}

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


def test_watch_suffixes_derive_from_shared_extension_table():
    # Watch mode must not carry its own copy of the format list: the hard-coded
    # one it used to hold had already drifted, omitting Canon .HIF.
    from utils.image_loading import WATCHABLE_IMAGE_EXTENSIONS
    assert WATCH_SUFFIXES == WATCHABLE_IMAGE_EXTENSIONS


def test_watch_suffixes_cover_heif_even_without_pillow_heif():
    # A filesystem event is only a note that the path changed. Narrowing watch
    # mode to what this install can DECODE would mean a library that gains
    # pillow-heif later never sees the HEIF files it already holds, so the
    # watch set is the known-container set and is never gated on availability.
    from utils.image_loading import (
        KNOWN_HEIF_EXTENSIONS, SCANNABLE_IMAGE_EXTENSIONS, WATCHABLE_IMAGE_EXTENSIONS,
    )
    assert KNOWN_HEIF_EXTENSIONS <= WATCHABLE_IMAGE_EXTENSIONS
    assert SCANNABLE_IMAGE_EXTENSIONS <= WATCHABLE_IMAGE_EXTENSIONS
    for suffix in KNOWN_HEIF_EXTENSIONS:
        pending = _PendingChanges()
        pending.add(f"/library/IMG_0001{suffix.upper()}")
        assert pending.take_if_settled(0) == {f"/library/IMG_0001{suffix.upper()}"}


def test_watch_suffixes_include_new_still_formats():
    # Mirrors test_scannable_extensions_include_hif's explicit per-extension
    # assertions, but for the WATCH set specifically -- a regression here
    # would otherwise only be caught implicitly through the subset check
    # above. PNG/GIF/WebP/BMP/TIFF are unconditional; .avif is watched
    # unconditionally too (KNOWN_AVIF_EXTENSIONS, the container set), even on
    # a Pillow build with no AVIF codec -- the same reasoning that gives .hif
    # unconditional watch coverage above.
    for suffix in ('.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.avif'):
        assert suffix in WATCH_SUFFIXES
        pending = _PendingChanges()
        pending.add(f"/library/file{suffix.upper()}")
        assert pending.take_if_settled(0) == {f"/library/file{suffix.upper()}"}


def test_extension_sets_are_immutable():
    # WATCH_SUFFIXES used to be bound to the very same set object as the scan
    # allow-list, so mutating either would silently have rewritten the other.
    import utils.image_loading as il
    for name in ('JPEG_EXTENSIONS', 'RAW_EXTENSIONS', 'KNOWN_HEIF_EXTENSIONS',
                 'HEIF_EXTENSIONS', 'SCANNABLE_IMAGE_EXTENSIONS',
                 'WATCHABLE_IMAGE_EXTENSIONS'):
        assert isinstance(getattr(il, name), frozenset), name


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

    def test_a_scan_that_saved_nothing_is_not_a_failure_that_ends_watching(self, monkeypatch, tmp_path):
        """Exit SAVED_NOTHING_EXIT_CODE is neither a crash nor a success: it must not consume
        the failure budget."""
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        returncodes = iter([SAVED_NOTHING_EXIT_CODE] * 5 + [1, 1, 1])
        runs = []

        def fake_run(cmd, *a, **kw):
            runs.append(cmd)
            return SimpleNamespace(returncode=next(returncodes))

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] > 20:
                raise AssertionError("watch loop did not stop after MAX_CONSECUTIVE_FAILURES")
            handler, _, _ = native.scheduled[0]
            handler.on_created(SimpleNamespace(is_directory=False, src_path=f"/library/f{calls['n']}.jpg"))

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert len(runs) == 5 + MAX_CONSECUTIVE_FAILURES

    def test_a_saved_nothing_scan_between_crashes_does_not_reset_the_streak(self, monkeypatch, tmp_path):
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        returncodes = iter([1, 1, SAVED_NOTHING_EXIT_CODE, 1])
        runs = []

        def fake_run(cmd, *a, **kw):
            runs.append(cmd)
            return SimpleNamespace(returncode=next(returncodes))

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] > 12:
                raise AssertionError("a 4 reset the crash streak: the watch loop kept running")
            handler, _, _ = native.scheduled[0]
            handler.on_created(SimpleNamespace(is_directory=False, src_path=f"/library/f{calls['n']}.jpg"))

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        watcher.run_watch_loop(["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert len(runs) == 4

    def test_a_failing_initial_scan_counts_as_the_first_failure(self, monkeypatch, tmp_path):
        """A failing initial scan consumes the first slot of the failure budget:
        a broken install stops after MAX_CONSECUTIVE_FAILURES total scans
        (initial included) instead of watching forever, and the loop reports the
        give-up to the caller."""
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        returncodes = iter([1] * MAX_CONSECUTIVE_FAILURES)
        runs = []

        def fake_run(cmd, *a, **kw):
            runs.append(cmd)
            return SimpleNamespace(returncode=next(returncodes))

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] > MAX_CONSECUTIVE_FAILURES + 2:
                raise AssertionError("watch loop did not stop after MAX_CONSECUTIVE_FAILURES")
            handler, _, _ = native.scheduled[0]
            handler.on_created(SimpleNamespace(is_directory=False, src_path=f"/library/f{calls['n']}.jpg"))

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        gave_up = not watcher.run_watch_loop(
            ["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=True)

        assert gave_up is True
        assert len(runs) == MAX_CONSECUTIVE_FAILURES

    def test_a_lock_held_scan_does_not_count_toward_the_streak(self, monkeypatch, tmp_path):
        """Exit LIBRARY_LOCK_HELD_EXIT_CODE is transient by definition — another
        job holds the lock and the next settled batch rescans — so a busy
        stretch must not accumulate toward giving up."""
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        returncodes = iter([LIBRARY_LOCK_HELD_EXIT_CODE] * 5 + [1, 1, 1])
        runs = []

        def fake_run(cmd, *a, **kw):
            runs.append(cmd)
            return SimpleNamespace(returncode=next(returncodes))

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] > 20:
                raise AssertionError("watch loop did not stop after MAX_CONSECUTIVE_FAILURES")
            handler, _, _ = native.scheduled[0]
            handler.on_created(SimpleNamespace(is_directory=False, src_path=f"/library/f{calls['n']}.jpg"))

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        gave_up = not watcher.run_watch_loop(
            ["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert gave_up is True
        assert len(runs) == 5 + MAX_CONSECUTIVE_FAILURES

    def test_a_user_interrupted_watch_reports_success(self, monkeypatch, tmp_path):
        """Ctrl-C is a clean stop: the loop must not ask the caller for a
        non-zero exit."""
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        def fake_run(cmd, *a, **kw):
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        def fake_sleep(seconds):
            raise KeyboardInterrupt

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        gave_up = not watcher.run_watch_loop(
            ["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)

        assert gave_up is False

    def test_a_lock_held_batch_is_retried_without_new_events(self, monkeypatch, tmp_path):
        """A batch skipped because another job held the library lock is queued
        again: the retry runs after the next debounce window even when no new
        file event arrives, instead of the batch's photos waiting for an
        unrelated change."""
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        returncodes = iter([LIBRARY_LOCK_HELD_EXIT_CODE, 0])
        runs = []

        def fake_run(cmd, *a, **kw):
            runs.append(cmd)
            return SimpleNamespace(returncode=next(returncodes))

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                handler, _, _ = native.scheduled[0]
                handler.on_created(SimpleNamespace(is_directory=False, src_path="/library/new.jpg"))
            if calls["n"] > 10:
                raise KeyboardInterrupt

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        assert watcher.run_watch_loop(
            ["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=False)
        assert len(runs) == 2

    @pytest.mark.parametrize("initial_code", [LIBRARY_LOCK_HELD_EXIT_CODE, SAVED_NOTHING_EXIT_CODE])
    def test_a_neutral_initial_scan_does_not_count_as_the_first_failure(self, monkeypatch, tmp_path, initial_code):
        """Only a real failure of the initial scan consumes the budget: an
        initial scan that found the library lock held, or saved nothing, leaves
        the streak at 0."""
        native = _FakeObserver()
        monkeypatch.setattr(watchdog.observers, "Observer", lambda: native)
        monkeypatch.setattr(watchdog.observers.polling, "PollingObserver", lambda: _FakeObserver())

        returncodes = iter([initial_code] + [1] * MAX_CONSECUTIVE_FAILURES)
        runs = []

        def fake_run(cmd, *a, **kw):
            runs.append(cmd)
            return SimpleNamespace(returncode=next(returncodes))

        monkeypatch.setattr(watcher.subprocess, "run", fake_run)

        calls = {"n": 0}

        def fake_sleep(seconds):
            calls["n"] += 1
            if calls["n"] > MAX_CONSECUTIVE_FAILURES + 2:
                raise AssertionError("watch loop did not stop after MAX_CONSECUTIVE_FAILURES")
            handler, _, _ = native.scheduled[0]
            handler.on_created(SimpleNamespace(is_directory=False, src_path=f"/library/f{calls['n']}.jpg"))

        monkeypatch.setattr(watcher.time, "sleep", fake_sleep)

        assert not watcher.run_watch_loop(
            ["/library"], str(tmp_path / "photos.db"), debounce_seconds=0, initial_scan=True)
        assert len(runs) == 1 + MAX_CONSECUTIVE_FAILURES
