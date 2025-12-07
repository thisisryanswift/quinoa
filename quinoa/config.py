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
    # Window state persistence
    "splitter_sizes": None,  # Will use SPLITTER_DEFAULT_SIZES if None
    "left_panel_collapsed": False,
    "right_panel_collapsed": False,
    # File Search settings
    "file_search_enabled": False,  # User opt-in
    "file_search_delay_minutes": 5,  # Delay before sync
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

    def get(self, key: str, default: Any | None = None) -> Any:
        # Keys stored in keyring for security
        if key == "api_key":
            try:
                return keyring.get_password(SERVICE_NAME, API_KEY_USER) or default
            except Exception as e:
                logger.warning("Keyring error: %s", e)
                return default
        if key == "file_search_store_name":
            try:
                return keyring.get_password(SERVICE_NAME, FILE_SEARCH_STORE_USER) or default
            except Exception as e:
                logger.warning("Keyring error: %s", e)
                return default
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        # Keys stored in keyring for security
        if key == "api_key":
            try:
                if value:
                    keyring.set_password(SERVICE_NAME, API_KEY_USER, value)
                else:
                    with contextlib.suppress(keyring.errors.PasswordDeleteError):
                        keyring.delete_password(SERVICE_NAME, API_KEY_USER)
            except Exception as e:
                logger.warning("Failed to save to keyring: %s", e)
        elif key == "file_search_store_name":
            try:
                if value:
                    keyring.set_password(SERVICE_NAME, FILE_SEARCH_STORE_USER, value)
                else:
                    with contextlib.suppress(keyring.errors.PasswordDeleteError):
                        keyring.delete_password(SERVICE_NAME, FILE_SEARCH_STORE_USER)
            except Exception as e:
                logger.warning("Failed to save to keyring: %s", e)
        else:
            self._data[key] = value
            self.save()


# Global instance
config = Config()
