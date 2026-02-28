"""Audio trimming and analysis utilities.

Provides waveform extraction, silence detection, and trimming for recordings.
Uses the wave stdlib module for analysis and ffmpeg for trimming operations.
"""

import logging
import shutil
import struct
import subprocess
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("quinoa")

# Silence detection defaults
SILENCE_AMPLITUDE_THRESHOLD = 0.01  # Fraction of max amplitude
SILENCE_MIN_DURATION_SECONDS = 2.0  # Min seconds to count as a silent region


@dataclass
class SilentRegion:
    """A region of silence in an audio file."""

    start_seconds: float
    end_seconds: float

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass
class AudioAnalysis:
    """Analysis results for an audio file."""

    duration_seconds: float
    sample_rate: int
    n_channels: int
    samples_per_channel: int
    # Downsampled peak amplitudes, normalised to 0.0-1.0.
    # One value per visual "bin" (the number of bins is caller-controlled).
    waveform: list[float] = field(default_factory=list)
    silent_regions: list[SilentRegion] = field(default_factory=list)


def analyse_audio(
    path: str | Path,
    n_bins: int = 800,
    silence_threshold: float = SILENCE_AMPLITUDE_THRESHOLD,
    silence_min_seconds: float = SILENCE_MIN_DURATION_SECONDS,
) -> AudioAnalysis | None:
    """Analyse a WAV or FLAC file, returning waveform data and silence regions.

    For FLAC files, this decodes to a temporary WAV via ffmpeg first.

    Args:
        path: Path to a WAV or FLAC audio file.
        n_bins: Number of waveform bins to return (controls visual resolution).
        silence_threshold: Amplitude fraction (0-1) below which audio is "silent".
        silence_min_seconds: Minimum duration for a silence region to be reported.

    Returns:
        AudioAnalysis with waveform and silence data, or None on error.
    """
    path = Path(path)
    if not path.exists():
        logger.warning("Audio file not found: %s", path)
        return None

    # For FLAC, decode to temporary WAV first
    tmp_wav: Path | None = None
    wav_path = path
    if path.suffix.lower() == ".flac":
        tmp_wav = path.with_suffix(".tmp_analysis.wav")
        if not _decode_flac_to_wav(path, tmp_wav):
            return None
        wav_path = tmp_wav

    try:
        return _analyse_wav(wav_path, n_bins, silence_threshold, silence_min_seconds)
    finally:
        if tmp_wav and tmp_wav.exists():
            tmp_wav.unlink()


def _decode_flac_to_wav(flac_path: Path, wav_path: Path) -> bool:
    """Decode a FLAC file to WAV using ffmpeg."""
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg not found in PATH")
        return False
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(flac_path), "-c:a", "pcm_s16le", str(wav_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("ffmpeg decode failed: %s", result.stderr)
            return False
        return wav_path.exists()
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out decoding %s", flac_path)
        return False
    except Exception as e:
        logger.error("Failed to decode FLAC: %s", e)
        return False


def _analyse_wav(
    wav_path: Path,
    n_bins: int,
    silence_threshold: float,
    silence_min_seconds: float,
) -> AudioAnalysis | None:
    """Analyse a WAV file for waveform and silence."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            sample_width = wf.getsampwidth()

            if n_frames == 0:
                return AudioAnalysis(
                    duration_seconds=0.0,
                    sample_rate=sample_rate,
                    n_channels=n_channels,
                    samples_per_channel=0,
                )

            duration = n_frames / sample_rate

            # Read all frames
            raw = wf.readframes(n_frames)
    except wave.Error as e:
        logger.error("Failed to read WAV file %s: %s", wav_path, e)
        return None

    # Unpack samples (support 16-bit and 24-bit)
    samples: Sequence[int]
    if sample_width == 2:
        fmt = f"<{n_frames * n_channels}h"
        samples = struct.unpack(fmt, raw)
        max_val = 32767.0
    elif sample_width == 3:
        # 24-bit: unpack manually
        unpacked: list[int] = []
        for i in range(0, len(raw), 3):
            val = int.from_bytes(raw[i : i + 3], byteorder="little", signed=True)
            unpacked.append(val)
        samples = unpacked
        max_val = 8388607.0
    elif sample_width == 4:
        fmt = f"<{n_frames * n_channels}i"
        samples = struct.unpack(fmt, raw)
        max_val = 2147483647.0
    else:
        logger.error("Unsupported sample width: %d", sample_width)
        return None

    # Mix down to mono by taking max absolute amplitude across channels per frame
    if n_channels > 1:
        mono: list[float] = []
        for i in range(0, len(samples), n_channels):
            frame_samples = samples[i : i + n_channels]
            mono.append(max(abs(s) for s in frame_samples) / max_val)
        amplitudes = mono
    else:
        amplitudes = [abs(s) / max_val for s in samples]

    # Build waveform bins (peak amplitude per bin)
    frames_per_bin = max(1, len(amplitudes) // n_bins)
    waveform: list[float] = []
    for i in range(0, len(amplitudes), frames_per_bin):
        chunk = amplitudes[i : i + frames_per_bin]
        waveform.append(max(chunk) if chunk else 0.0)

    # Trim to requested bin count (last bin may be partial)
    waveform = waveform[:n_bins]

    # Detect silent regions from the amplitude data
    silent_regions = _detect_silence(
        amplitudes, sample_rate, silence_threshold, silence_min_seconds
    )

    return AudioAnalysis(
        duration_seconds=duration,
        sample_rate=sample_rate,
        n_channels=n_channels,
        samples_per_channel=n_frames,
        waveform=waveform,
        silent_regions=silent_regions,
    )


def _detect_silence(
    amplitudes: list[float],
    sample_rate: int,
    threshold: float,
    min_duration_seconds: float,
) -> list[SilentRegion]:
    """Detect silent regions in amplitude data."""
    regions: list[SilentRegion] = []
    silence_start: int | None = None

    for i, amp in enumerate(amplitudes):
        if amp < threshold:
            if silence_start is None:
                silence_start = i
        else:
            if silence_start is not None:
                duration_samples = i - silence_start
                duration_seconds = duration_samples / sample_rate
                if duration_seconds >= min_duration_seconds:
                    regions.append(
                        SilentRegion(
                            start_seconds=silence_start / sample_rate,
                            end_seconds=i / sample_rate,
                        )
                    )
                silence_start = None

    # Handle silence extending to end of file
    if silence_start is not None:
        duration_samples = len(amplitudes) - silence_start
        duration_seconds = duration_samples / sample_rate
        if duration_seconds >= min_duration_seconds:
            regions.append(
                SilentRegion(
                    start_seconds=silence_start / sample_rate,
                    end_seconds=len(amplitudes) / sample_rate,
                )
            )

    return regions


@dataclass
class TrimRegion:
    """A region to keep (not cut) in the audio."""

    start_seconds: float
    end_seconds: float


def trim_audio_file(
    input_path: str | Path,
    output_path: str | Path,
    keep_regions: list[TrimRegion],
) -> bool:
    """Trim an audio file, keeping only the specified regions.

    Uses ffmpeg to extract and concatenate the kept regions.
    Works with both WAV and FLAC files.

    Args:
        input_path: Source audio file.
        output_path: Destination path for trimmed audio.
        keep_regions: List of time regions to keep, in order.

    Returns:
        True if successful.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return False

    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg not found in PATH")
        return False

    if not keep_regions:
        logger.error("No regions to keep")
        return False

    # Single region: simple trim
    if len(keep_regions) == 1:
        region = keep_regions[0]
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-ss",
            f"{region.start_seconds:.6f}",
            "-to",
            f"{region.end_seconds:.6f}",
            "-c",
            "copy",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.error("ffmpeg trim failed: %s", result.stderr)
                return False
            return output_path.exists()
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.error("ffmpeg trim error: %s", e)
            return False

    # Multiple regions: use ffmpeg concat filter
    # Build a complex filter that selects and concatenates segments
    filter_parts: list[str] = []
    concat_inputs: list[str] = []
    for i, region in enumerate(keep_regions):
        start = region.start_seconds
        end = region.end_seconds
        filter_parts.append(
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[a{i}]")

    filter_complex = ";".join(filter_parts)
    filter_complex += f";{''.join(concat_inputs)}concat=n={len(keep_regions)}:v=0:a=1[out]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("ffmpeg concat trim failed: %s", result.stderr)
            return False
        return output_path.exists()
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.error("ffmpeg concat trim error: %s", e)
        return False


def trim_recording(
    recording_dir: str | Path,
    keep_regions: list[TrimRegion],
    backup: bool = True,
) -> bool:
    """Trim all audio files in a recording directory.

    Trims microphone.wav, system.wav, and mixed_stereo.wav (and their FLAC
    counterparts) using the same regions. Creates backups with .pretrim suffix.

    Args:
        recording_dir: Directory containing the recording files.
        keep_regions: Regions to keep.
        backup: If True, rename originals with .pretrim suffix before overwriting.

    Returns:
        True if all files were trimmed successfully.
    """
    recording_dir = Path(recording_dir)
    if not recording_dir.is_dir():
        logger.error("Recording directory not found: %s", recording_dir)
        return False

    audio_files = [
        "microphone.wav",
        "system.wav",
        "mixed_stereo.wav",
        "microphone.flac",
        "system.flac",
        "mixed_stereo.flac",
    ]

    trimmed_any = False
    for filename in audio_files:
        file_path = recording_dir / filename
        if not file_path.exists():
            continue

        # Create backup
        if backup:
            backup_path = file_path.with_suffix(file_path.suffix + ".pretrim")
            if not backup_path.exists():
                shutil.copy2(file_path, backup_path)
                logger.info("Backed up %s -> %s", filename, backup_path.name)

        # Trim to a temp file, then replace the original
        tmp_path = file_path.with_suffix(file_path.suffix + ".trimming")
        try:
            if trim_audio_file(file_path, tmp_path, keep_regions):
                tmp_path.replace(file_path)
                trimmed_any = True
                logger.info("Trimmed %s", filename)
            else:
                if tmp_path.exists():
                    tmp_path.unlink()
                logger.warning("Failed to trim %s, original preserved", filename)
        except Exception as e:
            logger.error("Error trimming %s: %s", filename, e)
            if tmp_path.exists():
                tmp_path.unlink()

    return trimmed_any


def compute_trimmed_duration(keep_regions: list[TrimRegion]) -> float:
    """Compute the total duration of kept regions."""
    return sum(r.end_seconds - r.start_seconds for r in keep_regions)
