"""Audio trimming and analysis utilities.

Provides waveform extraction, silence detection, and trimming for recordings.
Uses the wave stdlib module for analysis and ffmpeg for trimming operations.
"""

import logging
import shutil
import struct
import subprocess
import wave
from collections.abc import Iterator
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
            errors="replace",
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("ffmpeg decode failed: %s", result.stderr)
            return False
        return wav_path.exists()
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out decoding %s", flac_path)
        return False
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
        logger.error("Failed to decode FLAC: %s", e)
        return False


def _count_wav_frames(wf: wave.Wave_read, bytes_per_frame: int, chunk_frames: int) -> int:
    """Stream through an open WAV file and count the readable frames."""
    count = 0
    while True:
        raw = wf.readframes(chunk_frames)
        if not raw:
            break
        frame_bytes = len(raw) - (len(raw) % bytes_per_frame)
        count += frame_bytes // bytes_per_frame
    return count


def _iter_samples(raw: bytes, sample_width: int, frame_bytes: int) -> Iterator[int]:
    """Yield signed PCM samples from a raw little-endian byte buffer."""
    if sample_width == 2:
        return (v[0] for v in struct.iter_unpack("<h", raw[:frame_bytes]))
    if sample_width == 4:
        return (v[0] for v in struct.iter_unpack("<i", raw[:frame_bytes]))
    # 24-bit: unpack manually
    return (
        int.from_bytes(raw[i : i + 3], "little", signed=True)
        for i in range(0, frame_bytes, 3)
    )


def _analyse_wav(
    wav_path: Path,
    n_bins: int,
    silence_threshold: float,
    silence_min_seconds: float,
) -> AudioAnalysis | None:
    """Analyse a WAV file for waveform and silence by streaming frames."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            header_n_frames = wf.getnframes()
            sample_width = wf.getsampwidth()
    except (OSError, EOFError, wave.Error, struct.error, ValueError) as e:
        logger.error("Failed to open WAV file %s: %s", wav_path, e)
        return None

    if sample_rate <= 0 or n_channels <= 0 or sample_width <= 0:
        logger.error("Invalid WAV metadata in %s", wav_path)
        return None

    if sample_width == 2:
        max_val = 32767.0
    elif sample_width == 3:
        max_val = 8388607.0
    elif sample_width == 4:
        max_val = 2147483647.0
    else:
        logger.error("Unsupported sample width: %d", sample_width)
        return None

    if n_bins <= 0:
        logger.error("n_bins must be positive, got %d", n_bins)
        return None

    if header_n_frames == 0:
        return AudioAnalysis(
            duration_seconds=0.0,
            sample_rate=sample_rate,
            n_channels=n_channels,
            samples_per_channel=0,
        )

    bytes_per_frame = sample_width * n_channels
    chunk_frames = max(1, sample_rate * 5)

    # First pass: count the frames that are actually readable. This stays
    # memory-bounded because we read and discard chunks, and it lets us place
    # bins correctly when the header over-declares frames (truncated files).
    try:
        with wave.open(str(wav_path), "rb") as wf:
            actual_n_frames = _count_wav_frames(wf, bytes_per_frame, chunk_frames)
    except (OSError, EOFError, wave.Error, struct.error, ValueError) as e:
        logger.error("Failed to read WAV frames from %s: %s", wav_path, e)
        return None

    if actual_n_frames == 0:
        return AudioAnalysis(
            duration_seconds=0.0,
            sample_rate=sample_rate,
            n_channels=n_channels,
            samples_per_channel=0,
        )

    if header_n_frames != actual_n_frames:
        logger.warning(
            "WAV header declared %d frames but only %d were readable in %s",
            header_n_frames,
            actual_n_frames,
            wav_path,
        )

    # For short files we return one bin per frame so the waveform is not padded
    # with trailing zero bins. For longer files we distribute frames evenly
    # across the requested number of bins.
    output_bins = min(n_bins, actual_n_frames)
    bin_peaks = [0.0] * output_bins
    silent_regions: list[SilentRegion] = []
    silence_start: int | None = None

    # Second pass: compute bin peaks and detect silent regions.
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frame_index = 0
            while True:
                raw = wf.readframes(chunk_frames)
                if not raw:
                    break

                frame_bytes = len(raw) - (len(raw) % bytes_per_frame)
                n_frames_in_chunk = frame_bytes // bytes_per_frame
                sample_iter = _iter_samples(raw, sample_width, frame_bytes)

                for _ in range(n_frames_in_chunk):
                    frame_peak = 0
                    for _ in range(n_channels):
                        sample = abs(next(sample_iter))
                        if sample > frame_peak:
                            frame_peak = sample
                    amp = frame_peak / max_val

                    if output_bins > 0:
                        bin_index = min(
                            output_bins - 1,
                            frame_index * output_bins // actual_n_frames,
                        )
                        if amp > bin_peaks[bin_index]:
                            bin_peaks[bin_index] = amp

                    if amp < silence_threshold:
                        if silence_start is None:
                            silence_start = frame_index
                    else:
                        if silence_start is not None:
                            silent_duration = (frame_index - silence_start) / sample_rate
                            if silent_duration >= silence_min_seconds:
                                silent_regions.append(
                                    SilentRegion(
                                        silence_start / sample_rate,
                                        frame_index / sample_rate,
                                    )
                                )
                            silence_start = None

                    frame_index += 1

            if silence_start is not None:
                silent_duration = (frame_index - silence_start) / sample_rate
                if silent_duration >= silence_min_seconds:
                    silent_regions.append(
                        SilentRegion(
                            silence_start / sample_rate,
                            frame_index / sample_rate,
                        )
                    )

            actual_duration = actual_n_frames / sample_rate
            return AudioAnalysis(
                duration_seconds=actual_duration,
                sample_rate=sample_rate,
                n_channels=n_channels,
                samples_per_channel=actual_n_frames,
                waveform=bin_peaks,
                silent_regions=silent_regions,
            )
    except (OSError, EOFError, wave.Error, struct.error, ValueError) as e:
        logger.error("Failed to analyse WAV %s: %s", wav_path, e)
        return None


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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=300,
            )
            if result.returncode != 0:
                logger.error("ffmpeg trim failed: %s", result.stderr)
                return False
            return output_path.exists()
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as e:
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
    filter_complex += (
        f";{''.join(concat_inputs)}concat=n={len(keep_regions)}:v=0:a=1[out]"
    )

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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
        )
        if result.returncode != 0:
            logger.error("ffmpeg concat trim failed: %s", result.stderr)
            return False
        return output_path.exists()
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as e:
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
        True if all existing files were trimmed successfully.
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

    any_found = False
    all_succeeded = True
    for filename in audio_files:
        file_path = recording_dir / filename
        if not file_path.exists():
            continue

        any_found = True

        # Create backup before overwriting the original, but only keep it for
        # files that are successfully trimmed. On failure the original is
        # untouched, so a leftover backup would be redundant.
        backup_path = file_path.with_suffix(file_path.suffix + ".pretrim")
        created_backup = False
        if backup and not backup_path.exists():
            shutil.copy2(file_path, backup_path)
            created_backup = True
            logger.info("Backed up %s -> %s", filename, backup_path.name)

        # Trim to a temp file, then replace the original.
        # Keep the original extension so ffmpeg can infer the output format.
        tmp_path = file_path.with_stem(file_path.stem + ".trimming")
        try:
            if trim_audio_file(file_path, tmp_path, keep_regions):
                tmp_path.replace(file_path)
                logger.info("Trimmed %s", filename)
            else:
                if tmp_path.exists():
                    tmp_path.unlink()
                if created_backup and backup_path.exists():
                    backup_path.unlink()
                logger.warning("Failed to trim %s, original preserved", filename)
                all_succeeded = False
        except OSError as e:
            logger.error("Error trimming %s: %s", filename, e)
            if tmp_path.exists():
                tmp_path.unlink()
            if created_backup and backup_path.exists():
                backup_path.unlink()
            all_succeeded = False

    return any_found and all_succeeded


def compute_trimmed_duration(keep_regions: list[TrimRegion]) -> float:
    """Compute the total duration of kept regions."""
    return sum(r.end_seconds - r.start_seconds for r in keep_regions)
