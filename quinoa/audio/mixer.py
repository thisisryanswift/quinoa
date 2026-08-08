"""Real-ffmpeg stereo mix utilities."""

import contextlib
import io
import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import cast

from quinoa.constants import DEFAULT_SAMPLE_RATE

logger = logging.getLogger("quinoa")

_TARGET_SAMPLE_RATE = DEFAULT_SAMPLE_RATE


class MixCancelledError(Exception):
    """Raised when the stereo mix is cancelled before completion."""

    pass


def _ffprobe(path: Path) -> dict[str, object]:
    """Return audio stream metadata for *path* as a dict.

    Raises RuntimeError if ffprobe fails and ValueError if there is no
    audio stream.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=channels,duration,sample_rate:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe returned invalid JSON for {path}: {e}") from e

    streams = data.get("streams", [])
    if not streams:
        raise ValueError(f"No audio stream found in {path}")

    info = dict(streams[0])
    format_info = data.get("format", {})
    info["format_duration"] = format_info.get("duration") if isinstance(format_info, dict) else None
    return info


def _duration_to_samples(info: dict[str, object]) -> int:
    """Convert ffprobe metadata to a sample count at the target sample rate."""
    duration_value = info.get("duration") or info.get("format_duration")
    if duration_value in (None, "N/A"):
        duration_value = info.get("format_duration")
    sample_rate_value = info.get("sample_rate")
    if not duration_value or duration_value == "N/A" or not sample_rate_value:
        raise ValueError("Could not determine input duration or sample rate")

    try:
        duration = float(str(duration_value))
        sample_rate = int(str(sample_rate_value))
    except ValueError as e:
        raise ValueError(f"Invalid ffprobe duration/sample_rate: {e}") from e

    if sample_rate <= 0:
        raise ValueError(f"Invalid sample rate {sample_rate}")

    return int(round(duration * _TARGET_SAMPLE_RATE))


def _mono_pan_expression(channels: int) -> str:
    """Build a pan expression that averages all input channels to mono."""
    if channels <= 0:
        raise ValueError("Channel count must be positive")
    weight = 1.0 / channels
    terms = [f"{weight:.17g}*c{i}" for i in range(channels)]
    return "c0=" + "+".join(terms)


def _temp_output_path(path: Path) -> Path:
    """Return a sibling temp path that retains a ``.wav`` extension."""
    return path.with_name(f"{path.stem}.tmp.wav")


_STDERR_LIMIT = 32768


def _start_stderr_reader(process: subprocess.Popen) -> tuple[threading.Thread, bytearray]:
    """Start a bounded reader for *process*'s stderr.

    Returns a daemon thread and a bytearray that receives up to
    ``_STDERR_LIMIT`` bytes of the most recent stderr output.  Reading in a
    dedicated thread prevents the child from blocking on a full stderr pipe.
    """
    stderr_buffer = bytearray()

    def _reader() -> None:
        stderr = process.stderr
        if stderr is None:
            return
        stderr = cast(io.BufferedReader, stderr)
        while True:
            try:
                chunk = stderr.read1(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            stderr_buffer.extend(chunk)
            if len(stderr_buffer) > _STDERR_LIMIT:
                del stderr_buffer[:-_STDERR_LIMIT]

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread, stderr_buffer


def _stderr_text(stderr_buffer: bytearray, limit: int = 2048) -> str:
    """Decode and truncate *stderr_buffer* for error messages."""
    text = stderr_buffer.decode("utf-8", errors="replace").strip()
    if len(text) > limit:
        text = f"...{text[-limit:]}"
    return text


def create_stereo_mix(
    mic_path: str | Path,
    sys_path: str | Path,
    output_path: str | Path,
    timeout: int = 300,
    cancellation_event: threading.Event | None = None,
) -> str:
    """Merge two audio inputs into a stereo WAV using ffmpeg.

    Left channel contains the microphone input and the right channel contains
    the system input.  Each input is downmixed to mono (preserving all
    channels, not just channel 0) and padded to the exact duration of the
    longest input.  The output is written to a temporary ``.tmp.wav`` file and
    atomically moved into place so callers never see a partially-written file.

    Args:
        timeout: Maximum total time in seconds to wait for ffmpeg.
        cancellation_event: Optional ``threading.Event`` that can abort the
            mix while ffmpeg is running.

    Raises:
        MixCancelledError: If ``cancellation_event`` is set before completion.
        subprocess.TimeoutExpired: If ffmpeg does not finish within ``timeout``.
    """
    if cancellation_event and cancellation_event.is_set():
        raise MixCancelledError("Stereo mix cancelled before starting")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH. Please install ffmpeg for audio mixing.")
    if not shutil.which("ffprobe"):
        raise RuntimeError(
            "ffprobe not found in PATH. Please install ffmpeg (which includes ffprobe) for audio mixing."
        )

    mic_path = Path(mic_path)
    sys_path = Path(sys_path)
    output_path = Path(output_path)

    if not mic_path.exists() or not sys_path.exists():
        raise FileNotFoundError(f"Input audio files not found: {mic_path} or {sys_path}")

    mic_info = _ffprobe(mic_path)
    sys_info = _ffprobe(sys_path)

    mic_samples = _duration_to_samples(mic_info)
    sys_samples = _duration_to_samples(sys_info)
    max_samples = max(mic_samples, sys_samples)
    if max_samples <= 0:
        raise ValueError("At least one input audio file must have a non-zero duration")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _temp_output_path(output_path)

    mic_channels = int(str(mic_info.get("channels", 0)))
    sys_channels = int(str(sys_info.get("channels", 0)))
    mic_pan = _mono_pan_expression(mic_channels)
    sys_pan = _mono_pan_expression(sys_channels)

    filter_complex = (
        f"[0:a]aresample={_TARGET_SAMPLE_RATE},pan=mono|{mic_pan}[mic];"
        f"[1:a]aresample={_TARGET_SAMPLE_RATE},pan=mono|{sys_pan}[sys];"
        f"[mic]apad=whole_len={max_samples}[mic_padded];"
        f"[sys]apad=whole_len={max_samples}[sys_padded];"
        f"[mic_padded][sys_padded]join=inputs=2:channel_layout=stereo[aout]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(mic_path),
        "-i",
        str(sys_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[aout]",
        str(tmp_path),
    ]

    success = False
    process: subprocess.Popen | None = None
    stderr_thread: threading.Thread | None = None
    stderr_buffer = bytearray()
    deadline = time.monotonic() + timeout
    try:
        logger.debug("Running ffmpeg stereo mix: %s", " ".join(cmd))
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            raise RuntimeError(f"ffmpeg stereo mix failed to start: {e}") from e

        stderr_thread, stderr_buffer = _start_stderr_reader(process)

        while process.poll() is None:
            if cancellation_event and cancellation_event.is_set():
                logger.info("Cancelling stereo mix for %s", output_path)
                process.kill()
                process.wait()
                if stderr_thread is not None:
                    stderr_thread.join(timeout=1.0)
                raise MixCancelledError(
                    f"Stereo mix cancelled for {output_path}; "
                    f"ffmpeg stderr: {_stderr_text(stderr_buffer)}"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("Stereo mix timed out for %s", output_path)
                process.kill()
                process.wait()
                if stderr_thread is not None:
                    stderr_thread.join(timeout=1.0)
                raise subprocess.TimeoutExpired(
                    cmd,
                    timeout,
                    output=None,
                    stderr=_stderr_text(stderr_buffer).encode("utf-8", errors="replace"),
                )

            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=min(0.25, remaining))

        if stderr_thread is not None:
            stderr_thread.join(timeout=1.0)

        returncode = process.returncode
        process = None
        if returncode != 0:
            raise RuntimeError(
                f"ffmpeg stereo mix failed with exit code {returncode}: "
                f"{_stderr_text(stderr_buffer)}"
            )

        out_info = _ffprobe(tmp_path)
        channels = int(str(out_info.get("channels", 0)))
        sample_rate = int(str(out_info.get("sample_rate", 0)))
        if channels != 2:
            raise RuntimeError(f"Expected stereo output, got {channels} channels")
        if sample_rate != _TARGET_SAMPLE_RATE:
            raise RuntimeError(
                f"Expected output sample rate {_TARGET_SAMPLE_RATE}, got {sample_rate}"
            )

        out_samples = _duration_to_samples(out_info)
        if out_samples != max_samples:
            raise RuntimeError(
                f"Output duration mismatch: {out_samples} samples, expected {max_samples}"
            )

        try:
            tmp_path.replace(output_path)
        except OSError as e:
            raise RuntimeError(f"Failed to move mixed output to {output_path}: {e}") from e

        success = True
        return str(output_path)
    finally:
        if process is not None:
            with contextlib.suppress(Exception):
                process.kill()
                process.wait()
        if stderr_thread is not None:
            with contextlib.suppress(Exception):
                stderr_thread.join(timeout=1.0)
        if not success:
            tmp_path.unlink(missing_ok=True)
