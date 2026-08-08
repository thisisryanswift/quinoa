import shutil
import struct
import subprocess
import threading
import wave
from pathlib import Path

import pytest

from quinoa.audio.converter import compress_audio, mix_recording_audio
from quinoa.audio.mixer import MixCancelledError, create_stereo_mix

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)

SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2


def _write_wav(path: Path, duration: float, channels: int, channel_values: list[int]) -> None:
    """Write a PCM WAV file filled with constant *channel_values*."""
    nframes = int(round(duration * SAMPLE_RATE))
    fmt = "<" + "h" * channels
    frame = struct.pack(fmt, *channel_values[:channels])
    data = frame * nframes

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data)


def _read_wav(path: Path) -> tuple[int, int, list[tuple[int, ...]]]:
    """Return (channels, nframes, frames) for a WAV file."""
    with wave.open(str(path), "rb") as wf:
        nchannels = wf.getnchannels()
        nframes = wf.getnframes()
        data = wf.readframes(nframes)

    fmt = "<" + "h" * nchannels
    stride = nchannels * SAMPLE_WIDTH
    frames = [
        struct.unpack(fmt, data[i : i + stride])
        for i in range(0, len(data), stride)
    ]
    return nchannels, nframes, frames


def _encode(path: Path, format: str) -> Path:
    """Encode a WAV file to FLAC or Opus, returning the new path."""
    output = path.with_suffix(f".{format}")
    codec = (
        ["-c:a", "libopus", "-b:a", "64k"]
        if format == "opus"
        else ["-c:a", format]
    )
    cmd = ["ffmpeg", "-y", "-i", str(path), *codec, str(output)]
    subprocess.run(cmd, check=True, capture_output=True)
    return output


def test_create_stereo_mix_exact_longest_frames(tmp_path: Path) -> None:
    mic = tmp_path / "mic.wav"
    sys = tmp_path / "sys.wav"
    out = tmp_path / "mixed.wav"
    _write_wav(mic, 0.1, 1, [1000])
    _write_wav(sys, 0.15, 1, [2000])

    create_stereo_mix(mic, sys, out)

    nchannels, nframes, _ = _read_wav(out)
    assert nchannels == 2
    assert nframes == int(round(0.15 * SAMPLE_RATE))


def test_create_stereo_mix_mic_left_sys_right(tmp_path: Path) -> None:
    mic = tmp_path / "mic.wav"
    sys = tmp_path / "sys.wav"
    out = tmp_path / "mixed.wav"
    _write_wav(mic, 0.1, 1, [3000])
    _write_wav(sys, 0.1, 1, [-3000])

    create_stereo_mix(mic, sys, out)

    _, _, frames = _read_wav(out)
    for left, right in frames:
        assert left == 3000
        assert right == -3000


def test_create_stereo_mix_multi_channel_downmix(tmp_path: Path) -> None:
    mic = tmp_path / "mic.wav"
    sys = tmp_path / "sys.wav"
    out = tmp_path / "mixed.wav"
    _write_wav(mic, 0.1, 4, [1000, 2000, 3000, 4000])
    _write_wav(sys, 0.1, 2, [500, 1500])

    create_stereo_mix(mic, sys, out)

    _, _, frames = _read_wav(out)
    for left, right in frames:
        assert left == 2500
        assert right == 1000


def test_create_stereo_mix_flac_opus_inputs(tmp_path: Path) -> None:
    mic_wav = tmp_path / "mic.wav"
    sys_wav = tmp_path / "sys.wav"
    _write_wav(mic_wav, 0.12, 1, [4000])
    _write_wav(sys_wav, 0.15, 1, [-4000])

    mic_flac = _encode(mic_wav, "flac")
    sys_opus = _encode(sys_wav, "opus")

    out = tmp_path / "mixed.wav"
    create_stereo_mix(mic_flac, sys_opus, out)

    nchannels, nframes, frames = _read_wav(out)
    assert nchannels == 2
    # Opus may add a small frame of encoder padding; allow one 20ms Opus frame.
    expected = int(round(0.15 * SAMPLE_RATE))
    assert abs(nframes - expected) <= 960
    left, right = frames[100]
    assert left == 4000
    # Opus is lossy, so allow a small tolerance on the decoded system channel.
    assert abs(right + 4000) <= 200


def test_create_stereo_mix_cleans_temp_on_failure(tmp_path: Path) -> None:
    mic = tmp_path / "mic.wav"
    sys = tmp_path / "sys.wav"
    _write_wav(mic, 0.1, 1, [1000])
    _write_wav(sys, 0.1, 1, [2000])

    # Force the atomic replace to fail by using an existing directory as output.
    bad_output = tmp_path / "blockdir"
    bad_output.mkdir()

    with pytest.raises(RuntimeError):
        create_stereo_mix(mic, sys, bad_output)

    assert not list(tmp_path.glob("*.tmp.*"))


def test_compress_audio_flac_and_opus(tmp_path: Path) -> None:
    wav = tmp_path / "audio.wav"
    _write_wav(wav, 0.2, 1, [5000])

    for fmt in ("flac", "opus"):
        out = compress_audio(wav, fmt)
        assert out is not None
        assert out.exists()
        assert out.suffix == f".{fmt}"
        assert not (tmp_path / f"audio.tmp.{fmt}").exists()

        decoded = tmp_path / f"decoded_{fmt}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out), str(decoded)],
            check=True,
            capture_output=True,
        )
        _, nframes, _ = _read_wav(decoded)
        expected = int(round(0.2 * SAMPLE_RATE))
        assert expected <= nframes <= expected + 960


def test_compress_audio_cleans_temp_on_failure(tmp_path: Path) -> None:
    wav = tmp_path / "audio.wav"
    _write_wav(wav, 0.1, 1, [1000])

    # Block the computed output path with a directory of the same name.
    block = tmp_path / "audio.flac"
    block.mkdir()

    assert compress_audio(wav, "flac") is None
    assert not (tmp_path / "audio.tmp.flac").exists()


def test_mix_recording_audio_stereo(tmp_path: Path) -> None:
    rec = tmp_path / "recording"
    rec.mkdir()
    mic = rec / "microphone.wav"
    sys = rec / "system.wav"
    _write_wav(mic, 0.1, 1, [4000])
    _write_wav(sys, 0.1, 1, [-4000])

    out = mix_recording_audio(rec)
    assert out is not None
    assert out.name == "mixed_stereo.wav"

    _, _, frames = _read_wav(out)
    for left, right in frames:
        assert left == 4000
        assert right == -4000


def test_mix_recording_audio_mic_only(tmp_path: Path) -> None:
    rec = tmp_path / "recording"
    rec.mkdir()
    mic = rec / "microphone.wav"
    _write_wav(mic, 0.1, 1, [1234])

    out = mix_recording_audio(rec)
    assert out is not None
    assert out.name == "mixed_stereo.wav"

    nchannels, nframes, frames = _read_wav(out)
    assert nchannels == 1
    assert nframes == int(round(0.1 * SAMPLE_RATE))
    assert all(frame[0] == 1234 for frame in frames)


def test_mix_recording_audio_mic_only_cleans_temp_on_failure(tmp_path: Path) -> None:
    rec = tmp_path / "recording"
    rec.mkdir()
    mic = rec / "microphone.wav"
    _write_wav(mic, 0.1, 1, [1234])

    # Block the target path so the atomic replace cannot succeed.
    block = rec / "mixed_stereo.wav"
    block.mkdir()

    assert mix_recording_audio(rec) is None
    assert not list(rec.glob("*.tmp.*"))


def test_mix_recording_audio_missing_mic(tmp_path: Path) -> None:
    rec = tmp_path / "recording"
    rec.mkdir()
    sys = rec / "system.wav"
    _write_wav(sys, 0.1, 1, [1000])

    assert mix_recording_audio(rec) is None


def test_create_stereo_mix_three_channel_downmix(tmp_path: Path) -> None:
    mic = tmp_path / "mic.wav"
    sys = tmp_path / "sys.wav"
    out = tmp_path / "mixed.wav"
    _write_wav(mic, 0.1, 3, [1000, 2000, 3000])
    _write_wav(sys, 0.1, 1, [4000])

    create_stereo_mix(mic, sys, out)

    _, _, frames = _read_wav(out)
    for left, right in frames:
        assert left == 2000
        assert right == 4000


def test_create_stereo_mix_missing_ffprobe_names_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_which(name: str) -> str | None:
        return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

    monkeypatch.setattr(shutil, "which", fake_which)

    mic = tmp_path / "mic.wav"
    sys = tmp_path / "sys.wav"
    out = tmp_path / "mixed.wav"
    _write_wav(mic, 0.1, 1, [1000])
    _write_wav(sys, 0.1, 1, [1000])

    with pytest.raises(RuntimeError, match="ffprobe"):
        create_stereo_mix(mic, sys, out)


def test_create_stereo_mix_cancellation_includes_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mic = tmp_path / "mic.wav"
    sys = tmp_path / "sys.wav"
    out = tmp_path / "mixed.wav"
    _write_wav(mic, 0.1, 1, [1000])
    _write_wav(sys, 0.1, 1, [1000])

    class FakePopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._killed = False
            self.stderr = None

        def poll(self) -> int | None:
            return 0 if self._killed else None

        def kill(self) -> None:
            self._killed = True

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(MixCancelledError, match="Stereo mix cancelled"):
        create_stereo_mix(mic, sys, out, cancellation_event=cancel)


def test_compress_audio_ignores_underreported_ffprobe_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "audio.wav"
    _write_wav(wav, 0.2, 1, [5000])

    import quinoa.audio.converter as converter

    real_ffprobe = converter._ffprobe

    def fake_ffprobe(path: Path) -> dict[str, object]:
        info = real_ffprobe(path)
        info["duration"] = "0.02"
        return info

    monkeypatch.setattr(converter, "_ffprobe", fake_ffprobe)

    out = compress_audio(wav, "flac")
    assert out is not None
    assert out.exists()

    decoded = tmp_path / "decoded.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), str(decoded)],
        check=True,
        capture_output=True,
    )
    _, nframes, _ = _read_wav(decoded)
    expected = int(round(0.2 * SAMPLE_RATE))
    # The old -t 0.02 behaviour would produce ~960 frames; the new code must
    # keep the full duration.
    assert expected <= nframes <= expected + 960
    assert nframes >= expected // 2


def test_compress_audio_ignores_unavailable_ffprobe_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wav = tmp_path / "audio.wav"
    _write_wav(wav, 0.1, 1, [1000])

    import quinoa.audio.converter as converter

    def fake_ffprobe(path: Path) -> dict[str, object]:
        return {
            "streams": [{"channels": 1, "sample_rate": SAMPLE_RATE}],
            "format": {},
        }

    monkeypatch.setattr(converter, "_ffprobe", fake_ffprobe)

    out = compress_audio(wav, "flac")
    assert out is not None
    assert out.exists()

    decoded = tmp_path / "decoded.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), str(decoded)],
        check=True,
        capture_output=True,
    )
    _, nframes, _ = _read_wav(decoded)
    assert nframes == int(round(0.1 * SAMPLE_RATE))
