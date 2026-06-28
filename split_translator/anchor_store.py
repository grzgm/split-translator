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


def load_scroll(filepath: Path) -> tuple[
    tuple[str, float] | None, tuple[str, float] | None
]:
    """Load the saved (original, translation) scroll positions, each or None.
    A file written before scroll positions existed has no "scroll" key, so both
    sides come back None."""
    scroll = _load_raw(filepath).get("scroll", {})
    if not isinstance(scroll, dict):
        return (None, None)
    return (
        _parse_scroll(scroll.get("original")),
        _parse_scroll(scroll.get("translation")),
    )


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
        # Last-known scroll position per edition, restored on the next launch.
        self.original_scroll, self.translation_scroll = load_scroll(filepath)

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

    def set_scroll(
        self,
        original: tuple[str, float] | None,
        translation: tuple[str, float] | None,
    ) -> None:
        """Store both editions' scroll positions and persist. Pass None for a
        side whose position is unknown (it is then not restored)."""
        self.original_scroll = original
        self.translation_scroll = translation
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
        original = self._scroll_dict(self.original_scroll)
        translation = self._scroll_dict(self.translation_scroll)
        if original is not None:
            scroll["original"] = original
        if translation is not None:
            scroll["translation"] = translation
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
