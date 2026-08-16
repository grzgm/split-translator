"""Declarative list of the flashcard editor's card-level text fields.

One entry per field carries everything the editor needs: what the widget is
called, what it shows while empty, what it explains on hover, whether editing it
means the printed paper copy is out of date, and how its text maps to and from a
Card. Construction, the empty marker, the altered flagging, clearing, loading
and saving all loop over this list, so adding a field is one entry instead of an
edit in six places. That is not hypothetical: the Tags field was added to five
of those places and missed in has_content.

The registry covers card-level text fields only. Audio URLs, the star and
printed toggles and the sense rows are not text fields and stay hand-written.

No Qt import, so this unit-tests headless like flashcard_editor_state and
flashcard_tags."""

from collections.abc import Callable
from dataclasses import dataclass

from .flashcard_tags import format_tags, parse_tags


def _stripped(text: str) -> str:
    """Trim to plain text. For the headword, which is required and is stored as
    an empty string rather than None."""
    return text.strip()


def _strip_or_none(text: str) -> str | None:
    """Trim, storing a blank field as None: the Card's optional text fields are
    None when unset, not empty strings."""
    return text.strip() or None


def _as_text(value) -> str:
    """A Card value as editable text. None becomes an empty field."""
    return value or ""


@dataclass(frozen=True)
class CardField:
    """One editable card-level text field.

    ``name`` is both the widget stem (``spelling_uk`` gives
    ``spelling_uk_input``) and the Card attribute, so loading and saving need no
    separate mapping table. ``printed`` marks a field that appears on the
    printed card: editing it clears the printed flag as well as marking the card
    altered, because the paper copy stops matching the card."""

    name: str
    placeholder: str = ""
    tooltip: str = ""
    printed: bool = False
    to_card: Callable[[str], object] = _strip_or_none
    from_card: Callable[[object], str] = _as_text

    @property
    def attr(self) -> str:
        """The editor attribute holding this field's widget."""
        return f"{self.name}_input"


_SPELLING_TOOLTIP = "New: filled from the Cambridge page (when it differs UK/US)"
_IPA_TOOLTIP = "New: filled from the Cambridge page"

#: Every card-level text field, in the order the editor shows them.
CARD_FIELDS = (
    CardField(
        "headword",
        tooltip="Ctrl+N: fill from the search box (the New button)",
        printed=True,
        to_card=_stripped,
    ),
    CardField(
        "spelling_uk", placeholder="UK spelling", tooltip=_SPELLING_TOOLTIP
    ),
    CardField(
        "spelling_us", placeholder="US spelling", tooltip=_SPELLING_TOOLTIP
    ),
    CardField("ipa_uk", placeholder="IPA UK", tooltip=_IPA_TOOLTIP),
    CardField("ipa_us", placeholder="IPA US", tooltip=_IPA_TOOLTIP),
    CardField("own_notation", printed=True),
    CardField(
        "tags",
        placeholder="comma separated",
        tooltip=(
            "Free-form labels, comma separated. The book a card's example came "
            "from is recorded here automatically."
        ),
        to_card=parse_tags,
        from_card=format_tags,
    ),
)
