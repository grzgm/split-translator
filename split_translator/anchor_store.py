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


def load_anchors(filepath: Path) -> list[tuple[str, str]]:
    """Load anchor pairs, tolerating a missing or malformed file by returning []."""
    if not filepath.exists():
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return [
        (pair["original"], pair["translation"])
        for pair in raw.get("anchors", [])
        if "original" in pair and "translation" in pair
    ]


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

    def _serialise(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "anchors": [
                {"original": o, "translation": t} for o, t in self.anchors
            ],
        }

    def save(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
        self.save_worker = SaveWorker(self.filepath, self._serialise())
        self.save_worker.start()

    def shutdown(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
