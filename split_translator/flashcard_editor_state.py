"""Pure-logic editor state for the flashcard panel.

One small object answers the questions the editor keeps asking: which mode is
the editor in (building a new card, or editing a saved one), has the user
altered the current card since it was last loaded, cleared or saved, and which
of the passive fills' targets are still free to write. The last of those lives
in its own AutofillRound (see flashcard_autofill), held here because the round
is settled exactly where the altered baseline is reset: a clear opens a fresh
one, and a load or a save shuts it. No Qt import, so it unit-tests headless like
page_mapper and graph_layout. The panel holds exactly one instance and every
mode/altered decision reads it."""

from collections.abc import Callable
from dataclasses import dataclass, field

from .flashcard_autofill import AutofillRound


@dataclass
class EditorState:
    """The editor's mode and altered baseline.

    mode is "new" while building a fresh card and "editing" while a saved card
    is loaded. loaded_card_id and loaded_created_at carry the saved card's id
    and original creation time so Save updates it in place and keeps its
    timestamp. altered is True once the user changes anything since the last
    load, clear or save; programmatic fills never set it.

    altered is a property rather than a plain field so every change to it runs
    through one place. Setting it fires on_altered_changed, but only when the
    flag actually flips, so a listener hears one notification per transition and
    not one per keystroke. That is what lets the panel announce "this card has
    unsaved edits" without every writer here having to remember to.

    printed_flag_altered is altered again, one level down, for the card's
    printed flag: True once the user has changed that flag by hand since the
    same baseline. It is needed because editing anything that appears on the
    printed card clears the flag by itself (the paper copy stops matching the
    card the moment it changes), and that automatic clear must not undo a
    deliberate choice.

    autofill is altered a third time, one level finer: which individual fill
    targets the user has taken over, rather than whether they have touched
    anything at all. altered still says "this card has unsaved edits" for the
    dock title and the discard prompts; the round says which passive fills may
    still write, which is what lets the pages keep filling around what is being
    typed while they load."""

    mode: str = "new"
    loaded_card_id: str | None = None
    loaded_created_at: str | None = None
    #: True once the user has set the printed flag by hand for the card now in
    #: the editor. Cleared by to_new and to_editing, so every load, clear and
    #: save starts from a fresh baseline, exactly like altered.
    printed_flag_altered: bool = False
    #: Called with the new value whenever altered flips. Stays a plain callable
    #: rather than a Qt signal so this module keeps its no-Qt, headless-testable
    #: character; the panel adapts it to a signal.
    on_altered_changed: Callable[[bool], None] | None = None
    #: The passive fills' permission to write. Restarted by to_new, so a clear
    #: or New opens a fresh round with every target free; shut by to_editing,
    #: so a saved card, just loaded or just saved, takes no passive fill until
    #: a search or New replaces it.
    autofill: AutofillRound = field(default_factory=AutofillRound)
    _altered: bool = field(default=False, repr=False)

    @property
    def altered(self) -> bool:
        return self._altered

    @altered.setter
    def altered(self, value: bool) -> None:
        value = bool(value)
        if value == self._altered:
            return
        self._altered = value
        if self.on_altered_changed is not None:
            self.on_altered_changed(value)

    @property
    def is_new(self) -> bool:
        return self.mode == "new"

    @property
    def is_editing(self) -> bool:
        return self.mode == "editing"

    def to_new(self) -> None:
        """Reset to building a fresh, unaltered card."""
        self.mode = "new"
        self.loaded_card_id = None
        self.loaded_created_at = None
        self.altered = False
        self.printed_flag_altered = False
        self.autofill.restart()

    def to_editing(self, card_id: str, created_at: str | None) -> None:
        """Enter editing a saved card. A freshly loaded card is a clean
        baseline, so altered is cleared.

        The passive fills are shut out of it. What a saved card holds was
        chosen and saved, and the fills that keep arriving afterwards are not
        about it: the book search a load starts, every F3 through the matches,
        the page grab when the dock is shown. Only what the user does changes
        it (typing, a capture, Fill). A search or New replaces the card with a
        fresh one, and that one takes part again."""
        self.mode = "editing"
        self.loaded_card_id = card_id
        self.loaded_created_at = created_at
        self.altered = False
        self.printed_flag_altered = False
        self.autofill.close()

    def begin_autofill(self) -> bool:
        """Open a round of passive fills, and say whether it opened.

        A search or a New card starts one. It opens only on a card with no
        unsaved edits: a card already being edited is left out of the round
        entirely, so a search made mid-edit never writes into it. Within an
        open round each target fills until the user takes it over, which is
        what lets the fields be typed while the pages are still loading."""
        if self.altered:
            self.autofill.close()
            return False
        self.autofill.restart()
        return True

    def mark_altered(self, target: str = "") -> None:
        """Record a genuine user edit.

        target names the fill target the edit landed on, where the caller knows
        it, so later passive fills skip that one and keep filling the rest. An
        edit with no target (a staged link, the printed toggle) still alters the
        card but leaves every fill free."""
        self.altered = True
        self.autofill.take(target)

    def mark_printed_flag_altered(self) -> None:
        """Record that the user set the printed flag by hand."""
        self.printed_flag_altered = True
