"""Loads personal configuration (book paths and page anchors)."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# All personal config and storage lives in a hidden .config dir at the project
# root, one level above this package, so the project root stays uncluttered.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / ".config"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass(frozen=True)
class Config:
    """Resolved application configuration."""

    original_path: str
    translation_path: str
    page_anchors: list[tuple[int, int]]


def load_config(config_path: Path = CONFIG_PATH) -> Config:
    """Load personal config (book paths, page anchors) from a gitignored file.

    Exits with a helpful message if the config file is missing or malformed.
    """
    # Ensure the .config dir exists so the storage workers can write into it.
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if not config_path.exists():
        sys.exit(
            f"Config file not found: {config_path}\n"
            "Copy config.sample.json to .config/config.json and fill in your "
            "book paths."
        )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        sys.exit(f"Could not read config file {config_path}: {exc}")

    try:
        # page_anchors is legacy and optional: content anchors now live in the
        # per-book-pair anchor store, so a config without it loads fine.
        page_anchors = [tuple(anchor) for anchor in raw.get("page_anchors", [])]
        return Config(
            original_path=raw["original_path"],
            translation_path=raw["translation_path"],
            page_anchors=page_anchors,
        )
    except (KeyError, TypeError) as exc:
        sys.exit(f"Config file {config_path} is missing required keys: {exc}")
