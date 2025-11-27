import json
import os
from pathlib import Path
import keyring
import keyring.errors

CONFIG_DIR = Path(os.path.expanduser("~/.config/granola"))
CONFIG_FILE = CONFIG_DIR / "config.json"
SERVICE_NAME = "granola-linux"
API_KEY_USER = "gemini_api_key"

DEFAULT_CONFIG = {
    "output_dir": os.path.expanduser("~/Music/Granola"),
    "system_audio_enabled": True,
    "mic_device_id": None,
}


class Config:
    def __init__(self):
        self._data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    saved = json.load(f)
                    # Filter out api_key if it was accidentally saved in json before
                    if "api_key" in saved:
                        del saved["api_key"]
                    self._data.update(saved)
            except Exception as e:
                print(f"Failed to load config: {e}")

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w") as f:
                # Ensure we never save api_key to json
                data_to_save = {k: v for k, v in self._data.items() if k != "api_key"}
                json.dump(data_to_save, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def get(self, key, default=None):
        if key == "api_key":
            try:
                return keyring.get_password(SERVICE_NAME, API_KEY_USER) or default
            except Exception as e:
                print(f"Keyring error: {e}")
                return default
        return self._data.get(key, default)

    def set(self, key, value):
        if key == "api_key":
            try:
                if value:
                    keyring.set_password(SERVICE_NAME, API_KEY_USER, value)
                else:
                    try:
                        keyring.delete_password(SERVICE_NAME, API_KEY_USER)
                    except keyring.errors.PasswordDeleteError:
                        pass
            except Exception as e:
                print(f"Failed to save to keyring: {e}")
        else:
            self._data[key] = value
            self.save()


# Global instance
config = Config()
