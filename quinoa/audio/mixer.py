import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("quinoa")


# FFmpeg filter complex for stereo mix:
# [0:a] is left channel (mic), [1:a] is right channel (system)
# pan=mono|c0=c0 ensures each input is mono before joining.
MIX_FILTER_COMPLEX = "[0:a]pan=mono|c0=c0[mic];[1:a]pan=mono|c0=c0[sys];[mic][sys]join=inputs=2:channel_layout=stereo[a]"


def create_stereo_mix(
    mic_path: str | Path, sys_path: str | Path, output_path: str | Path, timeout: int = 300
) -> str:
    """
    Merges two WAV files into a single stereo WAV file using ffmpeg.
    Left channel: Microphone (forced to mono)
    Right channel: System Audio (forced to mono)

    This is significantly faster than pure-Python mixing and avoids GIL issues.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH. Please install ffmpeg for audio mixing.")

    if not os.path.exists(mic_path) or not os.path.exists(sys_path):
        raise FileNotFoundError(f"Input audio files not found: {mic_path} or {sys_path}")

    # Command to interleave two mono streams into one stereo stream.
    # [0:a] is the microphone, [1:a] is the system audio.
    # pan=mono|c0=c0 ensures each input is mono before joining.
    # join=inputs=2:channel_layout=stereo creates the final stereo file.
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(mic_path),
        "-i",
        str(sys_path),
        "-filter_complex",
        MIX_FILTER_COMPLEX,
        "-map",
        "[a]",
        str(output_path),
    ]

    try:
        logger.debug("Running ffmpeg stereo mix: %s", " ".join(cmd))
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode()
        logger.error("ffmpeg mixing failed: %s", error_output)
        raise RuntimeError(f"ffmpeg mixing failed: {error_output}") from e
    except subprocess.TimeoutExpired as e:
        logger.error("ffmpeg mixing timed out after %ds", timeout)
        raise RuntimeError(f"ffmpeg mixing timed out after {timeout}s") from e

    return str(output_path)
