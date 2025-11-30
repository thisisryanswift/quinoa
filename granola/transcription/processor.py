import os
import wave
from pathlib import Path

from granola.constants import AUDIO_CHUNK_SIZE


def create_stereo_mix(mic_path: str | Path, sys_path: str | Path, output_path: str | Path) -> str:
    """
    Merges two WAV files into a single stereo WAV file.
    Left channel: Microphone (mixed down to mono if stereo)
    Right channel: System Audio (mixed down to mono if stereo)
    """
    if not os.path.exists(mic_path) or not os.path.exists(sys_path):
        raise FileNotFoundError("Input audio files not found")

    with wave.open(str(mic_path), "rb") as mic_wav, wave.open(str(sys_path), "rb") as sys_wav:
        # Validate compatibility
        if mic_wav.getframerate() != sys_wav.getframerate():
            raise ValueError(
                f"Sample rates mismatch: {mic_wav.getframerate()} vs {sys_wav.getframerate()}"
            )

        if mic_wav.getsampwidth() != sys_wav.getsampwidth():
            raise ValueError("Sample widths mismatch")

        sampwidth = mic_wav.getsampwidth()
        framerate = mic_wav.getframerate()

        mic_channels = mic_wav.getnchannels()
        sys_channels = sys_wav.getnchannels()

        mic_frames_total = mic_wav.getnframes()
        sys_frames_total = sys_wav.getnframes()
        max_frames = max(mic_frames_total, sys_frames_total)

        with wave.open(str(output_path), "wb") as out_wav:
            out_wav.setnchannels(2)
            out_wav.setsampwidth(sampwidth)
            out_wav.setframerate(framerate)
            out_wav.setnframes(max_frames)

            for _ in range(0, max_frames, AUDIO_CHUNK_SIZE):
                mic_data = mic_wav.readframes(AUDIO_CHUNK_SIZE)
                sys_data = sys_wav.readframes(AUDIO_CHUNK_SIZE)

                # Pad with silence if needed
                mic_expected_len = AUDIO_CHUNK_SIZE * sampwidth * mic_channels
                if len(mic_data) < mic_expected_len:
                    mic_data += b"\x00" * (mic_expected_len - len(mic_data))

                sys_expected_len = AUDIO_CHUNK_SIZE * sampwidth * sys_channels
                if len(sys_data) < sys_expected_len:
                    sys_data += b"\x00" * (sys_expected_len - len(sys_data))

                # Extract mono samples
                # If stereo, take first channel (first sampwidth bytes of every frame)

                mic_mono = bytearray()
                mic_frame_size = sampwidth * mic_channels
                for i in range(0, len(mic_data), mic_frame_size):
                    mic_mono.extend(mic_data[i : i + sampwidth])

                sys_mono = bytearray()
                sys_frame_size = sampwidth * sys_channels
                for i in range(0, len(sys_data), sys_frame_size):
                    sys_mono.extend(sys_data[i : i + sampwidth])

                # Interleave for output stereo
                stereo_data = bytearray()
                for i in range(0, len(mic_mono), sampwidth):
                    stereo_data.extend(mic_mono[i : i + sampwidth])  # Left
                    stereo_data.extend(sys_mono[i : i + sampwidth])  # Right

                out_wav.writeframes(stereo_data)

    return str(output_path)
