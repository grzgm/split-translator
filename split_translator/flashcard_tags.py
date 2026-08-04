"""The tag vocabulary for flashcards: what a tag looks like, how a field of them
parses, and how a book path becomes its automatic tag.

Pure string logic, no Qt and no imports from the rest of the package, so it is
directly unit testable. This module is the single source of truth for tag shape:
every tag stored on a card has passed through normalise_tag."""

import re
from pathlib import Path

# The automatic source-book tag carries this prefix so it stays distinguishable
# from a hand-typed one: duplicates can be spotted, and typing "book:" into the
# saved-cards filter narrows the list to every card with a recorded source.
BOOK_TAG_PREFIX = "book:"

# Commas separate tags and whitespace inside one is not significant, so both are
# collapsed to a single space. This is what guarantees a stored tag can never
# contain a comma, and so that a field of tags round-trips through parse_tags.
_SEPARATORS_RE = re.compile(r"[,\s]+")


def normalise_tag(text: str) -> str:
    """One tag in canonical form: lowercase, no surrounding whitespace, and any
    run of commas or whitespace inside it collapsed to a single space. Blank
    input gives an empty string."""
    return _SEPARATORS_RE.sub(" ", text).strip().lower()


def parse_tags(text: str) -> list[str]:
    """The editor's comma-separated field as canonical tags: blanks dropped and
    duplicates removed, keeping the order they were first typed in."""
    return _clean(text.split(","))


def parse_tag_list(values) -> list[str]:
    """The same cleaning for a sequence read off disk. Entries that are not
    strings are dropped (so a null in a hand-edited file does not become the tag
    "none"), and a value that is not a list or tuple gives no tags at all rather
    than raising, matching the tolerant-load contract of the store."""
    if not isinstance(values, (list, tuple)):
        return []
    return _clean(values)


def _clean(values) -> list[str]:
    tags: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        tag = normalise_tag(value)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def format_tags(tags: list[str]) -> str:
    """Canonical tags as the one comma-separated line the editor field holds."""
    return ", ".join(tags)


def book_tag(path: str) -> str:
    """The automatic tag for a book file: its name without the extension,
    normalised and prefixed. An empty or stem-less path gives an empty string,
    so a misconfigured book path adds no tag rather than a bare "book:"."""
    if not path:
        return ""
    stem = normalise_tag(Path(path).stem)
    return BOOK_TAG_PREFIX + stem if stem else ""
