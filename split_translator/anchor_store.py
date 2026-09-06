"""Persists content-anchor pairs for one book pair to a JSON file, off the UI
thread. Mirrors the flashcard/history store pattern (tolerant load, background
SaveWorker, in-flight write awaited on shutdown)."""

import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QThread

from .normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE, NormaliseSpec

SCHEMA_VERSION = 1


def anchor_path_for(
    original_path: str, translation_path: str, root: Path
) -> Path:
    """Return the per-book-pair anchor file path, keyed by the two book paths."""
    key = hashlib.sha1(
        f"{original_path}\n{translation_path}".encode()
    ).hexdigest()[:16]
    return root / f"anchors_{key}.json"


def _load_raw(filepath: Path) -> dict:
    """Read and parse the file, tolerating a missing or malformed one ({})."""
    if not filepath.exists():
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_anchors(filepath: Path) -> list[tuple[str, str]]:
    """Load anchor pairs, tolerating a missing or malformed file by returning []."""
    raw = _load_raw(filepath)
    return [
        (pair["original"], pair["translation"])
        for pair in raw.get("anchors", [])
        if "original" in pair and "translation" in pair
    ]


def _parse_scroll(value) -> tuple[str, float] | None:
    """Parse one side's saved scroll ({"id": str, "fraction": float}) or None."""
    if not isinstance(value, dict):
        return None
    block_id = value.get("id")
    if not block_id:
        return None
    try:
        fraction = float(value.get("fraction", 0.0))
    except (TypeError, ValueError):
        fraction = 0.0
    return (block_id, fraction)


# Each surface that remembers a position (the reading panel and the anchor
# editor) keeps its own original/translation pair so they scroll independently.
READER_SURFACE = "reader"
EDITOR_SURFACE = "editor"

# The scroll positions and the on/off flag above are keyed by SURFACE (reader /
# editor). The normalisation multipliers below are keyed by SIDE (original /
# translation, imported from normalise_spec) instead, because one set of
# multipliers is shared by both surfaces: they exist to line the two editions up
# with each other rather than to suit one screen. The mismatch is deliberate.

_ScrollPair = tuple[tuple[str, float] | None, tuple[str, float] | None]


def _parse_scroll_pair(value) -> _ScrollPair:
    """Parse one surface's {"original": ..., "translation": ...} block."""
    if not isinstance(value, dict):
        return (None, None)
    return (
        _parse_scroll(value.get("original")),
        _parse_scroll(value.get("translation")),
    )


def load_scroll(filepath: Path) -> dict[str, _ScrollPair]:
    """Load each surface's saved (original, translation) scroll positions.
    Returns a dict keyed by surface name; a surface with no saved data is absent.

    Back-compat: a file written before per-surface scroll existed stored the
    position flat under "scroll" ({"original": ..., "translation": ...}); that
    shape is read as the reader's position. A file with no "scroll" key yields an
    empty dict."""
    scroll = _load_raw(filepath).get("scroll", {})
    if not isinstance(scroll, dict):
        return {}
    result: dict[str, _ScrollPair] = {}
    # New per-surface shape: scroll[surface][original|translation].
    for surface in (READER_SURFACE, EDITOR_SURFACE):
        pair = _parse_scroll_pair(scroll.get(surface))
        if pair != (None, None):
            result[surface] = pair
    # Old flat shape (no surface key): treat as the reader, unless a per-surface
    # reader entry already supplied one.
    if READER_SURFACE not in result:
        flat = (
            _parse_scroll(scroll.get("original")),
            _parse_scroll(scroll.get("translation")),
        )
        if flat != (None, None):
            result[READER_SURFACE] = flat
    return result


def load_normalise(filepath: Path) -> dict[str, bool]:
    """Load each surface's saved paragraph-normalisation flag. Returns a dict
    keyed by surface name (reader / editor); a surface with no stored flag is
    absent (the caller supplies the default). A missing or malformed "normalise"
    block yields an empty dict, so every surface then falls back to its default."""
    raw = _load_raw(filepath).get("normalise", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, bool] = {}
    for surface in (READER_SURFACE, EDITOR_SURFACE):
        if surface in raw:
            result[surface] = bool(raw[surface])
    return result


def load_normalise_scale(filepath: Path) -> dict[str, NormaliseSpec]:
    """Load each edition's normalisation multipliers. Returns a dict keyed by
    side (original / translation); a side with nothing stored is absent and the
    caller then uses the default (all x1.0, which is the fixed spec). A missing
    or malformed "normalise_scale" block yields an empty dict, so a hand-broken
    file falls back to the rendering the app has always had."""
    raw = _load_raw(filepath).get("normalise_scale", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, NormaliseSpec] = {}
    for side in (ORIGINAL_SIDE, TRANSLATION_SIDE):
        if side in raw:
            result[side] = NormaliseSpec.from_dict(raw[side])
    return result


def write_anchors(filepath: Path, data: dict) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SaveWorker(QThread):
    """Writes anchors to disk off the UI thread."""

    def __init__(self, filepath: Path, data: dict):
        super().__init__()
        self.filepath = filepath
        self.data = data

    def run(self):
        write_anchors(self.filepath, self.data)


class AnchorStore:
    """Owns the in-memory anchor list and persists it to a JSON file."""

    def __init__(
        self,
        filepath: Path,
        original_path: str | None = None,
        translation_path: str | None = None,
    ):
        self.filepath = filepath
        self.save_worker = None
        # Informational only: the two books' file names, recorded so the
        # hash-named anchor file can be told apart at a glance. Just the
        # basename, never the full path, so no machine path lands in the file.
        self.original_file = (
            os.path.basename(original_path) if original_path else None
        )
        self.translation_file = (
            os.path.basename(translation_path) if translation_path else None
        )
        self.anchors: list[tuple[str, str]] = load_anchors(filepath)
        # Last-known scroll position per surface (reader / editor), each an
        # (original, translation) pair, restored on the next launch.
        self.scroll: dict[str, _ScrollPair] = load_scroll(filepath)
        # Paragraph-normalisation flag per surface (reader / editor). A surface
        # absent here uses the caller's default (ON); see get_normalise.
        self.normalise: dict[str, bool] = load_normalise(filepath)
        # Each edition's normalisation multipliers, shared by both surfaces
        # (see ORIGINAL_SIDE). A side absent here renders at the fixed spec.
        self.normalise_scale: dict[str, NormaliseSpec] = load_normalise_scale(
            filepath
        )

    def add(self, original_id: str, translation_id: str) -> None:
        self.anchors.append((original_id, translation_id))
        self.save()

    def remove(self, original_id: str) -> None:
        self.anchors = [a for a in self.anchors if a[0] != original_id]
        self.save()

    def resolve(
        self, original_ids: list[str], translation_ids: list[str]
    ) -> list[tuple[int, int]]:
        """Convert stored id pairs to index pairs against the current id lists,
        dropping any pair whose id is no longer present."""
        orig_index = {bid: i for i, bid in enumerate(original_ids)}
        trans_index = {bid: i for i, bid in enumerate(translation_ids)}
        pairs = []
        for original_id, translation_id in self.anchors:
            if original_id in orig_index and translation_id in trans_index:
                pairs.append((orig_index[original_id], trans_index[translation_id]))
        return pairs

    def get_scroll(self, surface: str) -> _ScrollPair:
        """Return a surface's saved (original, translation) positions, each or
        None if not stored."""
        return self.scroll.get(surface, (None, None))

    def set_scroll(
        self,
        surface: str,
        original: tuple[str, float] | None,
        translation: tuple[str, float] | None,
    ) -> None:
        """Store a surface's scroll positions and persist. Pass None for a side
        whose position is unknown (it is then not restored). The two surfaces
        (reader / editor) are kept independent."""
        if original is None and translation is None:
            self.scroll.pop(surface, None)
        else:
            self.scroll[surface] = (original, translation)
        self.save()

    def get_normalise(self, surface: str, default: bool = True) -> bool:
        """Return a surface's saved paragraph-normalisation flag, or `default`
        (ON) when the surface has none stored (a fresh book pair, or a file
        written before this feature)."""
        return self.normalise.get(surface, default)

    def set_normalise(self, surface: str, value: bool) -> None:
        """Store a surface's paragraph-normalisation flag and persist. The two
        surfaces (reader / editor) are kept independent, like the scroll state."""
        self.normalise[surface] = bool(value)
        self.save()

    def get_normalise_specs(self) -> tuple[NormaliseSpec, NormaliseSpec]:
        """Return this book pair's (original, translation) normalisation
        multipliers, each defaulting to the fixed spec when nothing is
        stored."""
        return (
            self.normalise_scale.get(ORIGINAL_SIDE, NormaliseSpec()),
            self.normalise_scale.get(TRANSLATION_SIDE, NormaliseSpec()),
        )

    def set_normalise_specs(
        self, original: NormaliseSpec, translation: NormaliseSpec
    ) -> None:
        """Store both editions' multipliers and persist, in one write. Both
        sides are taken together (like set_scroll) so a reset, which changes
        both, does not spawn two write workers."""
        self.normalise_scale[ORIGINAL_SIDE] = original
        self.normalise_scale[TRANSLATION_SIDE] = translation
        self.save()

    @staticmethod
    def _scroll_dict(position: tuple[str, float] | None) -> dict | None:
        if position is None:
            return None
        return {"id": position[0], "fraction": position[1]}

    def _serialise(self) -> dict:
        data = {
            "version": SCHEMA_VERSION,
        }
        # Informational book file names, written near the top so the file is
        # self-identifying. Omitted when unknown (e.g. a store built without
        # paths in a test) to keep the file clean.
        if self.original_file is not None:
            data["original_file"] = self.original_file
        if self.translation_file is not None:
            data["translation_file"] = self.translation_file
        data["anchors"] = [
            {"original": o, "translation": t} for o, t in self.anchors
        ]
        scroll = {}
        for surface, (original, translation) in self.scroll.items():
            side = {}
            original_dict = self._scroll_dict(original)
            translation_dict = self._scroll_dict(translation)
            if original_dict is not None:
                side["original"] = original_dict
            if translation_dict is not None:
                side["translation"] = translation_dict
            if side:
                scroll[surface] = side
        if scroll:
            data["scroll"] = scroll
        if self.normalise:
            data["normalise"] = dict(self.normalise)
        # Only non-default sides are written, so the file stays clean and a
        # reset removes the key rather than leaving a block of ones behind.
        scale = {
            side: spec.to_dict()
            for side, spec in self.normalise_scale.items()
            if not spec.is_default
        }
        if scale:
            data["normalise_scale"] = scale
        return data

    def save(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
        self.save_worker = SaveWorker(self.filepath, self._serialise())
        self.save_worker.start()

    def shutdown(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
