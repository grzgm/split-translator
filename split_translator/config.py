"""Loads personal configuration (book paths and page anchors)."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# config.json lives next to the project root, one level above this package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass(frozen=True)
class Config:
    """Resolved application configuration."""

    pdf_original_path: str
    pdf_translation_path: str
    page_anchors: list[tuple[int, int]]


def load_config(config_path: Path = CONFIG_PATH) -> Config:
    """Load personal config (book paths, page anchors) from a gitignored file.

    Exits with a helpful message if the config file is missing or malformed.
    """
    if not config_path.exists():
        sys.exit(
            f"Config file not found: {config_path}\n"
            "Copy config.sample.json to config.json and fill in your book paths."
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
            pdf_original_path=raw["pdf_original_path"],
            pdf_translation_path=raw["pdf_translation_path"],
            page_anchors=page_anchors,
        )
    except (KeyError, TypeError) as exc:
        sys.exit(f"Config file {config_path} is missing required keys: {exc}")
