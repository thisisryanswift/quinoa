"""Unit tests for waveform widget cut management."""

import os

# Set headless platform before importing PyQt6 so the plugin selection is stable.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import QApplication

from quinoa.ui.waveform_widget import MIN_REGION_SECONDS, CutMarker, WaveformWidget


@pytest.fixture(scope="module")
def qapp() -> QCoreApplication:
    """Create a headless QApplication for the test module."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def widget(qapp: QApplication) -> WaveformWidget:
    """Return a configured WaveformWidget with a 10-second duration."""
    w = WaveformWidget()
    w.set_waveform([0.0, 0.5, 1.0, 0.5], 10.0)
    return w


def test_get_cuts_empty(widget: WaveformWidget) -> None:
    """A fresh widget has no cuts."""
    assert widget.get_cuts() == []


def test_add_cut(widget: WaveformWidget) -> None:
    """add_cut stores a CutMarker and emits cuts_changed."""
    changes: list[None] = []
    widget.cuts_changed.connect(lambda: changes.append(None))

    widget.add_cut(1.0, 3.0)
    assert len(widget.get_cuts()) == 1
    assert widget.get_cuts()[0] == CutMarker(1.0, 3.0)
    assert len(changes) == 1


def test_add_cut_clamps_and_rejects_tiny(widget: WaveformWidget) -> None:
    """add_cut clamps to the duration and ignores very small regions."""
    widget.add_cut(-5.0, 15.0)
    assert widget.get_cuts()[0] == CutMarker(0.0, 10.0)

    widget.clear_cuts()
    widget.add_cut(2.0, 2.0 + MIN_REGION_SECONDS - 0.01)
    assert widget.get_cuts() == []


def test_add_cut_merges_overlapping(widget: WaveformWidget) -> None:
    """Overlapping cuts are merged into a single region."""
    widget.add_cut(1.0, 3.0)
    widget.add_cut(2.5, 4.0)
    assert len(widget.get_cuts()) == 1
    assert widget.get_cuts()[0] == CutMarker(1.0, 4.0)


def test_remove_cut(widget: WaveformWidget) -> None:
    """remove_cut deletes the cut at the given index."""
    widget.add_cut(1.0, 2.0)
    widget.add_cut(3.0, 4.0)
    widget.remove_cut(0)
    assert widget.get_cuts() == [CutMarker(3.0, 4.0)]

    widget.remove_cut(100)  # out of range is a no-op
    assert widget.get_cuts() == [CutMarker(3.0, 4.0)]


def test_clear_cuts(widget: WaveformWidget) -> None:
    """clear_cuts removes all cuts."""
    widget.add_cut(1.0, 2.0)
    widget.add_cut(3.0, 4.0)
    widget.clear_cuts()
    assert widget.get_cuts() == []


def test_suggest_cuts_from_silence(widget: WaveformWidget) -> None:
    """suggest_cuts_from_silence adds cuts for each large silence region."""
    widget.suggest_cuts_from_silence([(0.0, 2.0), (5.0, 8.0)])
    assert widget.get_cuts() == [CutMarker(0.0, 2.0), CutMarker(5.0, 8.0)]


def test_suggest_cuts_from_silence_edge_only(widget: WaveformWidget) -> None:
    """With edge_only, only silences at the start or end of the file are kept."""
    widget.suggest_cuts_from_silence([(0.0, 1.5), (3.0, 6.0), (8.5, 10.0)], edge_only=True)
    assert widget.get_cuts() == [CutMarker(0.0, 1.5), CutMarker(8.5, 10.0)]
