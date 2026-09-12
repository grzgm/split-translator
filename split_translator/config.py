"""Loads personal configuration (book paths and page anchors)."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .layout import LAYOUT_NORMAL, normalise_layout

# All personal config and storage lives in a hidden .config dir at the project
# root, one level above this package, so the project root stays uncluttered.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / ".config"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass(frozen=True)
class Config:
    """Resolved configuration for one workspace."""

    # The workspace's display name, shown in the window title.
    name: str
    # The folder this config was loaded from. Every store writes its file here,
    # which is what makes one config file per workspace enough to keep the
    # workspaces apart.
    dir: Path
    original_path: str
    translation_path: str
    page_anchors: list[tuple[int, int]]
    # Which arrangement this workspace was last read in (see layout.py).
    # Last and defaulted because it is the only field the window writes
    # back, and every other caller builds a Config without it.
    layout: str = LAYOUT_NORMAL


def load_config(config_path: Path = CONFIG_PATH) -> Config:
    """Load personal config (book paths, page anchors) from a gitignored file.

    Exits with a helpful message if the config file is missing or malformed.
    """
    # Ensure the .config dir exists so the storage workers can write into it.
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if not config_path.exists():
        sys.exit(
            f"Config file not found: {config_path}\n"
            "This workspace's config.json is missing. Recreate the workspace "
            "from the workspace picker."
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
            # The folder name is the fallback, so a config.json written by hand
            # without a name still titles the window with something useful.
            name=str(raw.get("name") or config_path.parent.name),
            dir=config_path.parent,
            original_path=raw["original_path"],
            translation_path=raw["translation_path"],
            page_anchors=page_anchors,
            layout=normalise_layout(raw.get("layout")),
        )
    except (KeyError, TypeError) as exc:
        sys.exit(f"Config file {config_path} is missing required keys: {exc}")


def save_layout(config_dir: Path, layout: str) -> None:
    """Record which layout a workspace was left in, touching no other key.

    The file is read back first so the keys the workspace picker owns (the name
    and the two book paths) survive, the same way save_workspace leaves this key
    alone. A missing or malformed file is left as it is: it is the picker's to
    repair, and a layout is not worth overwriting one to record.
    """
    path = config_dir / "config.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(raw, dict):
        return
    raw["layout"] = normalise_layout(layout)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
