import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import keyring
import keyring.errors

logger = logging.getLogger("quinoa")

CONFIG_DIR = Path(os.path.expanduser("~/.config/quinoa"))
CONFIG_FILE = CONFIG_DIR / "config.json"
SERVICE_NAME = "quinoa"
API_KEY_USER = "gemini_api_key"
FILE_SEARCH_STORE_USER = "file_search_store_name"

DEFAULT_CONFIG = {
    "output_dir": os.path.expanduser("~/Music/Quinoa"),
    "system_audio_enabled": True,
    "mic_device_id": None,
    # AI model
    "gemini_model": None,  # Uses GEMINI_MODEL_TRANSCRIPTION constant if None
    "cached_gemini_models": None,  # Cached list of available models from API
    # Window state persistence
    "splitter_sizes": None,  # Will use SPLITTER_DEFAULT_SIZES if None
    "left_panel_collapsed": False,
    "right_panel_collapsed": False,
    # File Search settings
    "file_search_enabled": False,  # User opt-in
    "file_search_delay_minutes": 5,  # Delay before sync
    "calendar_auth_expired": False,  # True if refresh failed
    # Automation
    "auto_transcribe": True,  # Transcribe automatically after recording stops
    # Notifications
    "notifications_enabled": True,  # Show meeting notifications
    "recording_reminder_enabled": True,  # Warn if meeting started but not recording
    "reminder_grace_period_minutes": 2,  # Minutes after meeting start before reminder
    "notify_video_only": True,  # Only notify for meetings with video links
}


class Config:
    def __init__(self) -> None:
        self._data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    saved = json.load(f)
                    if not isinstance(saved, dict):
                        raise ValueError("Config file did not contain a JSON object")
                    # Filter out api_key if it was accidentally saved in json before
                    if "api_key" in saved:
                        del saved["api_key"]
                    self._data.update(saved)
            except Exception as e:
                logger.warning("Failed to load config: %s", e)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w") as f:
                # Ensure we never save api_key to json
                data_to_save = {k: v for k, v in self._data.items() if k != "api_key"}
                json.dump(data_to_save, f, indent=4)
        except Exception as e:
            logger.warning("Failed to save config: %s", e)

    def _get_keyring_value(self, user: str, default: Any = None) -> Any:
        """Robustly retrieve a password from the keyring."""
        try:
            raw_data = keyring.get_password(SERVICE_NAME, user)
            if not raw_data:
                return default

            if isinstance(raw_data, bytes):
                try:
                    return raw_data.decode("utf-8")
                except UnicodeDecodeError:
                    logger.warning("Corrupt binary data for %s in keyring, clearing.", user)
                    with contextlib.suppress(Exception):
                        keyring.set_password(SERVICE_NAME, user, "")
                    return default
            return raw_data
        except Exception as e:
            logger.warning("Keyring error for %s: %s", user, e)
            return default

    def get(self, key: str, default: Any | None = None) -> Any:
        # Keys stored in keyring for security
        if key == "api_key":
            return self._get_keyring_value(API_KEY_USER, default)
        if key == "file_search_store_name":
            return self._get_keyring_value(FILE_SEARCH_STORE_USER, default)
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        # Keys stored in keyring for security
        if key == "api_key":
            try:
                if value:
                    keyring.set_password(SERVICE_NAME, API_KEY_USER, value)
                else:
                    with contextlib.suppress(Exception):
                        keyring.set_password(SERVICE_NAME, API_KEY_USER, "")
            except Exception as e:
                logger.warning("Failed to save to keyring: %s", e)
        elif key == "file_search_store_name":
            try:
                if value:
                    keyring.set_password(SERVICE_NAME, FILE_SEARCH_STORE_USER, value)
                else:
                    with contextlib.suppress(Exception):
                        keyring.set_password(SERVICE_NAME, FILE_SEARCH_STORE_USER, "")
            except Exception as e:
                logger.warning("Failed to save to keyring: %s", e)
        else:
            self._data[key] = value
            self.save()


# Global instance
config = Config()
