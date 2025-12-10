"""Background worker for compressing existing recordings.

Finds transcribed recordings with uncompressed WAV files and converts them to FLAC.
Runs at low priority to avoid impacting UI performance.
"""

import logging
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from quinoa.audio.converter import compress_recording_audio, mix_recording_audio
from quinoa.storage.database import Database

logger = logging.getLogger("quinoa")

# How long to wait between compression jobs (seconds)
COMPRESSION_DELAY_S = 5

# How long to wait before starting compression on app launch (seconds)
STARTUP_DELAY_S = 30


class CompressionWorker(QThread):
    """Background thread for compressing audio files.

    Finds recordings that:
    - Have been transcribed (status = 'transcribed')
    - Have WAV files that haven't been compressed yet

    Compresses them to FLAC one at a time with delays to avoid
    hogging system resources.
    """

    # Signals
    compression_started = pyqtSignal(str)  # recording_id
    compression_completed = pyqtSignal(str, int)  # recording_id, files_compressed
    compression_failed = pyqtSignal(str, str)  # recording_id, error

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._running = False

    def run(self) -> None:
        """Main worker loop."""
        self._running = True

        # Wait a bit after app launch before starting
        logger.info("Compression worker starting (waiting %ds)", STARTUP_DELAY_S)
        for _ in range(STARTUP_DELAY_S):
            if not self._running:
                return
            time.sleep(1)

        logger.info("Compression worker active")

        while self._running:
            try:
                recording = self._find_next_recording()
                if recording:
                    self._compress_recording(recording)
                else:
                    # No work to do, sleep longer
                    for _ in range(60):  # Check every minute when idle
                        if not self._running:
                            return
                        time.sleep(1)
            except Exception as e:
                logger.error("Compression worker error: %s", e)
                time.sleep(COMPRESSION_DELAY_S)

        logger.info("Compression worker stopped")

    def stop(self) -> None:
        """Stop the worker gracefully."""
        self._running = False

    def _find_next_recording(self) -> dict | None:
        """Find a recording that needs compression.

        Returns the first transcribed recording that has WAV files
        but no corresponding FLAC files.
        """
        # Get all transcribed recordings
        recordings = self.db.get_recordings()

        for rec in recordings:
            # Skip if not transcribed
            if rec.get("status") != "transcribed":
                continue

            # Skip if no directory path
            dir_path = rec.get("directory_path")
            if not dir_path:
                continue

            recording_dir = Path(dir_path)
            if not recording_dir.exists():
                continue

            # Check if there are WAV files without FLAC counterparts
            for wav_name in ["microphone.wav", "system.wav", "mixed_stereo.wav"]:
                wav_path = recording_dir / wav_name
                flac_path = wav_path.with_suffix(".flac")

                if wav_path.exists() and not flac_path.exists():
                    return rec

        return None

    def _compress_recording(self, rec: dict) -> None:
        """Compress a single recording."""
        rec_id = rec["id"]
        dir_path = rec["directory_path"]

        logger.info("Processing audio for recording %s", rec_id)
        self.compression_started.emit(rec_id)

        try:
            # 1. Mix audio if needed
            mixed_path = mix_recording_audio(dir_path)
            if mixed_path:
                logger.info("Mixed audio created: %s", mixed_path)
                # Update DB with stereo path
                self.db.update_recording_paths(rec_id, stereo_path=str(mixed_path))

            # 2. Compress
            results = compress_recording_audio(dir_path, delete_originals=False)
            compressed_count = sum(1 for v in results.values() if v is not None)

            if compressed_count > 0:
                logger.info("Compressed %d files for recording %s", compressed_count, rec_id)
                self.compression_completed.emit(rec_id, compressed_count)
            else:
                logger.debug("No files compressed for recording %s", rec_id)

        except Exception as e:
            logger.error("Failed to compress recording %s: %s", rec_id, e)
            self.compression_failed.emit(rec_id, str(e))

        # Delay before next compression
        for _ in range(COMPRESSION_DELAY_S):
            if not self._running:
                return
            time.sleep(1)
