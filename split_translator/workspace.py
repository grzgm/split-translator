"""Workspaces: independent reading projects.

Each workspace is a self-contained folder under .config/workspaces/ holding its
own book paths, search history, flashcard deck and content anchors. Nothing is
shared between workspaces except the browser profile, which is not workspace
data.

The folder name (slug) is derived from the display name, which lives in the
workspace's own config.json. There is no central registry: workspaces are found
by scanning, so no stored list can disagree with what is on disk. Files sitting
directly in .config/ are therefore never seen and never read.

Every function takes its root or path as an optional argument, resolved from the
module constant inside the body rather than as a default value. A default is
evaluated when the function is defined, which would bake in the real .config/
path and leave tests unable to redirect it by patching the constant. Resolving
in the body means patching WORKSPACES_DIR or SETTINGS_PATH redirects every call
that omits the argument.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import CONFIG_DIR

WORKSPACES_DIR = CONFIG_DIR / "workspaces"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

# Stamped into the app-level settings file. Informational, like the flashcard
# store's version: there is no migration code reading it.
SETTINGS_VERSION = 1

# The slug for a name that normalises to nothing: punctuation only, or a name
# written entirely in a non-Latin script.
FALLBACK_SLUG = "workspace"

# Letters NFKD does not decompose, because they are distinct letters rather than
# a base plus a combining mark. Without the first pair, "Lodz" spelled with the
# Polish l with stroke would slug to "odz" and lose its first letter.
_TRANSLITERATE = str.maketrans(
    {
        "\u0142": "l",   # small l with stroke (Polish)
        "\u0141": "L",   # capital L with stroke
        "\u00df": "ss",  # sharp s
        "\u00f8": "o",   # small o with stroke
        "\u00d8": "O",   # capital O with stroke
        "\u0111": "d",   # small d with stroke
        "\u0110": "D",   # capital D with stroke
        "\u00e6": "ae",  # small ae
        "\u00c6": "AE",  # capital AE
    }
)


@dataclass(frozen=True)
class Workspace:
    """One reading project: its folder, plus the book pair its config records."""

    slug: str
    name: str
    dir: Path
    original_path: str
    translation_path: str


def slugify(name: str, taken: set[str]) -> str:
    """A folder name for a display name.

    Accented letters fold to ASCII, every other run of non-alphanumerics becomes
    a single hyphen, and the ends are trimmed. A numeric suffix avoids anything
    in taken, which is how folder names stay unique with no registry to consult.
    """
    decomposed = unicodedata.normalize("NFKD", name.translate(_TRANSLITERATE))
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    base = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-") or FALLBACK_SLUG
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def workspace_dir(slug: str, root: Path | None = None) -> Path:
    """The folder holding one workspace's files."""
    return (root or WORKSPACES_DIR) / slug


def config_path_for(slug: str, root: Path | None = None) -> Path:
    """A workspace's config file, in the shape load_config already reads."""
    return workspace_dir(slug, root) / "config.json"


def read_workspace(directory: Path) -> Workspace | None:
    """Read one workspace folder, or None if it holds no usable config.json.

    A folder that is not a workspace is skipped rather than treated as an error,
    so an unrelated directory under the workspaces root cannot break the picker.
    """
    try:
        with open(directory / "config.json", "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return Workspace(
        slug=directory.name,
        # The folder name is the fallback display name, so a config.json written
        # by hand without a name still lists sensibly rather than blank.
        name=str(raw.get("name") or directory.name),
        dir=directory,
        original_path=str(raw.get("original_path") or ""),
        translation_path=str(raw.get("translation_path") or ""),
    )


def list_workspaces(root: Path | None = None) -> list[Workspace]:
    """Every workspace on disk, sorted by display name, case insensitively.

    Alphabetical rather than most-recently-opened: that would need a timestamp
    written into every workspace on open, and the picker shows no such time.
    """
    root = root or WORKSPACES_DIR
    if not root.is_dir():
        return []
    found = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        workspace = read_workspace(entry)
        if workspace is not None:
            found.append(workspace)
    return sorted(found, key=lambda workspace: workspace.name.lower())


def load_settings(path: Path | None = None) -> dict:
    """App-level settings from .config/settings.json.

    Tolerant like every other store here: a missing or malformed file reads as
    empty and is left untouched until the next successful save.
    """
    path = path or SETTINGS_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_settings(settings: dict, path: Path | None = None) -> None:
    """Write the app-level settings file, creating .config/ if it is missing."""
    path = path or SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(settings)
    data["version"] = SETTINGS_VERSION
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def last_workspace(path: Path | None = None) -> str | None:
    """The slug the app was last opened with, or None if none is recorded."""
    value = load_settings(path).get("last_workspace")
    return value if isinstance(value, str) and value else None


def set_last_workspace(slug: str, path: Path | None = None) -> None:
    """Record the slug to open on the next launch, keeping other settings."""
    settings = load_settings(path)
    settings["last_workspace"] = slug
    save_settings(settings, path)
