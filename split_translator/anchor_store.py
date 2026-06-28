"""Persists content-anchor pairs for one book pair to a JSON file, off the UI
thread. Mirrors the flashcard/history store pattern (tolerant load, background
SaveWorker, in-flight write awaited on shutdown)."""

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QThread

SCHEMA_VERSION = 1


def anchor_path_for(
    original_path: str, translation_path: str, root: Path
) -> Path:
    """Return the per-book-pair anchor file path, keyed by the two book paths."""
    key = hashlib.sha1(
        f"{original_path}\n{translation_path}".encode("utf-8")
    ).hexdigest()[:16]
    return root / f".translation_tool_anchors_{key}.json"


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


def write_anchors(filepath: Path, data: dict) -> None:
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

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.save_worker = None
        self.anchors: list[tuple[str, str]] = load_anchors(filepath)
        # Last-known scroll position per surface (reader / editor), each an
        # (original, translation) pair, restored on the next launch.
        self.scroll: dict[str, _ScrollPair] = load_scroll(filepath)

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

    @staticmethod
    def _scroll_dict(position: tuple[str, float] | None) -> dict | None:
        if position is None:
            return None
        return {"id": position[0], "fraction": position[1]}

    def _serialise(self) -> dict:
        data = {
            "version": SCHEMA_VERSION,
            "anchors": [
                {"original": o, "translation": t} for o, t in self.anchors
            ],
        }
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
        return data

    def save(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
        self.save_worker = SaveWorker(self.filepath, self._serialise())
        self.save_worker.start()

    def shutdown(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
