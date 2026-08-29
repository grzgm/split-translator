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
import shutil
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


def taken_slugs(root: Path | None = None) -> set[str]:
    """Every folder name already used under the workspaces root.

    Includes folders that are not valid workspaces, because a name is taken on
    disk whether or not the app understands what is in it.
    """
    root = root or WORKSPACES_DIR
    if not root.is_dir():
        return set()
    return {entry.name for entry in root.iterdir() if entry.is_dir()}


def save_workspace(workspace: Workspace) -> None:
    """Write a workspace's config.json, creating the folder if it is missing, so
    a freshly created workspace and an edited one take the same path."""
    workspace.dir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": workspace.name,
        "original_path": workspace.original_path,
        "translation_path": workspace.translation_path,
    }
    with open(workspace.dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_workspace(name: str, root: Path | None = None) -> Workspace:
    """Create a workspace with no book paths set.

    The deck, history and anchor files are simply absent, which every store
    already reads as empty, so there is nothing to seed.
    """
    root = root or WORKSPACES_DIR
    slug = slugify(name, taken_slugs(root))
    workspace = Workspace(
        slug=slug,
        name=name,
        dir=root / slug,
        original_path="",
        translation_path="",
    )
    save_workspace(workspace)
    return workspace


def delete_workspace(slug: str, root: Path | None = None) -> None:
    """Remove a workspace folder and everything in it, permanently."""
    shutil.rmtree((root or WORKSPACES_DIR) / slug)


def duplicate_workspace(
    slug: str, name: str, root: Path | None = None
) -> Workspace:
    """Copy a workspace's whole folder under a new slug and name.

    The deck, history and every anchor file travel with it; only the name in the
    copy's config.json differs.
    """
    root = root or WORKSPACES_DIR
    source = read_workspace(root / slug)
    if source is None:
        raise ValueError(f"Not a workspace: {slug}")
    new_slug = slugify(name, taken_slugs(root))
    shutil.copytree(root / slug, root / new_slug)
    copy = Workspace(
        slug=new_slug,
        name=name,
        dir=root / new_slug,
        original_path=source.original_path,
        translation_path=source.translation_path,
    )
    save_workspace(copy)
    return copy


def rename_workspace_folder(
    old_slug: str, new_slug: str, root: Path | None = None
) -> None:
    """Move a workspace folder so it matches its display name.

    The caller allocates new_slug with slugify(name, taken_slugs(root) minus the
    workspace's own slug), never this function: the caller needs the resulting
    slug in order to reopen the workspace afterwards, so discovering it here
    would leave the caller guessing.

    Path.rename refuses a non-empty existing target, which is the behaviour to
    want: a clash raises rather than destroying the other workspace.
    """
    if old_slug == new_slug:
        return
    root = root or WORKSPACES_DIR
    (root / old_slug).rename(root / new_slug)


def both_books_resolve(workspace: Workspace) -> bool:
    """Whether both of a workspace's book paths point at a file that exists.

    One rule with one implementation, used by the picker to enable Open and by
    app.main to decide whether a workspace can be launched into. It matters
    because book_loader.load_book raises ValueError on an unreadable file, which
    would crash BookPanel's constructor before anything could offer a repair.
    """
    return bool(
        workspace.original_path
        and workspace.translation_path
        and Path(workspace.original_path).is_file()
        and Path(workspace.translation_path).is_file()
    )


def startup_slug(
    root: Path | None = None, settings_path: Path | None = None
) -> str | None:
    """The workspace to open without asking, or None when the picker is needed.

    None when nothing is recorded, when the recorded workspace is no longer on
    disk, or when its books cannot be read.
    """
    slug = last_workspace(settings_path)
    if not slug:
        return None
    workspace = read_workspace((root or WORKSPACES_DIR) / slug)
    if workspace is None or not both_books_resolve(workspace):
        return None
    return slug
