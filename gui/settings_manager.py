from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def get_config_dir() -> Path:
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home()
        config_dir = base / "CorridorKey Studio"
    else:
        config_dir = Path.home() / ".config" / "corridorkey-studio"

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # fallback to application directory if user profile is restricted
        config_dir = Path(__file__).resolve().parents[1] / ".config"
        config_dir.mkdir(parents=True, exist_ok=True)

    return config_dir


def get_presets_dir() -> Path:
    presets_dir = get_config_dir() / "presets"
    presets_dir.mkdir(parents=True, exist_ok=True)
    return presets_dir


def get_settings_file() -> Path:
    return get_config_dir() / "settings.json"


def load_settings() -> dict:
    settings_file = get_settings_file()
    if not settings_file.is_file():
        return {}
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # auto-migrate legacy brightness offset (0.0) to linear gain multiplier (1.0)
            if isinstance(data, dict) and "bright" in data:
                try:
                    if float(data["bright"]) <= 0.05:
                        data["bright"] = 1.0
                except (ValueError, TypeError):
                    data["bright"] = 1.0
            return data
    except Exception:
        return {}


def save_settings(data: dict) -> bool:
    settings_file = get_settings_file()
    try:
        temp_file = settings_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(settings_file)
        return True
    except Exception:
        return False


def list_custom_presets() -> list[str]:
    presets_dir = get_presets_dir()
    if not presets_dir.is_dir():
        return []
    names = []
    for p in sorted(presets_dir.glob("*.json")):
        names.append(p.stem)
    return names


def save_custom_preset(name: str, data: dict) -> bool:
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_", " ")).strip()
    if not safe_name:
        return False
    preset_file = get_presets_dir() / f"{safe_name}.json"
    try:
        with open(preset_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def load_custom_preset(name: str) -> dict | None:
    preset_file = get_presets_dir() / f"{name}.json"
    if not preset_file.is_file():
        return None
    try:
        with open(preset_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_custom_preset(name: str) -> bool:
    preset_file = get_presets_dir() / f"{name}.json"
    try:
        if preset_file.is_file():
            preset_file.unlink()
            return True
        return False
    except Exception:
        return False
