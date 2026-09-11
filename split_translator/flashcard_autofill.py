"""One search's worth of passive filling: what may still be written, and where.

The dictionary pages take seconds to load, so the fills a search sets off do not
all arrive at once. The search box seeds the headword straight away, the book
match follows quickly, and the Cambridge grab lands whenever the page finishes.
In between, the user is already typing. This object is what lets those two
happen at the same time: it holds a round of passive fills open across that gap,
and closes the individual targets the user has taken over in the meantime.

Two separate questions, which used to share one boolean and got in each other's
way:

  * Is this card open to passive filling at all? Asked once, when the round
    starts. A card that already carried unsaved edits at that moment stays out
    of the round entirely, so a search made while editing never writes into it.
  * May this particular target still be written? Asked at each fill. A target
    the user has typed into is theirs for the rest of the round, and the others
    keep filling around it.

A target stays taken for the whole round even if the user empties it again: a
field is never rewritten under someone who has been in it. The next round (a
search, a New card or a clear) starts from a clean sheet. A load or a save
shuts the round instead: a saved card takes no passive fill at all.

No Qt import, so this unit-tests headless like flashcard_editor_state and
flashcard_fields."""

from dataclasses import dataclass, field


class Target:
    """Everything a passive fill can write, one name each.

    The text fields share their names with ``flashcard_fields.CARD_FIELDS``,
    which is what lets each field name its own target from the one wiring loop
    that builds it. The audio clips and the first example are not registry
    fields, so they are named here alone."""

    HEADWORD = "headword"
    SPELLING_UK = "spelling_uk"
    SPELLING_US = "spelling_us"
    IPA_UK = "ipa_uk"
    IPA_US = "ipa_us"
    AUDIO_UK = "audio_uk"
    AUDIO_US = "audio_us"
    #: The first sense's first example, which the book-sentence fill owns.
    EXAMPLE = "example"

    @classmethod
    def audio(cls, region: str) -> str:
        """The audio target for a region ("uk"/"us"), so the callers that
        already branch on the region do not spell the names out again."""
        return cls.AUDIO_UK if region == "uk" else cls.AUDIO_US

    @classmethod
    def ipa(cls, region: str) -> str:
        """The IPA target for a region, the notation half of ``audio``."""
        return cls.IPA_UK if region == "uk" else cls.IPA_US


@dataclass
class AutofillRound:
    """The passive fills' permission to write, target by target."""

    #: False while the round is shut: no target may be filled, whatever the
    #: user has or has not touched. A fresh object starts open, because a fresh
    #: editor holds a fresh unaltered card.
    is_open: bool = True
    _taken: set = field(default_factory=set, repr=False)

    def restart(self) -> None:
        """Begin a round with every target free again."""
        self.is_open = True
        self._taken.clear()

    def close(self) -> None:
        """Shut the round. Nothing is filled until the next restart."""
        self.is_open = False
        self._taken.clear()

    def take(self, target: str) -> None:
        """Record that the user has taken a target over by hand. Unknown or
        blank names are ignored, so a caller may pass a field's name without
        first checking whether any fill writes there."""
        if target:
            self._taken.add(target)

    def is_taken(self, target: str) -> bool:
        return target in self._taken

    def allows(self, target: str) -> bool:
        """May a passive fill write this target now?"""
        return self.is_open and target not in self._taken
