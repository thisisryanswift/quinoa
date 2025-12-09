"""Audio format conversion utilities.

Converts WAV files to FLAC for storage optimization after transcription.
Uses ffmpeg for conversion.

# TODO: Make format configurable in settings (FLAC vs Opus)
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("quinoa")

# Default compression format
# FLAC is lossless and well-supported by Gemini
DEFAULT_FORMAT = "flac"


def get_compressed_path(wav_path: str | Path, format: str = DEFAULT_FORMAT) -> Path:
    """Get the path for the compressed version of a WAV file.

    Args:
        wav_path: Path to the original WAV file
        format: Target format (flac, opus, etc.)

    Returns:
        Path with the new extension
    """
    wav_path = Path(wav_path)
    return wav_path.with_suffix(f".{format}")


def compress_audio(
    wav_path: str | Path,
    format: str = DEFAULT_FORMAT,
    delete_original: bool = False,
) -> Path | None:
    """Compress a WAV file to FLAC or other format.

    Args:
        wav_path: Path to the WAV file to compress
        format: Target format (default: flac)
        delete_original: If True, delete the original WAV after successful conversion

    Returns:
        Path to the compressed file, or None if conversion failed
    """
    wav_path = Path(wav_path)

    if not wav_path.exists():
        logger.warning("WAV file not found: %s", wav_path)
        return None

    if wav_path.suffix.lower() != ".wav":
        logger.warning("Not a WAV file: %s", wav_path)
        return None

    # Check if ffmpeg is available
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg not found in PATH. Cannot compress audio.")
        return None

    output_path = get_compressed_path(wav_path, format)

    # Skip if already compressed
    if output_path.exists():
        logger.debug("Compressed file already exists: %s", output_path)
        return output_path

    try:
        # Build ffmpeg command based on format
        cmd = ["ffmpeg", "-y", "-i", str(wav_path)]

        if format == "flac":
            # FLAC: lossless compression
            cmd.extend(["-c:a", "flac", "-compression_level", "8"])
        elif format == "opus":
            # Opus: lossy but excellent for speech
            cmd.extend(["-c:a", "libopus", "-b:a", "64k"])
        else:
            logger.error("Unsupported format: %s", format)
            return None

        cmd.append(str(output_path))

        logger.info("Compressing %s to %s", wav_path.name, output_path.name)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            logger.error("ffmpeg failed: %s", result.stderr)
            # Clean up partial output
            if output_path.exists():
                output_path.unlink()
            return None

        # Verify output file was created
        if not output_path.exists():
            logger.error("Output file not created: %s", output_path)
            return None

        # Log compression ratio
        original_size = wav_path.stat().st_size
        compressed_size = output_path.stat().st_size
        ratio = (1 - compressed_size / original_size) * 100
        logger.info(
            "Compressed %s: %.1f MB -> %.1f MB (%.0f%% reduction)",
            wav_path.name,
            original_size / (1024 * 1024),
            compressed_size / (1024 * 1024),
            ratio,
        )

        # Delete original if requested
        if delete_original:
            wav_path.unlink()
            logger.debug("Deleted original: %s", wav_path)

        return output_path

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out compressing %s", wav_path)
        if output_path.exists():
            output_path.unlink()
        return None
    except Exception as e:
        logger.error("Failed to compress %s: %s", wav_path, e)
        if output_path.exists():
            output_path.unlink()
        return None


def compress_recording_audio(
    recording_dir: str | Path,
    format: str = DEFAULT_FORMAT,
    delete_originals: bool = False,
) -> dict[str, Path | None]:
    """Compress all WAV files in a recording directory.

    Args:
        recording_dir: Directory containing microphone.wav and/or system.wav
        format: Target format
        delete_originals: If True, delete original WAVs after successful conversion

    Returns:
        Dict mapping original filenames to compressed paths (or None if failed)
    """
    recording_dir = Path(recording_dir)
    results: dict[str, Path | None] = {}

    for wav_name in ["microphone.wav", "system.wav", "mixed_stereo.wav"]:
        wav_path = recording_dir / wav_name
        if wav_path.exists():
            results[wav_name] = compress_audio(wav_path, format, delete_originals)

    return results
