"""Regression tests for the trim view worker threads."""

import os
import shutil
import wave
from pathlib import Path

# Set headless platform before importing PyQt6 so the plugin selection is stable.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from quinoa.ui.trim_view import AnalysisWorker, TrimWorker


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Create a headless QApplication for the test module."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


def _write_tone_wav(path: Path, duration: float, sample_rate: int = 48000) -> None:
    """Write a brief sine tone WAV for worker tests."""
    import math

    n_frames = int(duration * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.setnframes(n_frames)
        for i in range(n_frames):
            value = int(32767 * 0.5 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wf.writeframes(value.to_bytes(2, "little", signed=True))


def test_analysis_worker_emits_finished_for_missing_file(
    qapp: QApplication, tmp_path: Path
) -> None:
    """AnalysisWorker always emits finished, even when analysis fails."""
    worker = AnalysisWorker(str(tmp_path / "missing.wav"))
    captured: list[object] = []
    worker.finished.connect(captured.append)
    worker.run()

    assert len(captured) == 1
    assert captured[0] is None


def test_analysis_worker_emits_finished_on_exception(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AnalysisWorker emits a failure result when analyse_audio raises."""
    from quinoa.ui import trim_view

    monkeypatch.setattr(
        trim_view,
        "analyse_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    worker = AnalysisWorker(str(tmp_path / "any.wav"))
    captured: list[object] = []
    worker.finished.connect(captured.append)
    worker.run()

    assert len(captured) == 1
    assert captured[0] is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_trim_worker_emits_finished_on_success(qapp: QApplication, tmp_path: Path) -> None:
    """TrimWorker emits finished with success=True after a valid trim."""
    from quinoa.audio.trimmer import TrimRegion

    recording_dir = tmp_path / "recording"
    recording_dir.mkdir()
    _write_tone_wav(recording_dir / "microphone.wav", 1.0)

    worker = TrimWorker(str(recording_dir), [TrimRegion(0.0, 0.5)])
    results: list[tuple[bool, float]] = []
    worker.finished.connect(lambda success, dur: results.append((success, dur)))
    worker.run()

    assert len(results) == 1
    success, duration = results[0]
    assert success is True
    assert duration == pytest.approx(0.5, abs=0.01)


def test_trim_worker_emits_finished_on_exception(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TrimWorker emits a failure signal when trim_recording raises."""
    from quinoa.audio.trimmer import TrimRegion
    from quinoa.ui import trim_view

    monkeypatch.setattr(
        trim_view,
        "trim_recording",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    worker = TrimWorker(str(tmp_path / "recording"), [TrimRegion(0.0, 1.0)])
    results: list[tuple[bool, float]] = []
    worker.finished.connect(lambda success, dur: results.append((success, dur)))
    worker.run()

    assert len(results) == 1
    success, duration = results[0]
    assert success is False
    assert duration == 0.0
