from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = {"side_camera_id": None, "rear_camera_id": None}
CONFIG_PATH = CONFIG_DIR / "camera_config.json"
EXAMPLE_CONFIG_PATH = CONFIG_DIR / "camera_config.example.json"


def _ensure_example_exists() -> None:
    if not EXAMPLE_CONFIG_PATH.exists():
        EXAMPLE_CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)

    cleaned = dict(DEFAULT_CONFIG)
    cleaned.update({
        "side_camera_id": data.get("side_camera_id"),
        "rear_camera_id": data.get("rear_camera_id"),
    })
    return cleaned


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    _ensure_example_exists()
    cleaned = dict(DEFAULT_CONFIG)
    cleaned.update(config)

    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(cleaned, handle, indent=2)
        handle.write("\n")

    return cleaned
