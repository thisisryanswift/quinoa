"""Regression tests for graceful SIGINT shutdown and unified quit routing."""

import contextlib
import os
import signal
import time
from collections.abc import Callable
from unittest.mock import MagicMock

# Headless platform for any PyQt tests in this module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QObject, QSocketNotifier, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from quinoa.constants import PanelMode
from quinoa.main import start_test, stop_test


@pytest.fixture
def qapp() -> QApplication:
    """Provide a headless QApplication for Qt signal/widget tests."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# SigintBridge
# ---------------------------------------------------------------------------


@pytest.fixture
def sigint_bridge(qapp: QApplication):
    """Create a SigintBridge and clean it up after the test."""
    from quinoa.main import SigintBridge

    bridge = SigintBridge()
    yield bridge
    if not getattr(bridge, "_disposed", False):
        bridge.dispose()


def _write_wakeup_byte(bridge, byte: bytes = b"\0") -> None:
    """Simulate CPython's wakeup-fd write, ignoring closed-pipe errors."""
    with contextlib.suppress(OSError):
        os.write(bridge._write_fd, byte)


def test_sigint_bridge_emits_one_quit_for_repeated_bytes(sigint_bridge, qapp: QApplication) -> None:
    """Repeated wakeup bytes must coalesce into exactly one quit request."""
    emitted: list[None] = []
    sigint_bridge.quit_requested.connect(lambda: emitted.append(None))

    for _ in range(3):
        _write_wakeup_byte(sigint_bridge)

    qapp.processEvents()
    qapp.processEvents()

    assert len(emitted) == 1


def test_sigint_bridge_coalesces_after_first_emit(sigint_bridge, qapp: QApplication) -> None:
    """Additional bytes after the first emitted quit request are ignored."""
    emitted: list[None] = []
    sigint_bridge.quit_requested.connect(lambda: emitted.append(None))

    _write_wakeup_byte(sigint_bridge)
    qapp.processEvents()
    _write_wakeup_byte(sigint_bridge)
    qapp.processEvents()

    assert len(emitted) == 1


def test_sigint_bridge_noop_handler_does_not_raise(sigint_bridge, qapp: QApplication) -> None:
    """The installed Python SIGINT handler is a no-op and returns normally."""
    import quinoa.main as qmain

    assert signal.getsignal(signal.SIGINT) is qmain._noop_signal_handler
    # A no-op handler returns None and does not raise; the assertion below is
    # the absence of an exception.
    qmain._noop_signal_handler(signal.SIGINT, None)


def test_sigint_bridge_restores_wakeup_fd_and_handler(qapp: QApplication) -> None:
    """Disposal restores the previous wakeup descriptor and SIGINT handler."""
    import quinoa.main as qmain

    original_handler = signal.getsignal(signal.SIGINT)
    original_wakeup = signal.set_wakeup_fd(-1)
    signal.set_wakeup_fd(original_wakeup)

    bridge = qmain.SigintBridge()
    try:
        assert signal.getsignal(signal.SIGINT) is qmain._noop_signal_handler
        current_wakeup = signal.set_wakeup_fd(-1)
        signal.set_wakeup_fd(current_wakeup)
        assert current_wakeup == bridge._write_fd
    finally:
        bridge.dispose()

    assert signal.getsignal(signal.SIGINT) is original_handler
    restored_wakeup = signal.set_wakeup_fd(-1)
    signal.set_wakeup_fd(restored_wakeup)
    assert restored_wakeup == original_wakeup
    assert bridge._read_fd == -1
    assert bridge._write_fd == -1


def test_sigint_bridge_dispose_is_idempotent_and_non_throwing(
    qapp: QApplication,
) -> None:
    """Repeated disposal is safe and never raises."""
    import quinoa.main as qmain

    bridge = qmain.SigintBridge()
    bridge.dispose()
    bridge.dispose()
    bridge.dispose()

    assert bridge._disposed is True
    assert bridge._read_fd == -1
    assert bridge._write_fd == -1


def test_sigint_bridge_closed_pipe_after_disposal(qapp: QApplication) -> None:
    """After disposal the bridge file descriptors are closed."""
    import quinoa.main as qmain

    bridge = qmain.SigintBridge()
    bridge.dispose()

    with pytest.raises(OSError):
        os.write(bridge._write_fd, b"\0")


def test_sigint_bridge_partial_setup_rollback(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late setup failure rolls back handler/wakeup/fds and re-raises."""
    import quinoa.main as qmain

    original_handler = signal.getsignal(signal.SIGINT)
    original_wakeup = signal.set_wakeup_fd(-1)
    signal.set_wakeup_fd(original_wakeup)

    read_fd, write_fd = os.pipe()

    class FailingNotifier(QSocketNotifier):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("notifier boom")

    monkeypatch.setattr(qmain.os, "pipe", lambda: (read_fd, write_fd))
    monkeypatch.setattr(qmain, "QSocketNotifier", FailingNotifier)

    with pytest.raises(RuntimeError, match="notifier boom"):
        qmain.SigintBridge()

    assert signal.getsignal(signal.SIGINT) is original_handler
    current_wakeup = signal.set_wakeup_fd(-1)
    signal.set_wakeup_fd(current_wakeup)
    assert current_wakeup == original_wakeup

    with pytest.raises(OSError):
        os.fstat(read_fd)
    with pytest.raises(OSError):
        os.fstat(write_fd)


# ---------------------------------------------------------------------------
# MainWindow quit routing
# ---------------------------------------------------------------------------


class FakeMiddlePanel(QWidget):
    """Minimal stand-in for MainWindow's middle panel."""

    recording_state_changed = pyqtSignal(bool)
    recording_started = pyqtSignal(str)
    recording_stopped = pyqtSignal(str)
    silence_detected = pyqtSignal()
    metadata_changed = pyqtSignal(str)

    def __init__(
        self,
        db: object | None = None,
        transcription_manager: object | None = None,
        on_history_changed: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.transcription_manager = transcription_manager
        self.on_history_changed = on_history_changed
        self.calls: list[str] = []
        self._recording = False
        self.record_btn = MagicMock()
        self.record_btn.isEnabled.return_value = True
        self._auto_transcribe_timer = QTimer(self)

    def stop_recording_for_shutdown(self) -> None:
        self.calls.append("stop_recording_for_shutdown")

    def cleanup(self, timeout_ms: int = 2000) -> tuple[bool, None]:
        self.calls.append("cleanup")
        return True, None

    def stop_device_monitor(self) -> None:
        self.calls.append("stop_device_monitor")

    def on_meeting_renamed(self, rec_id: str, new_title: str) -> None:
        pass

    def toggle_recording(self) -> None:
        self._recording = not self._recording
        self.calls.append("toggle_recording")

    def focus_notes(self) -> None:
        pass

    @property
    def is_recording(self) -> bool:
        return self._recording


class FakeCalendarPanel(QWidget):
    meeting_selected = pyqtSignal(str)
    recording_selected = pyqtSignal(str)
    search_result_selected = pyqtSignal(str, str)
    new_meeting_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    meeting_renamed = pyqtSignal(str, str)

    def __init__(self, db: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db

    def refresh(self) -> None:
        pass

    def select_meeting(self, rec_id: str) -> None:
        pass


class FakeRightPanel(QWidget):
    citation_clicked = pyqtSignal(str)

    def __init__(self, db: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db

    def set_file_search(self, manager: object) -> None:
        pass

    def set_enabled(self, enabled: bool) -> None:
        pass

    def set_viewing_context(self, ctx: object) -> None:
        pass

    def cleanup(self, timeout_ms: int = 2000) -> tuple[bool, None]:
        return True, None


class FakeTrayIconManager(QObject):
    message_clicked = pyqtSignal()
    start_recording_requested = pyqtSignal(str)

    def __init__(self, parent_window: QWidget | None = None) -> None:
        super().__init__(parent_window)
        self._parent_window = parent_window
        self._visible = False

    def setup(self) -> bool:
        self._visible = False
        return True

    def is_visible(self) -> bool:
        return self._visible

    def show_message(self, *args: object, **kwargs: object) -> None:
        pass

    def cleanup(self) -> None:
        pass


@pytest.fixture
def main_window(qapp: QApplication, monkeypatch: pytest.MonkeyPatch):
    """Build a MainWindow with all heavy dependencies replaced by fakes."""
    from quinoa.ui import main_window as mw

    monkeypatch.setattr(mw, "Database", MagicMock)
    monkeypatch.setattr(mw, "TranscriptionManager", lambda db, parent: MagicMock())
    monkeypatch.setattr(mw, "config", MagicMock())
    monkeypatch.setattr(mw.config, "get", lambda key, default=None: default)
    monkeypatch.setattr(mw, "calendar_is_authenticated", lambda: False)
    monkeypatch.setattr(mw, "FileSearchManager", MagicMock)
    monkeypatch.setattr(mw, "SyncWorker", MagicMock)
    monkeypatch.setattr(mw, "CalendarSyncWorker", MagicMock)
    monkeypatch.setattr(mw, "NotificationWorker", MagicMock)
    monkeypatch.setattr(mw, "CompressionWorker", lambda db: MagicMock())
    monkeypatch.setattr(mw, "CalendarPanel", FakeCalendarPanel)
    monkeypatch.setattr(mw, "RightPanel", FakeRightPanel)
    monkeypatch.setattr(mw, "TrayIconManager", FakeTrayIconManager)
    monkeypatch.setattr(mw, "MiddlePanel", FakeMiddlePanel)

    window = mw.MainWindow()
    yield window
    window.close()


def test_request_quit_sets_intent_and_closes_once(main_window) -> None:
    """request_quit must set quit intent and call close() exactly once."""
    main_window.close = MagicMock()

    main_window.request_quit()
    main_window.request_quit()
    main_window.request_quit()

    assert main_window._quitting is True
    assert main_window.close.call_count == 1


def test_close_event_quit_bypasses_tray_and_cleans_up(
    main_window, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quit-intent close must bypass minimize-to-tray and stop recording first."""
    order: list[str] = []
    recording_mock = MagicMock(side_effect=lambda: order.append("recording"))

    monkeypatch.setattr(main_window, "_save_window_state", lambda: order.append("save_state"))
    monkeypatch.setattr(main_window.middle_panel, "stop_recording_for_shutdown", recording_mock)
    monkeypatch.setattr(
        main_window.transcription_manager, "cancel_all", lambda: order.append("transcription")
    )
    monkeypatch.setattr(main_window, "_stop_calendar_sync", lambda: order.append("calendar"))
    monkeypatch.setattr(
        main_window, "_stop_notification_worker", lambda: order.append("notification")
    )
    monkeypatch.setattr(
        main_window, "_stop_compression_worker", lambda: order.append("compression")
    )

    def fake_middle_cleanup(timeout_ms: int = 2000) -> tuple[bool, None]:
        order.append("middle_cleanup")
        return True, None

    def fake_right_cleanup(timeout_ms: int = 2000) -> tuple[bool, None]:
        order.append("right_cleanup")
        return True, None

    monkeypatch.setattr(main_window.middle_panel, "cleanup", fake_middle_cleanup)
    monkeypatch.setattr(main_window.right_panel, "cleanup", fake_right_cleanup)
    monkeypatch.setattr(
        main_window.middle_panel, "stop_device_monitor", lambda: order.append("device_monitor")
    )
    monkeypatch.setattr(main_window.tray_manager, "cleanup", lambda: order.append("tray"))

    main_window.tray_manager._visible = True
    main_window._quitting = True
    event = QCloseEvent()
    main_window.closeEvent(event)

    assert event.isAccepted()
    assert main_window._shutdown_started is True
    assert "recording" in order
    recording_index = order.index("recording")
    for name in (
        "transcription",
        "calendar",
        "notification",
        "compression",
        "middle_cleanup",
        "right_cleanup",
        "device_monitor",
        "tray",
    ):
        assert name in order
        assert order.index(name) > recording_index
    assert recording_mock.call_count == 1


def test_close_event_is_idempotent(main_window, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated close events must not repeat the cleanup sequence."""
    recording_mock = MagicMock()
    monkeypatch.setattr(main_window.middle_panel, "stop_recording_for_shutdown", recording_mock)

    main_window.tray_manager._visible = False
    main_window._quitting = False

    event1 = QCloseEvent()
    main_window.closeEvent(event1)

    event2 = QCloseEvent()
    main_window.closeEvent(event2)

    assert event1.isAccepted()
    assert event2.isAccepted()
    assert recording_mock.call_count == 1
    assert main_window._shutdown_started is True


def test_close_event_ordinary_close_minimizes_to_tray(main_window) -> None:
    """An ordinary close with tray available must hide the window, not exit."""
    main_window.tray_manager._visible = True
    main_window._quitting = False
    event = QCloseEvent()
    main_window.closeEvent(event)

    assert not event.isAccepted()
    assert main_window._quitting is False


def test_cleanup_continues_after_recording_shutdown_error(
    main_window, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If recording shutdown raises, the remaining worker/device/tray cleanup still runs."""
    order: list[str] = []

    def failing_stop() -> None:
        order.append("recording")
        raise RuntimeError("shutdown recording failure")

    monkeypatch.setattr(main_window.middle_panel, "stop_recording_for_shutdown", failing_stop)
    monkeypatch.setattr(main_window, "_save_window_state", lambda: order.append("save_state"))
    monkeypatch.setattr(
        main_window.transcription_manager, "cancel_all", lambda: order.append("transcription")
    )
    monkeypatch.setattr(main_window, "_stop_calendar_sync", lambda: order.append("calendar"))
    monkeypatch.setattr(
        main_window, "_stop_notification_worker", lambda: order.append("notification")
    )
    monkeypatch.setattr(
        main_window, "_stop_compression_worker", lambda: order.append("compression")
    )

    def fake_middle_cleanup(timeout_ms: int = 2000) -> tuple[bool, None]:
        order.append("middle_cleanup")
        return True, None

    def fake_right_cleanup(timeout_ms: int = 2000) -> tuple[bool, None]:
        order.append("right_cleanup")
        return True, None

    monkeypatch.setattr(main_window.middle_panel, "cleanup", fake_middle_cleanup)
    monkeypatch.setattr(main_window.right_panel, "cleanup", fake_right_cleanup)
    monkeypatch.setattr(
        main_window.middle_panel, "stop_device_monitor", lambda: order.append("device_monitor")
    )
    monkeypatch.setattr(main_window.tray_manager, "cleanup", lambda: order.append("tray"))

    main_window._cleanup_for_exit()

    assert main_window._shutdown_started is True
    assert "recording" in order
    recording_index = order.index("recording")
    for name in (
        "save_state",
        "transcription",
        "calendar",
        "notification",
        "compression",
        "middle_cleanup",
        "right_cleanup",
        "device_monitor",
        "tray",
    ):
        assert name in order
        assert order.index(name) > recording_index


# ---------------------------------------------------------------------------
# MiddlePanel shutdown recording stop
# ---------------------------------------------------------------------------


@pytest.fixture
def middle_panel(qapp: QApplication, monkeypatch: pytest.MonkeyPatch):
    """Return a MiddlePanel with mocked audio/DB dependencies."""
    from quinoa.ui import middle_panel as mp

    monkeypatch.setattr(mp.quinoa_audio, "list_devices", MagicMock(return_value=[]))
    monkeypatch.setattr(
        mp.quinoa_audio, "subscribe_device_changes", MagicMock(return_value=MagicMock())
    )

    db = MagicMock()
    db.get_frequent_speakers.return_value = []
    db.get_notes.return_value = None
    db.get_transcript.return_value = None
    db.get_enhanced_notes.return_value = None

    panel = mp.MiddlePanel(db=db)
    panel._mode = PanelMode.IDLE
    panel._viewing_rec_id = None
    panel.current_rec_id = None
    panel._shutting_down = False

    yield panel

    panel.stop_device_monitor()


def _setup_active_recording(panel, session: object, rec_id: str = "rec-1") -> None:
    """Put a MiddlePanel into an active recording state with the given session."""
    panel.recording_session = session
    panel.current_rec_id = rec_id
    panel.current_session_dir = "/tmp"
    panel.recording_start_time = time.time() - 5
    panel.recording_paused_time = 0.0
    panel._mode = PanelMode.RECORDING
    panel.status_label.setText("Recording...")


def test_stop_recording_for_shutdown_sets_shutting_down_and_stops_timer(
    middle_panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shutdown stop must set the shutdown flag and stop pending auto-transcription."""
    from quinoa.ui import middle_panel as mp

    class CleanSession:
        def stop(self) -> None:
            pass

    _setup_active_recording(middle_panel, CleanSession())
    middle_panel._auto_transcribe_timer.start(10000)

    monkeypatch.setattr(
        mp.config,
        "get",
        lambda key, default=None: (
            True if key == "auto_transcribe" else "test-key" if key == "api_key" else default
        ),
    )

    middle_panel.stop_recording_for_shutdown()

    assert middle_panel._shutting_down is True
    assert not middle_panel._auto_transcribe_timer.isActive()
    assert middle_panel.recording_session is None
    assert middle_panel.db.update_recording_status.call_count == 1
    assert middle_panel.db.update_recording_status.call_args.args[1] == "completed"


def test_shutdown_failed_stop_marks_failed_and_skips_modal(
    middle_panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shutdown recording finalization error must mark failed without a modal dialog."""
    from quinoa.ui import middle_panel as mp

    class FailingSession:
        def stop(self) -> None:
            raise RuntimeError("encoder finalize failed")

    _setup_active_recording(middle_panel, FailingSession(), rec_id="rec-fail")

    monkeypatch.setattr(
        mp.config,
        "get",
        lambda key, default=None: (
            True if key == "auto_transcribe" else "test-key" if key == "api_key" else default
        ),
    )
    mock_qmb = MagicMock()
    monkeypatch.setattr(mp, "QMessageBox", mock_qmb)

    middle_panel.stop_recording_for_shutdown()

    assert middle_panel._shutting_down is True
    assert not middle_panel._auto_transcribe_timer.isActive()
    assert middle_panel.recording_session is None
    assert middle_panel.db.update_recording_status.call_args.args[1] == "failed"
    assert not mock_qmb.critical.called


def test_shutdown_suppresses_async_modals(middle_panel, monkeypatch: pytest.MonkeyPatch) -> None:
    """Async error callbacks must not open modal dialogs while shutting down."""
    from quinoa.ui import middle_panel as mp

    mock_qmb = MagicMock()
    monkeypatch.setattr(mp, "QMessageBox", mock_qmb)

    middle_panel._shutting_down = True
    middle_panel._handle_audio_error("PipeWire connection lost")
    middle_panel._on_transcription_job_error("rec-1", "network error")
    middle_panel._on_enhancement_error("model failed")

    assert not mock_qmb.critical.called
    assert not mock_qmb.warning.called


def test_stop_recording_for_shutdown_without_session(middle_panel) -> None:
    """Shutdown stop with no active session still cancels pending auto-transcription."""
    middle_panel._shutting_down = False
    middle_panel._auto_transcribe_timer.start(10000)
    middle_panel.recording_session = None

    middle_panel.stop_recording_for_shutdown()

    assert middle_panel._shutting_down is True
    assert not middle_panel._auto_transcribe_timer.isActive()


# ---------------------------------------------------------------------------
# Tray Quit
# ---------------------------------------------------------------------------


class FakeDBusNotifier(QObject):
    start_recording_requested = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def setup(self) -> bool:
        return False


class FakeMainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.request_quit = MagicMock()
        self.toggle_recording = MagicMock()


@pytest.fixture
def tray_manager(qapp: QApplication, monkeypatch: pytest.MonkeyPatch):
    """Build a TrayIconManager with tray available and D-Bus disabled."""
    from quinoa.ui import tray_icon as ti

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(ti, "DBusNotifier", FakeDBusNotifier)

    parent = FakeMainWindow()
    manager = ti.TrayIconManager(parent)  # type: ignore[arg-type]
    manager.setup()
    yield manager
    manager.cleanup()


def test_tray_quit_delegates_to_parent_request_quit(tray_manager) -> None:
    """The tray Quit action must call the window's shared request_quit entrypoint."""
    quit_action = None
    for action in tray_manager.tray_icon.contextMenu().actions():
        if action.text() == "Quit":
            quit_action = action
            break

    assert quit_action is not None
    quit_action.trigger()

    assert tray_manager._parent_window.request_quit.call_count == 1


# ---------------------------------------------------------------------------
# Smoke-test helpers
# ---------------------------------------------------------------------------


class FakeSmokePanel:
    def __init__(self, enabled: bool = True, recording: bool = False) -> None:
        self.record_btn = MagicMock()
        self.record_btn.isEnabled.return_value = enabled
        self._recording = recording

    @property
    def is_recording(self) -> bool:
        return self._recording

    def toggle_recording(self) -> None:
        self._recording = not self._recording


class FakeSmokeWindow:
    def __init__(self, enabled: bool = True, recording: bool = False) -> None:
        self.middle_panel = FakeSmokePanel(enabled=enabled, recording=recording)
        self.request_quit = MagicMock()
        self.toggle_recording_call_count = 0

    def toggle_recording(self) -> None:
        self.toggle_recording_call_count += 1
        self.middle_panel._recording = not self.middle_panel._recording


def test_start_test_no_device_requests_quit() -> None:
    """Smoke start with a disabled record button must exit through request_quit."""
    window = FakeSmokeWindow(enabled=False, recording=False)
    app = MagicMock()

    start_test(window, app)

    assert window.request_quit.call_count == 1
    assert window.toggle_recording_call_count == 0
    assert app.quit.call_count == 0


def test_stop_test_skips_toggle_when_not_recording() -> None:
    """Smoke stop must not start a new recording if the start never succeeded."""
    window = FakeSmokeWindow(enabled=True, recording=False)
    app = MagicMock()

    stop_test(window, app)

    assert window.toggle_recording_call_count == 0
    assert window.request_quit.call_count == 1
    assert app.quit.call_count == 0


def test_stop_test_stops_active_recording_then_requests_quit() -> None:
    """Smoke stop must stop an active recording before requesting quit."""
    window = FakeSmokeWindow(enabled=True, recording=True)
    app = MagicMock()

    stop_test(window, app)

    assert window.toggle_recording_call_count == 1
    assert window.request_quit.call_count == 1
    assert app.quit.call_count == 0


def test_start_test_successful_path_schedules_stop_and_requests_quit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke start schedules stop_test and ends by calling request_quit, not app.quit."""
    import quinoa.main as qmain

    class FakeTimer:
        calls: list[tuple[int, Callable[[], None]]] = []

        @staticmethod
        def singleShot(delay: int, callback: Callable[[], None]) -> None:
            FakeTimer.calls.append((delay, callback))
            callback()

    monkeypatch.setattr(qmain, "QTimer", FakeTimer)

    window = FakeSmokeWindow(enabled=True, recording=False)
    app = MagicMock()

    start_test(window, app)

    assert window.toggle_recording_call_count == 2
    assert window.request_quit.call_count == 1
    assert app.quit.call_count == 0
    assert len(FakeTimer.calls) == 1
    assert FakeTimer.calls[0][0] == 3000
