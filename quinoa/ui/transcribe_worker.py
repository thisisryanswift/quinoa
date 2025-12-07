"""Background worker for transcription tasks."""

import os

from PyQt6.QtCore import QThread, pyqtSignal

from quinoa.config import config
from quinoa.transcription.gemini import GeminiTranscriber
from quinoa.transcription.processor import create_stereo_mix


class TranscribeWorker(QThread):
    """Background thread for audio transcription."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, output_dir):
        super().__init__()
        self.output_dir = output_dir

    def run(self):
        try:
            mic_path = os.path.join(self.output_dir, "microphone.wav")
            sys_path = os.path.join(self.output_dir, "system.wav")
            stereo_path = os.path.join(self.output_dir, "mixed_stereo.wav")

            # 1. Mix audio
            if not os.path.exists(mic_path):
                self.error.emit("Microphone recording not found.")
                return

            if os.path.exists(sys_path):
                create_stereo_mix(mic_path, sys_path, stereo_path)
                upload_path = stereo_path
            else:
                upload_path = mic_path

            # 2. Transcribe
            api_key = config.get("api_key")
            transcriber = GeminiTranscriber(api_key=api_key)
            transcript = transcriber.transcribe(upload_path)

            self.finished.emit(transcript)

        except Exception as e:
            self.error.emit(str(e))
