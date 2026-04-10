"""Configuration management for the save game syncer.

Stores connection settings in a JSON file next to the executable or
in the user's AppData directory.
"""

import json
import os
import logging
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "vostok_sync_config.json"


def _config_dir() -> str:
    """Return the config directory (AppData/Roaming on Windows, ~/.config on Linux)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        )
    config_dir = os.path.join(base, "VostokSaveSync")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def config_path() -> str:
    return os.path.join(_config_dir(), CONFIG_FILENAME)


@dataclass
class SyncConfig:
    remote_host: str = ""
    remote_port: int = 22
    remote_username: str = ""
    remote_password: str = ""  # stored in plaintext - user's choice
    local_save_dir: str = ""
    remote_save_dir: str = ""

    def save(self) -> str:
        """Save config to JSON file. Returns the path written to."""
        path = config_path()
        data = asdict(self)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("Config saved to %s", path)
        return path

    @classmethod
    def load(cls) -> "SyncConfig":
        """Load config from JSON file. Returns defaults if file missing."""
        path = config_path()
        if not os.path.exists(path):
            logger.info("No config file found, using defaults.")
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Config loaded from %s", path)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to load config: %s. Using defaults.", exc)
            return cls()
