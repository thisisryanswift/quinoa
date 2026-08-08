"""Unit tests for the audio trimmer/analyser utilities."""

import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from quinoa.audio.trimmer import (
    SILENCE_AMPLITUDE_THRESHOLD,
    SilentRegion,
    analyse_audio,
)


def _write_sine_wav(
    path: Path,
    duration: float,
    *,
    freq: float = 440.0,
    sample_rate: int = 48000,
    channels: int = 1,
    sample_width: int = 2,
    amplitude: float = 0.9,
) -> int:
    """Write a sine-wave WAV and return the frame count."""
    n_frames = int(duration * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.setnframes(n_frames)

        max_val = 32767.0
        for i in range(n_frames):
            t = i / sample_rate
            sample = int(max_val * amplitude * math.sin(2 * math.pi * freq * t))
            for _ in range(channels):
                wf.writeframes(struct.pack("<h", sample))
    return n_frames


def _write_constant_wav(
    path: Path,
    n_frames: int,
    *,
    sample_rate: int = 1000,
    channels: int = 1,
    sample_width: int = 2,
    value: int = 10000,
) -> None:
    """Write a constant-value PCM WAV file, supporting 16/24/32-bit."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.setnframes(n_frames)

        if sample_width == 2:
            sample_bytes = struct.pack("<h", value)
        elif sample_width == 4:
            sample_bytes = struct.pack("<i", value)
        elif sample_width == 3:
            sample_bytes = value.to_bytes(3, "little", signed=True)
        else:
            raise ValueError(f"Unsupported sample width: {sample_width}")

        wf.writeframes(sample_bytes * (n_frames * channels))


def _write_silent_wav(
    path: Path,
    duration: float,
    *,
    sample_rate: int = 48000,
    channels: int = 1,
) -> int:
    """Write a silent WAV and return the frame count."""
    n_frames = int(duration * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.setnframes(n_frames)
        wf.writeframes(b"\0" * (n_frames * channels * 2))
    return n_frames


def _write_mixed_wav(
    path: Path,
    segments: list[tuple[float, float]],
    *,
    sample_rate: int = 48000,
    channels: int = 1,
) -> None:
    """Write a WAV made of alternating silent and loud segments."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        n_frames = sum(int(d * sample_rate) for _, d in segments)
        wf.setnframes(n_frames)

        for is_loud, duration in segments:
            segment_frames = int(duration * sample_rate)
            for _ in range(segment_frames):
                sample = int(32767 * 0.9) if is_loud else 0
                for _ in range(channels):
                    wf.writeframes(struct.pack("<h", sample))


def test_analyse_audio_missing_file() -> None:
    """analyse_audio returns None for a missing file."""
    assert analyse_audio(Path("/does/not/exist.wav")) is None


def test_analyse_audio_empty_file(tmp_path: Path) -> None:
    """A completely empty file is treated as a malformed WAV."""
    wav_path = tmp_path / "empty.wav"
    wav_path.write_bytes(b"")
    assert analyse_audio(wav_path) is None


def test_analyse_audio_zero_frames(tmp_path: Path) -> None:
    """A valid WAV with zero frames returns a zero-duration analysis."""
    wav_path = tmp_path / "zero.wav"
    _write_silent_wav(wav_path, 0.0)

    analysis = analyse_audio(wav_path, n_bins=10)
    assert analysis is not None
    assert analysis.duration_seconds == 0.0
    assert analysis.samples_per_channel == 0
    assert analysis.waveform == []


def test_analyse_audio_detects_silence_regions(tmp_path: Path) -> None:
    """analyse_audio reports expected silent regions."""
    wav_path = tmp_path / "mixed.wav"
    # 0.5s silence, 3s tone, 0.5s silence — only the middle tone is non-silent
    _write_mixed_wav(
        wav_path,
        [(False, 0.5), (True, 3.0), (False, 0.5)],
        sample_rate=48000,
    )

    analysis = analyse_audio(
        wav_path,
        n_bins=4,
        silence_threshold=SILENCE_AMPLITUDE_THRESHOLD,
        silence_min_seconds=0.1,
    )
    assert analysis is not None
    assert analysis.sample_rate == 48000
    assert analysis.n_channels == 1
    assert analysis.duration_seconds == pytest.approx(4.0, abs=0.05)
    # The waveform should have at least one high bin (the tone)
    assert max(analysis.waveform) > 0.5
    # We expect two silent regions around the tone
    assert len(analysis.silent_regions) == 2
    # First silence covers [0, ~0.5], second covers [~3.5, 4.0]
    assert analysis.silent_regions[0].start_seconds == pytest.approx(0.0, abs=0.02)
    assert analysis.silent_regions[0].end_seconds == pytest.approx(0.5, abs=0.02)
    assert analysis.silent_regions[1].start_seconds == pytest.approx(3.5, abs=0.02)
    assert analysis.silent_regions[1].end_seconds == pytest.approx(4.0, abs=0.02)


def test_analyse_audio_full_silence_is_one_region(tmp_path: Path) -> None:
    """A completely silent file produces a single silence region."""
    wav_path = tmp_path / "silent.wav"
    _write_silent_wav(wav_path, 1.0)

    analysis = analyse_audio(
        wav_path,
        n_bins=4,
        silence_min_seconds=0.1,
    )
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(1.0, abs=0.05)
    assert len(analysis.silent_regions) == 1
    assert analysis.silent_regions[0].duration == pytest.approx(1.0, abs=0.05)


def test_analyse_audio_mixed_down_to_mono(tmp_path: Path) -> None:
    """Stereo amplitude is mixed down by taking the per-frame maximum."""
    wav_path = tmp_path / "stereo.wav"
    _write_sine_wav(wav_path, 1.0, channels=2)

    analysis = analyse_audio(wav_path, n_bins=4)
    assert analysis is not None
    assert analysis.n_channels == 2
    assert analysis.duration_seconds == pytest.approx(1.0, abs=0.05)
    assert max(analysis.waveform) > 0.5
    assert len(analysis.silent_regions) == 0


def test_analyse_audio_short_file_one_bin_per_frame(tmp_path: Path) -> None:
    """For files shorter than n_bins the waveform has one bin per frame."""
    wav_path = tmp_path / "short.wav"
    sample_rate = 1000
    _write_constant_wav(wav_path, 500, sample_rate=sample_rate, value=20000)

    analysis = analyse_audio(wav_path, n_bins=800)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(0.5, abs=0.01)
    assert len(analysis.waveform) == 500
    assert all(v > 0.5 for v in analysis.waveform)


def test_analyse_audio_long_file_bins_distributed_exactly(tmp_path: Path) -> None:
    """For files longer than n_bins frames are distributed evenly."""
    wav_path = tmp_path / "long.wav"
    sample_rate = 1000
    _write_constant_wav(wav_path, 1000, sample_rate=sample_rate, value=20000)

    analysis = analyse_audio(wav_path, n_bins=800)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(1.0, abs=0.01)
    assert len(analysis.waveform) == 800
    assert all(v > 0.5 for v in analysis.waveform)


def test_analyse_audio_truncated_header_no_trailing_zeros(tmp_path: Path) -> None:
    """A truncated WAV uses the readable frame count for bins, not the header."""
    wav_path = tmp_path / "truncated.wav"
    sample_rate = 1000
    declared_frames = 1000
    actual_frames = 500
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.setnframes(declared_frames)
        wf.writeframes(struct.pack("<h", 20000) * actual_frames)

    analysis = analyse_audio(wav_path, n_bins=800)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(0.5, abs=0.01)
    assert analysis.samples_per_channel == actual_frames
    assert len(analysis.waveform) == actual_frames
    assert all(v > 0.5 for v in analysis.waveform)


def test_analyse_audio_chunk_boundary(tmp_path: Path) -> None:
    """Streaming across chunk boundaries produces the correct bin count."""
    wav_path = tmp_path / "chunk.wav"
    sample_rate = 1000
    # The default chunk size is sample_rate * 5 = 5000 frames, so 6000 frames
    # requires two reads.
    _write_constant_wav(wav_path, 6000, sample_rate=sample_rate, value=20000)

    analysis = analyse_audio(wav_path, n_bins=6000)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(6.0, abs=0.01)
    assert len(analysis.waveform) == 6000
    assert all(v > 0.5 for v in analysis.waveform)


def test_analyse_audio_24_bit_pcm(tmp_path: Path) -> None:
    """24-bit PCM files are analysed correctly."""
    wav_path = tmp_path / "24bit.wav"
    sample_rate = 1000
    _write_constant_wav(
        wav_path,
        1000,
        sample_rate=sample_rate,
        sample_width=3,
        value=4000000,
    )

    analysis = analyse_audio(wav_path, n_bins=800)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(1.0, abs=0.01)
    assert analysis.samples_per_channel == 1000
    assert len(analysis.waveform) == 800
    assert all(v > 0.4 for v in analysis.waveform)


def test_analyse_audio_32_bit_pcm(tmp_path: Path) -> None:
    """32-bit PCM files are analysed correctly."""
    wav_path = tmp_path / "32bit.wav"
    sample_rate = 1000
    _write_constant_wav(
        wav_path,
        1000,
        sample_rate=sample_rate,
        sample_width=4,
        value=1000000000,
    )

    analysis = analyse_audio(wav_path, n_bins=800)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(1.0, abs=0.01)
    assert analysis.samples_per_channel == 1000
    assert len(analysis.waveform) == 800
    assert all(v > 0.4 for v in analysis.waveform)


def test_silent_region_duration() -> None:
    """SilentRegion.duration computes the span in seconds."""
    region = SilentRegion(start_seconds=1.0, end_seconds=3.5)
    assert region.duration == 2.5


def test_compute_trimmed_duration() -> None:
    """compute_trimmed_duration sums kept region spans."""
    from quinoa.audio.trimmer import TrimRegion, compute_trimmed_duration

    regions = [TrimRegion(0.0, 10.0), TrimRegion(20.0, 25.5)]
    assert compute_trimmed_duration(regions) == 15.5

    assert compute_trimmed_duration([]) == 0.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_trim_audio_file_single_region(tmp_path: Path) -> None:
    """trim_audio_file keeps a single region."""
    from quinoa.audio.trimmer import TrimRegion, trim_audio_file

    src = tmp_path / "source.wav"
    out = tmp_path / "trimmed.wav"
    _write_sine_wav(src, 2.0)

    result = trim_audio_file(src, out, [TrimRegion(0.5, 1.5)])
    assert result is True
    assert out.exists()

    analysis = analyse_audio(out)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(1.0, abs=0.1)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_trim_audio_file_concat_regions(tmp_path: Path) -> None:
    """trim_audio_file concatenates multiple keep regions."""
    from quinoa.audio.trimmer import TrimRegion, trim_audio_file

    src = tmp_path / "source.wav"
    out = tmp_path / "trimmed.wav"
    _write_sine_wav(src, 4.0)

    result = trim_audio_file(src, out, [TrimRegion(0.0, 1.0), TrimRegion(2.5, 3.5)])
    assert result is True

    analysis = analyse_audio(out)
    assert analysis is not None
    assert analysis.duration_seconds == pytest.approx(2.0, abs=0.1)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_trim_recording(tmp_path: Path) -> None:
    """trim_recording trims all audio files in a directory and backs them up."""
    from quinoa.audio.trimmer import TrimRegion, trim_recording

    recording_dir = tmp_path / "recording"
    recording_dir.mkdir()
    _write_sine_wav(recording_dir / "microphone.wav", 2.0)
    _write_sine_wav(recording_dir / "system.wav", 2.0)

    result = trim_recording(recording_dir, [TrimRegion(0.5, 1.5)], backup=True)
    assert result is True

    for name in ("microphone.wav", "system.wav"):
        trimmed = recording_dir / name
        backup = recording_dir / f"{name}.pretrim"
        assert trimmed.exists()
        assert backup.exists()

        analysis = analyse_audio(trimmed)
        assert analysis is not None
        assert analysis.duration_seconds == pytest.approx(1.0, abs=0.1)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_trim_recording_partial_failure(tmp_path: Path) -> None:
    """trim_recording returns False if any existing track fails to trim."""
    from quinoa.audio.trimmer import TrimRegion, trim_recording

    recording_dir = tmp_path / "recording"
    recording_dir.mkdir()
    _write_sine_wav(recording_dir / "microphone.wav", 2.0)
    _write_sine_wav(recording_dir / "mixed_stereo.wav", 2.0)
    # Corrupt the system track so ffmpeg cannot decode it.
    (recording_dir / "system.wav").write_bytes(b"not a wav file")

    result = trim_recording(recording_dir, [TrimRegion(0.5, 1.5)], backup=True)
    assert result is False

    # The valid tracks were still trimmed.
    for name in ("microphone.wav", "mixed_stereo.wav"):
        trimmed = recording_dir / name
        backup = recording_dir / f"{name}.pretrim"
        assert trimmed.exists()
        assert backup.exists()

        analysis = analyse_audio(trimmed)
        assert analysis is not None
        assert analysis.duration_seconds == pytest.approx(1.0, abs=0.1)

    # The corrupt track is preserved.
    assert (recording_dir / "system.wav").exists()
    assert not (recording_dir / "system.wav.pretrim").exists()
