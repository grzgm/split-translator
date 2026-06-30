"""Flashcard storage: dataclasses and a JSON-backed store with a background save worker."""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThread

SCHEMA_VERSION = 2

# The four shipped link types: (key, display label, edge colour). Synonym,
# Similar and Related form a green gradient (intensity = closeness in meaning,
# Synonym closest); Antonym is red. This list is the single source of truth for
# the editor dropdown, the graph legend and the edge colours. Link.type is a
# free-form string in storage, so a type not in this list still round-trips; the
# UI falls back to its raw string and a neutral colour. Add a type later by
# appending one tuple here.
LINK_TYPES = [
    ("synonym", "Synonym", "#1b7a2f"),
    ("similar", "Similar", "#4caf50"),
    ("related", "Related", "#a5d6a7"),
    ("antonym", "Antonym", "#f44336"),
]
LINK_TYPE_KEYS = {key for key, _label, _colour in LINK_TYPES}
LINK_FALLBACK_COLOUR = "#888888"


@dataclass
class Sense:
    """One meaning of a word: a part of speech bound to a Polish and an English
    text, plus any usage examples that belong to that meaning."""

    pos: str = ""
    polish: str = ""
    english: str = ""
    examples: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return (
            not self.polish.strip()
            and not self.english.strip()
            and not any(e.strip() for e in self.examples)
        )

    def to_dict(self) -> dict:
        return {
            "pos": self.pos,
            "polish": self.polish,
            "english": self.english,
            "examples": list(self.examples),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Sense":
        return cls(
            pos=data.get("pos", ""),
            polish=data.get("polish", ""),
            english=data.get("english", ""),
            examples=list(data.get("examples", [])),
        )


@dataclass
class Card:
    """A vocabulary card: one headword with optional spellings, pronunciation and senses."""

    headword: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    spelling_uk: str | None = None
    spelling_us: str | None = None
    ipa_uk: str | None = None
    ipa_us: str | None = None
    own_notation: str | None = None
    audio_uk_url: str | None = None
    audio_us_url: str | None = None
    senses: list[Sense] = field(default_factory=list)
    starred: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "headword": self.headword,
            "spelling_uk": self.spelling_uk,
            "spelling_us": self.spelling_us,
            "ipa_uk": self.ipa_uk,
            "ipa_us": self.ipa_us,
            "own_notation": self.own_notation,
            "audio_uk_url": self.audio_uk_url,
            "audio_us_url": self.audio_us_url,
            "senses": [s.to_dict() for s in self.senses],
            "starred": self.starred,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            headword=data.get("headword", ""),
            spelling_uk=data.get("spelling_uk"),
            spelling_us=data.get("spelling_us"),
            ipa_uk=data.get("ipa_uk"),
            ipa_us=data.get("ipa_us"),
            own_notation=data.get("own_notation"),
            audio_uk_url=data.get("audio_uk_url"),
            audio_us_url=data.get("audio_us_url"),
            senses=[Sense.from_dict(s) for s in data.get("senses", [])],
            starred=bool(data.get("starred", False)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class Link:
    """A symmetric, typed relationship between two cards (by id). a_id/b_id are
    held in canonical (sorted) order so a pair has exactly one representation and
    (A,B) equals (B,A). type is a free-form string."""

    a_id: str
    b_id: str
    type: str

    def __post_init__(self):
        if self.a_id > self.b_id:
            self.a_id, self.b_id = self.b_id, self.a_id

    def to_dict(self) -> dict:
        return {"a_id": self.a_id, "b_id": self.b_id, "type": self.type}

    @classmethod
    def from_dict(cls, data: dict) -> "Link":
        return cls(
            a_id=data.get("a_id", ""),
            b_id=data.get("b_id", ""),
            type=data.get("type", ""),
        )


def serialise_cards(cards: list[Card], links: list["Link"] | None = None) -> dict:
    """Build the on-disk JSON structure from cards and their links."""
    return {
        "version": SCHEMA_VERSION,
        "cards": [c.to_dict() for c in cards],
        "links": [link.to_dict() for link in (links or [])],
    }


def load_flashcards(filepath: Path) -> tuple[list[Card], list["Link"]]:
    """Load cards and links, tolerating a missing or malformed file by returning
    ([], []). A v1 file (no links key) loads with an empty link list. Links that
    reference a card id not present are dropped (dangling-link pruning)."""
    if not filepath.exists():
        return [], []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], []
    cards = [Card.from_dict(c) for c in raw.get("cards", [])]
    ids = {c.id for c in cards}
    links = []
    for entry in raw.get("links", []):
        link = Link.from_dict(entry)
        if link.a_id in ids and link.b_id in ids:
            links.append(link)
    return cards, links


def load_cards(filepath: Path) -> list[Card]:
    """Load only the cards (links ignored). Kept for callers that do not need
    links."""
    return load_flashcards(filepath)[0]


def write_cards(filepath: Path, data: dict) -> None:
    """Write the serialised structure to disk (runs on the worker thread)."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SaveWorker(QThread):
    """Writes flashcards to disk off the UI thread."""

    def __init__(self, filepath: Path, data: dict):
        super().__init__()
        self.filepath = filepath
        self.data = data

    def run(self):
        write_cards(self.filepath, self.data)


class FlashcardStore:
    """Owns the in-memory card list and persists it to a JSON file."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.save_worker = None
        self.cards = load_cards(filepath)

    def add_card(self, card: Card) -> None:
        self.cards.insert(0, card)
        self.save()

    def update_card(self, card: Card) -> bool:
        """Replace the stored card sharing this card's id (used when a saved card
        is loaded into the editor, edited and saved again). Returns True if a
        match was found and replaced, False otherwise."""
        for i, existing in enumerate(self.cards):
            if existing.id == card.id:
                self.cards[i] = card
                self.save()
                return True
        return False

    def save(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
        self.save_worker = SaveWorker(self.filepath, serialise_cards(self.cards))
        self.save_worker.start()

    def shutdown(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
