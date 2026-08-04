"""Flashcard storage: dataclasses and a JSON-backed store with a background save worker."""

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .flashcard_tags import parse_tag_list

# Cards file schema. v4 added the per-card "tags" array; v3 dropped the embedded
# "links" array (links live in their own file now, see LINKS_SCHEMA_VERSION).
# load_cards ignores the version field, so there is no migration code at all: an
# older file simply loads with no tags and is rewritten in the current shape on
# the next save.
SCHEMA_VERSION = 4
LINKS_SCHEMA_VERSION = 1

# The links file lives beside the cards file under this name when the store is
# not given an explicit links path.
DEFAULT_LINKS_FILENAME = "flashcard_links.json"

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
    printed: bool = False
    tags: list[str] = field(default_factory=list)
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
            "printed": self.printed,
            "tags": list(self.tags),
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
            printed=bool(data.get("printed", False)),
            tags=parse_tag_list(data.get("tags", [])),
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


# A headword occurrence in an English definition is stored as this literal
# token. Printing decides whether to show it as a blank or as the token itself.
REDACTION_TOKEN = "{{word}}"

# Short inflections kept after the token, so "cats" stores as "{{word}}s". This
# is a whole-remainder membership test, not a longest-prefix match.
_INFLECTION_SUFFIXES = frozenset({"s", "es", "ed", "d", "ing"})

# One whole word: letters, with internal hyphens or apostrophes (so "well-being"
# and "don't" are single tokens and are matched or skipped as a unit).
_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


def headword_forms(card: Card) -> list[str]:
    """The lowercase surface forms to redact: the headword and its UK/US
    spellings, non-empty and de-duplicated, longest first so a longer spelling
    is tried before a shorter one it contains."""
    forms: list[str] = []
    for value in (card.headword, card.spelling_uk, card.spelling_us):
        if value:
            low = value.strip().lower()
            if low and low not in forms:
                forms.append(low)
    forms.sort(key=len, reverse=True)
    return forms


def redact_headword(text: str, forms: list[str]) -> str:
    """Replace whole-word headword occurrences in text with REDACTION_TOKEN,
    keeping a short inflection suffix (so "cats" becomes "{{word}}s"). Matching is
    case-insensitive. Existing tokens are never re-processed, so calling this on
    already-redacted text is a no-op."""
    if not text or not forms:
        return text

    def replace_word(match: "re.Match[str]") -> str:
        word = match.group(0)
        low = word.lower()
        for form in forms:
            if low == form:
                return REDACTION_TOKEN
        for form in forms:
            if low.startswith(form):
                suffix = word[len(form):]
                if suffix.lower() in _INFLECTION_SUFFIXES:
                    return REDACTION_TOKEN + suffix
        return word

    segments = text.split(REDACTION_TOKEN)
    redacted = [_WORD_RE.sub(replace_word, segment) for segment in segments]
    return REDACTION_TOKEN.join(redacted)


def redact_card_definitions(card: Card) -> None:
    """Rewrite every sense's English definition in place, replacing headword
    occurrences with REDACTION_TOKEN. Called on each save so stored cards carry
    tokens; idempotent, so re-saving does not change already-redacted text."""
    forms = headword_forms(card)
    if not forms:
        return
    for sense in card.senses:
        sense.english = redact_headword(sense.english, forms)


def serialise_cards(cards: list[Card]) -> dict:
    """Build the on-disk JSON structure for the cards file. Links are stored in
    their own file (see serialise_links) and never written here."""
    return {
        "version": SCHEMA_VERSION,
        "cards": [c.to_dict() for c in cards],
    }


def serialise_links(links: list["Link"]) -> dict:
    """Build the on-disk JSON structure for the separate links file."""
    return {
        "version": LINKS_SCHEMA_VERSION,
        "links": [link.to_dict() for link in links],
    }


def load_cards(filepath: Path) -> list[Card]:
    """Load cards from the cards file, tolerating a missing or malformed file by
    returning []. Any legacy 'links' key in this file is ignored: links live in
    their own file now and are only read from there (no backfill)."""
    if not filepath.exists():
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return [Card.from_dict(c) for c in raw.get("cards", [])]


def load_links(filepath: Path, valid_ids: set[str]) -> list["Link"]:
    """Load links from the separate links file, tolerating a missing or malformed
    file by returning []. Links referencing a card id not in valid_ids are dropped
    (dangling-link pruning)."""
    if not filepath.exists():
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    links = []
    for entry in raw.get("links", []):
        link = Link.from_dict(entry)
        if link.a_id in valid_ids and link.b_id in valid_ids:
            links.append(link)
    return links


def write_cards(filepath: Path, data: dict) -> None:
    """Write a serialised store structure (cards or links) to disk (runs on the
    worker thread)."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SaveWorker(QThread):
    """Writes the cards file and the links file to disk off the UI thread. Both
    are written on every save (unified write); the files are small."""

    def __init__(
        self,
        cards_file: Path,
        cards_data: dict,
        links_file: Path,
        links_data: dict,
    ):
        super().__init__()
        self.cards_file = cards_file
        self.cards_data = cards_data
        self.links_file = links_file
        self.links_data = links_data

    def run(self):
        write_cards(self.cards_file, self.cards_data)
        write_cards(self.links_file, self.links_data)


class _StoreSignals(QObject):
    """Holds the store's Qt signal. FlashcardStore is a plain object so it can be
    built off the UI thread and in tests without a QApplication; the signal lives
    on this tiny QObject and is re-exposed as store.cards_changed."""

    cards_changed = Signal()


class FlashcardStore:
    """Owns the in-memory card list and links, and persists them to two JSON
    files: the cards in filepath and the links (which reference cards by id) in a
    separate links_filepath. When links_filepath is not given it defaults to a
    sibling of the cards file named DEFAULT_LINKS_FILENAME."""

    def __init__(self, filepath: Path, links_filepath: Path | None = None):
        self.filepath = filepath
        self.links_filepath = links_filepath or filepath.parent / DEFAULT_LINKS_FILENAME
        self.save_worker = None
        self.cards = load_cards(self.filepath)
        self.links = load_links(self.links_filepath, {c.id for c in self.cards})
        self._signals = _StoreSignals()
        self.cards_changed = self._signals.cards_changed

    def add_card(self, card: Card) -> None:
        redact_card_definitions(card)
        self.cards.insert(0, card)
        self.save()

    def update_card(self, card: Card) -> bool:
        """Replace the stored card sharing this card's id (used when a saved card
        is loaded into the editor, edited and saved again). Returns True if a
        match was found and replaced, False otherwise."""
        redact_card_definitions(card)
        for i, existing in enumerate(self.cards):
            if existing.id == card.id:
                self.cards[i] = card
                self.save()
                return True
        return False

    def delete_card(self, card_id: str) -> bool:
        """Remove the card with this id, and every link touching it, in one save.

        The links go with the card rather than being left to the load-time prune,
        so the in-memory list and the file agree the moment the card is gone.
        Returns True when a card was actually removed, so deleting an id that is
        no longer there does not churn disk or UI."""
        remaining = [c for c in self.cards if c.id != card_id]
        if len(remaining) == len(self.cards):
            return False
        self.cards = remaining
        self.links = [l for l in self.links if card_id not in (l.a_id, l.b_id)]
        self.save()
        return True

    def set_printed(self, card_ids, value: bool) -> bool:
        """Set the printed flag to value on every card whose id is in card_ids.
        Does one disk write and emits cards_changed once. Returns True when at
        least one card actually changed, so a no-op does not churn disk or UI."""
        wanted = set(card_ids)
        changed = False
        for card in self.cards:
            if card.id in wanted and card.printed != value:
                card.printed = value
                changed = True
        if changed:
            self.save()
        return changed

    def links_for(self, card_id: str) -> list[Link]:
        return [l for l in self.links if card_id in (l.a_id, l.b_id)]

    def set_links_for(self, card_id: str, new_links: list[Link]) -> None:
        """Replace every link touching card_id with new_links. Each new link must
        touch card_id. Symmetric pairs are deduplicated by (a_id, b_id)."""
        kept = [l for l in self.links if card_id not in (l.a_id, l.b_id)]
        seen = {(l.a_id, l.b_id) for l in kept}
        for link in new_links:
            key = (link.a_id, link.b_id)
            if key not in seen:
                seen.add(key)
                kept.append(link)
        self.links = kept
        self.save()

    def save_card_with_links(self, card: Card, links: list[Link]) -> None:
        """Add or update a card and replace its links in a single save.

        Mirrors update_card (replace in place when the id exists, else insert at
        the front) and set_links_for (replace every link touching card.id with
        the given list, deduped by canonical (a_id, b_id)), but performs exactly
        one disk write and emits cards_changed once. Used by the editor's Save so
        a single Save is a single disk write and a single graph refresh."""
        redact_card_definitions(card)
        replaced = False
        for i, existing in enumerate(self.cards):
            if existing.id == card.id:
                self.cards[i] = card
                replaced = True
                break
        if not replaced:
            self.cards.insert(0, card)

        kept = [l for l in self.links if card.id not in (l.a_id, l.b_id)]
        seen = {(l.a_id, l.b_id) for l in kept}
        for link in links:
            key = (link.a_id, link.b_id)
            if key not in seen:
                seen.add(key)
                kept.append(link)
        self.links = kept
        self.save()

    def save(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
        self.save_worker = SaveWorker(
            self.filepath,
            serialise_cards(self.cards),
            self.links_filepath,
            serialise_links(self.links),
        )
        self.save_worker.start()
        self.cards_changed.emit()

    def shutdown(self) -> None:
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()
