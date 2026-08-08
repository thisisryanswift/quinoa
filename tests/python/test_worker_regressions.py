"""Regression tests for worker error handling and UI isolation."""

import json
import os
import time
from datetime import datetime
from typing import Any, cast, overload
from unittest.mock import MagicMock

# Headless platform for any PyQt tests in this module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httplib2
import httpx
import pytest
from PyQt6.QtCore import QDeadlineTimer, QThread
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def qapp() -> QApplication:
    """Provide a headless QApplication for Qt signal/widget tests."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    return cast(QApplication, app)


# -----------------------------------------------------------------------------
# TranscribeWorker / EnhanceWorker / ChatWorker error signaling
# -----------------------------------------------------------------------------


def _stereo_path(tmp_path):
    """Create an empty stereo mix file so TranscribeWorker skips audio mixing."""
    path = tmp_path / "mixed_stereo.wav"
    path.write_bytes(b"")
    return str(path)


def test_transcribe_worker_connect_error_emits_user_facing_error(
    qapp: QApplication, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network-level httpx.ConnectError must surface as the worker's error signal."""
    from quinoa.ui import transcribe_worker as tw
    from quinoa.ui.transcribe_worker import TranscribeWorker

    monkeypatch.setattr(
        tw.config,
        "get",
        lambda key, default=None: "test-key" if key == "api_key" else default,
    )

    class FailingTranscriber:
        def __init__(self, api_key: str | None = None) -> None:  # noqa: ARG002
            pass

        def transcribe(self, *args: Any, **kwargs: Any) -> str:  # noqa: ARG002
            raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(tw, "GeminiTranscriber", FailingTranscriber)

    output_dir = tmp_path / "session"
    output_dir.mkdir()
    _stereo_path(output_dir)

    worker = TranscribeWorker(str(output_dir), "rec-1")
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()

    assert len(errors) == 1
    assert "connection" in errors[0].lower()


def test_enhance_worker_connect_error_emits_user_facing_error(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network-level httpx.ConnectError during enhancement must emit error, not crash."""
    from quinoa.ui import enhance_worker as ew
    from quinoa.ui.enhance_worker import EnhanceWorker

    monkeypatch.setattr(
        ew.config,
        "get",
        lambda key, default=None: "test-key" if key == "api_key" else default,
    )

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = httpx.ConnectError("connection failed")
    monkeypatch.setattr(ew.genai, "Client", lambda **kwargs: mock_client)

    worker = EnhanceWorker("notes content", "transcript content")
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()

    assert len(errors) == 1
    assert "connection" in errors[0].lower()


def test_chat_worker_connect_error_emits_user_facing_error(qapp: QApplication) -> None:
    """A network-level httpx.ConnectError during chat must emit error, not crash."""
    from quinoa.search.chat_worker import ChatWorker
    from quinoa.search.file_search import FileSearchManager

    mock_file_search = MagicMock(spec=FileSearchManager)
    mock_file_search.query.side_effect = httpx.ConnectError("connection failed")

    worker = ChatWorker(mock_file_search, "question", [])
    errors: list[str] = []
    worker.error.connect(errors.append)
    worker.run()

    assert len(errors) == 1
    assert "connection" in errors[0].lower()


# -----------------------------------------------------------------------------
# CalendarSyncWorker transport error handling
# -----------------------------------------------------------------------------


def test_calendar_sync_worker_catches_httplib2_error_and_emits_sync_failed(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """httplib2 transport failures must emit sync_failed and stay caught inside the loop."""
    from quinoa.calendar import sync_worker as sw

    monkeypatch.setattr(sw, "get_credentials", lambda: MagicMock(valid=True))
    monkeypatch.setattr(
        sw,
        "CalendarClient",
        MagicMock(side_effect=httplib2.HttpLib2Error("transport failed")),
    )

    worker = sw.CalendarSyncWorker(MagicMock())
    failed: list[str] = []
    worker.sync_failed.connect(failed.append)

    worker._sync_today()

    assert len(failed) == 1
    assert "transport failed" in failed[0]


# -----------------------------------------------------------------------------
# MiddlePanel transcription completion isolation
# -----------------------------------------------------------------------------


@pytest.fixture
def middle_panel(qapp: QApplication, monkeypatch: pytest.MonkeyPatch):
    """Return a MiddlePanel with mocked audio/DB dependencies."""
    from quinoa.ui import middle_panel as mp

    monkeypatch.setattr(mp.quinoa_audio, "list_devices", MagicMock(return_value=[]))
    monkeypatch.setattr(
        mp.quinoa_audio, "subscribe_device_changes", MagicMock(return_value=MagicMock())
    )
    monkeypatch.setattr(mp.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(mp.QMessageBox, "critical", lambda *args, **kwargs: None)

    db = MagicMock()
    db.get_frequent_speakers.return_value = []
    db.get_notes.return_value = None
    db.get_transcript.return_value = None
    db.get_enhanced_notes.return_value = None

    panel = mp.MiddlePanel(db=db)
    panel._mode = mp.PanelMode.IDLE
    panel._viewing_rec_id = None
    panel.current_rec_id = None

    yield panel

    panel.stop_device_monitor()


def _valid_transcript_json() -> str:
    return json.dumps(
        {
            "utterances": [
                {
                    "speaker": "Me",
                    "text": "Hello",
                    "start_time": "00:00",
                    "end_time": "00:01",
                }
            ],
            "summary": "A meeting",
            "action_items": [{"text": "Do work", "assignee": None}],
        }
    )


def test_background_finished_does_not_overwrite_viewed_meeting(middle_panel) -> None:
    """Finishing recording A while viewing B refreshes history but leaves B's UI alone."""
    from quinoa.constants import PanelMode

    panel = middle_panel
    panel._mode = PanelMode.VIEWING
    panel._viewing_rec_id = "B"
    panel.current_rec_id = "A"
    panel.status_label.setText("Idle")

    history_calls: list[int] = []
    panel.on_history_changed = lambda: history_calls.append(1)

    panel._on_transcription_job_finished("A", _valid_transcript_json())

    # Left panel still refreshes for background completion.
    assert history_calls
    # UI of the viewed meeting is unchanged.
    assert panel.status_label.text() == "Idle"
    assert panel._viewing_rec_id == "B"
    assert panel._cached_transcript == ""


def test_visible_finished_updates_ui(middle_panel) -> None:
    """When the finished recording is the one being viewed, UI and controls update."""
    from quinoa.constants import PanelMode

    panel = middle_panel
    panel._mode = PanelMode.VIEWING
    panel._viewing_rec_id = "A"
    panel.current_rec_id = "A"
    panel.transcribe_btn.setEnabled(False)
    panel.transcribe_btn.setText("Transcribing...")

    panel._on_transcription_job_finished("A", _valid_transcript_json())

    assert panel.status_label.text() == "Transcription Complete"
    assert panel.transcribe_btn.text() == "Re-transcribe"
    assert panel.transcribe_btn.isEnabled()
    assert panel._cached_utterances


def test_just_finished_current_updates_ui(middle_panel) -> None:
    """Auto-transcribing the recording that just stopped updates the UI."""
    from quinoa.constants import PanelMode

    panel = middle_panel
    panel._mode = PanelMode.IDLE
    panel._viewing_rec_id = None
    panel.current_rec_id = "A"

    panel._on_transcription_job_finished("A", _valid_transcript_json())

    assert panel.status_label.text() == "Transcription Complete"
    assert panel.transcribe_btn.text() == "Re-transcribe"
    assert panel._cached_utterances


def test_partial_updates_only_viewed_recording(middle_panel) -> None:
    """Partial results update the UI only when the viewed recording is the one that recovered."""
    from quinoa.constants import PanelMode

    panel = middle_panel
    panel._mode = PanelMode.VIEWING
    panel._viewing_rec_id = "A"

    truncated = (
        '{"utterances": ['
        '{"speaker": "Me", "text": "Hello", "start_time": "00:00", "end_time": "00:01"}, '
        '{"speaker": "X", "text": "cut'
    )

    panel._on_transcription_job_partial("A", truncated)

    assert panel.status_label.text() == "Partial Transcription"
    assert panel.transcribe_btn.text() == "Re-transcribe"
    assert panel._cached_utterances


def test_partial_does_not_alter_other_meeting(middle_panel) -> None:
    """A partial result for a background recording must not change the viewed meeting."""
    from quinoa.constants import PanelMode

    panel = middle_panel
    panel._mode = PanelMode.VIEWING
    panel._viewing_rec_id = "B"

    truncated = (
        '{"utterances": ['
        '{"speaker": "Me", "text": "Hello", "start_time": "00:00", "end_time": "00:01"}, '
        '{"speaker": "X", "text": "cut'
    )

    panel._on_transcription_job_partial("A", truncated)

    assert panel._viewing_rec_id == "B"
    assert panel._cached_transcript == ""
    assert panel.status_label.text() != "Partial Transcription"


def test_error_re_enables_controls_for_viewed(middle_panel) -> None:
    """A transcription error for the viewed recording must make controls usable again."""
    from quinoa.constants import PanelMode

    panel = middle_panel
    panel._mode = PanelMode.VIEWING
    panel._viewing_rec_id = "A"
    panel.transcribe_btn.setEnabled(False)
    panel.transcribe_btn.setText("Transcribing...")

    panel._on_transcription_job_error("A", "Something failed")

    assert panel.status_label.text() == "Transcription Failed"
    assert panel.transcribe_btn.isEnabled()
    assert panel.transcribe_btn.text() == "Transcribe"


def test_error_re_enables_controls_for_just_finished(middle_panel) -> None:
    """A transcription error for the just-finished recording must re-enable controls."""
    from quinoa.constants import PanelMode

    panel = middle_panel
    panel._mode = PanelMode.IDLE
    panel._viewing_rec_id = None
    panel.current_rec_id = "A"
    panel.transcribe_btn.setEnabled(False)
    panel.transcribe_btn.setText("Transcribing...")

    panel._on_transcription_job_error("A", "Something failed")

    assert panel.status_label.text() == "Transcription Failed"
    assert panel.transcribe_btn.isEnabled()
    assert panel.transcribe_btn.text() == "Transcribe"


# -----------------------------------------------------------------------------
# MiddlePanel recording stop/finalize error handling
# -----------------------------------------------------------------------------


def test_stop_recording_failure_marks_failed_and_does_not_auto_transcribe(
    qapp: QApplication, middle_panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A RuntimeError from RecordingSession.stop/finalize must mark failed, not completed, and must not auto-transcribe."""
    from quinoa.constants import PanelMode
    from quinoa.ui import middle_panel as mp

    panel = middle_panel

    # Enable auto-transcribe and provide an API key so a clean stop would start transcription.
    monkeypatch.setattr(
        mp.config,
        "get",
        lambda key, default=None: (
            True if key == "auto_transcribe" else "test-key" if key == "api_key" else default
        ),
    )

    # Simulate an active recording with a session that fails to stop/finalize.
    class FailingSession:
        def stop(self) -> None:
            raise RuntimeError("encoder finalize failed")

        def poll_events(self) -> list:
            return []

    panel.recording_session = FailingSession()
    panel.current_rec_id = "rec-fail"
    panel.current_session_dir = "/tmp/rec-fail"
    panel.recording_start_time = time.time() - 10
    panel.recording_paused_time = 0
    panel._mode = PanelMode.RECORDING
    panel.status_label.setText("Recording...")

    # Ensure there are notes to save.
    monkeypatch.setattr(panel, "_get_notes_text", lambda: "saved notes")

    # Capture signals and callbacks that reset tray/history state.
    state_changes: list[bool] = []
    stopped_ids: list[str] = []
    history_calls: list[None] = []
    panel.recording_state_changed.connect(state_changes.append)
    panel.recording_stopped.connect(stopped_ids.append)
    panel.on_history_changed = lambda: history_calls.append(None)

    # Prevent the real transcription path from firing if the timer were started.
    transcription_calls: list[str] = []
    monkeypatch.setattr(
        panel, "_start_transcription", lambda: transcription_calls.append(panel.current_rec_id)
    )

    panel._stop_recording()

    # Notes and best-effort duration saved, status marked failed.
    panel.db.save_notes.assert_called_once_with("rec-fail", "saved notes")
    assert panel.db.update_recording_status.call_count == 1
    call_args = panel.db.update_recording_status.call_args
    assert call_args is not None
    args, kwargs = call_args
    assert args[0] == "rec-fail"
    assert args[1] == "failed"
    assert isinstance(kwargs.get("duration"), (int, float))
    assert isinstance(kwargs.get("ended_at"), datetime)

    # UI/tray/history reset safely but not as successful.
    assert panel.recording_session is None
    assert panel._mode == PanelMode.IDLE
    assert panel.status_label.text() == "Recording failed"
    assert panel.record_btn.text() == "Start Recording"
    assert panel.transcribe_btn.isEnabled()

    # Signals that reset tray and refresh history are still emitted.
    assert state_changes == [False]
    assert stopped_ids == ["rec-fail"]
    assert len(history_calls) == 1

    # No auto-transcribe and no success/completed status.
    assert not transcription_calls
    assert not panel._auto_transcribe_timer.isActive()
    assert "completed" not in [
        call.args[1] for call in panel.db.update_recording_status.call_args_list
    ]


# -----------------------------------------------------------------------------
# Always-emitted terminal ``done`` signal
# -----------------------------------------------------------------------------


def test_transcribe_worker_done_emitted_after_error(
    qapp: QApplication, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TranscribeWorker must emit ``done`` even when an API error occurs."""
    from quinoa.ui import transcribe_worker as tw
    from quinoa.ui.transcribe_worker import TranscribeWorker

    monkeypatch.setattr(
        tw.config,
        "get",
        lambda key, default=None: "test-key" if key == "api_key" else default,
    )

    class FailingTranscriber:
        def __init__(self, api_key: str | None = None) -> None:  # noqa: ARG002
            pass

        def transcribe(self, *args: Any, **kwargs: Any) -> str:  # noqa: ARG002
            raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(tw, "GeminiTranscriber", FailingTranscriber)

    output_dir = tmp_path / "session"
    output_dir.mkdir()
    _stereo_path(output_dir)

    worker = TranscribeWorker(str(output_dir), "rec-1")
    done: list[None] = []
    worker.done.connect(lambda: done.append(None))
    worker.run()

    assert len(done) == 1


def test_genai_http_timeouts_use_milliseconds(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quinoa.constants import GEMINI_GENERATION_TIMEOUT_MS, GEMINI_UPLOAD_TIMEOUT_MS
    from quinoa.search import file_search as fs
    from quinoa.transcription import gemini
    from quinoa.ui import enhance_worker as ew

    captured: list[int | None] = []

    def capture_client(*args: Any, **kwargs: Any) -> MagicMock:
        options = kwargs.get("http_options")
        captured.append(options.timeout if options else None)
        return MagicMock()

    monkeypatch.setattr(gemini.genai, "Client", capture_client)
    gemini.GeminiTranscriber(api_key="test-key")
    monkeypatch.setattr(fs.genai, "Client", capture_client)
    fs.FileSearchManager(api_key="test-key")
    monkeypatch.setattr(ew.genai, "Client", capture_client)
    worker = ew.EnhanceWorker("notes", "transcript")
    monkeypatch.setattr(ew.config, "get", lambda key, default=None: "test-key")
    worker.run()

    assert captured[:2] == [GEMINI_UPLOAD_TIMEOUT_MS, GEMINI_GENERATION_TIMEOUT_MS]
    assert captured[2:] == [GEMINI_GENERATION_TIMEOUT_MS, GEMINI_GENERATION_TIMEOUT_MS]


def test_enhance_worker_done_emitted_after_success(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EnhanceWorker must emit ``done`` after a successful enhancement."""
    from quinoa.ui import enhance_worker as ew
    from quinoa.ui.enhance_worker import EnhanceWorker

    monkeypatch.setattr(
        ew.config,
        "get",
        lambda key, default=None: "test-key" if key == "api_key" else default,
    )

    response = MagicMock()
    response.text = json.dumps({"enhanced_notes": "# Enhanced notes"})
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = response
    monkeypatch.setattr(ew.genai, "Client", lambda **kwargs: mock_client)

    worker = EnhanceWorker("notes content", "transcript content")
    notes_ready: list[str] = []
    done: list[None] = []
    worker.notes_ready.connect(notes_ready.append)
    worker.done.connect(lambda: done.append(None))
    worker.run()

    assert len(notes_ready) == 1
    assert len(done) == 1


def test_enhance_worker_cancel_closes_client(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling EnhanceWorker must close its per-worker HTTP client."""
    import threading

    from quinoa.ui import enhance_worker as ew
    from quinoa.ui.enhance_worker import EnhanceWorker

    monkeypatch.setattr(
        ew.config,
        "get",
        lambda key, default=None: "test-key" if key == "api_key" else default,
    )

    block_event = threading.Event()

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = lambda *args, **kwargs: block_event.wait(5)  # noqa: ARG005
    monkeypatch.setattr(ew.genai, "Client", lambda **kwargs: mock_client)

    worker = EnhanceWorker("notes content", "transcript content")
    worker.start()

    # Give the worker thread time to create the client and block.
    QThread.msleep(150)

    worker.cancel()

    assert worker.isInterruptionRequested()
    assert mock_client.close.called

    block_event.set()
    assert worker.wait(2000) is True


def test_chat_worker_done_emitted_after_response(qapp: QApplication) -> None:
    """ChatWorker must emit ``done`` after a successful response."""
    from quinoa.search.chat_worker import ChatWorker
    from quinoa.search.file_search import FileSearchManager

    mock_file_search = MagicMock(spec=FileSearchManager)
    mock_file_search.query.return_value = ("answer", [])

    worker = ChatWorker(mock_file_search, "question", [])
    done: list[None] = []
    worker.done.connect(lambda: done.append(None))
    worker.run()

    assert len(done) == 1


# -----------------------------------------------------------------------------
# Panel cleanup keeps timed-out workers alive until ``done``
# -----------------------------------------------------------------------------


def test_middle_panel_cleanup_returns_pending_worker(
    qapp: QApplication, middle_panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MiddlePanel.cleanup must return a still-running EnhanceWorker instead of destroying it."""
    import threading

    from PyQt6.QtCore import QThread, pyqtSignal

    from quinoa.ui import main_window as mw

    class FakeEnhanceWorker(QThread):
        notes_ready = pyqtSignal(str)
        error = pyqtSignal(str)
        done = pyqtSignal()

        def __init__(self) -> None:
            super().__init__()
            self._finish_event = threading.Event()
            self._deleted = False

        def cancel(self) -> None:
            self.requestInterruption()

        @overload
        def wait(self, deadline: QDeadlineTimer = ...) -> bool: ...
        @overload
        def wait(self, deadline: int) -> bool: ...
        def wait(self, deadline: QDeadlineTimer | int | None = None) -> bool:
            if deadline is None:
                deadline = QDeadlineTimer()
            if not self._finish_event.is_set():
                return False
            return QThread.wait(self, deadline)

        def run(self) -> None:
            self._finish_event.wait(10)
            self.done.emit()

        def deleteLater(self) -> None:  # noqa: N802
            self._deleted = True

    worker = FakeEnhanceWorker()
    middle_panel._enhance_worker = worker
    worker.start()
    QThread.msleep(100)

    finished, pending = middle_panel.cleanup(timeout_ms=100)

    assert finished is False
    assert pending is worker
    assert middle_panel._enhance_worker is None

    mw._stash_pending_worker(worker)
    worker._finish_event.set()
    assert worker.wait(1000) is True
    qapp.processEvents()

    assert worker not in mw._PENDING_WORKERS
    assert worker._deleted is True


def test_right_panel_cleanup_returns_pending_worker(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RightPanel.cleanup must return a still-running ChatWorker instead of destroying it."""
    import threading

    from PyQt6.QtCore import QThread, pyqtSignal

    from quinoa.search.chat_worker import ChatWorker
    from quinoa.ui import main_window as mw
    from quinoa.ui.right_panel import RightPanel

    class FakeChatWorker(QThread):
        response_ready = pyqtSignal(str, list)
        error = pyqtSignal(str)
        done = pyqtSignal()

        def __init__(self) -> None:
            super().__init__()
            self._finish_event = threading.Event()
            self._deleted = False

        def cancel(self) -> None:
            self.requestInterruption()

        @overload
        def wait(self, deadline: QDeadlineTimer = ...) -> bool: ...
        @overload
        def wait(self, deadline: int) -> bool: ...
        def wait(self, deadline: QDeadlineTimer | int | None = None) -> bool:
            if deadline is None:
                deadline = QDeadlineTimer()
            if not self._finish_event.is_set():
                return False
            return QThread.wait(self, deadline)

        def run(self) -> None:
            self._finish_event.wait(10)
            self.done.emit()

        def deleteLater(self) -> None:  # noqa: N802
            self._deleted = True

    right_panel = RightPanel(db=None)
    worker = FakeChatWorker()
    right_panel._chat_worker = cast(ChatWorker, worker)
    worker.start()
    QThread.msleep(100)

    finished, pending = right_panel.cleanup(timeout_ms=100)

    assert finished is False
    assert pending is worker
    assert right_panel._chat_worker is None

    mw._stash_pending_worker(worker)
    worker._finish_event.set()
    assert worker.wait(1000) is True
    qapp.processEvents()

    assert worker not in mw._PENDING_WORKERS
    assert worker._deleted is True
