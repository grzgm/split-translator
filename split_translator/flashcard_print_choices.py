"""Which examples the user chose to print for a card, for this session only.

Pure logic with no Qt import, so it unit-tests headless like
flashcard_print_layout. The print window builds one of these and it dies with
the window: nothing is persisted, so flashcards.json is untouched and there is
no schema change.

A card is in one of two modes. In "auto" it prints whatever the browser's fit
measurement keeps, which is the default the app has always produced. In
"manual" it prints exactly the pairs the user ticked, and the fit is skipped
for it.

A choice is keyed by (sense index, example index) rather than by sentence text.
That is safe because a choice is dropped the moment its card's examples change
(see drop_stale), so an index can never come to mean a different sentence."""

from .flashcard_print_layout import example_sense_order
from .flashcards import Card

AUTO = "auto"
MANUAL = "manual"


def auto_pairs(card: Card) -> list[tuple[int, int]]:
    """Every (sense index, example index) pair on the card, in reading order.

    These are the ticks shown for a card with no fit measurement of its own,
    for example one that is not in the print selection and so never reaches the
    preview to be measured."""
    return [(sense, index) for sense, index, _text in example_sense_order(card)]


def example_snapshot(card: Card) -> tuple:
    """The card's example text as a hashable value, used to notice that the
    card has been edited since a choice was recorded against it."""
    return tuple(tuple(sense.examples or []) for sense in (card.senses or []))


class PrintChoices:
    """The hand-picked example sets, by card id. A card absent from here is in
    auto mode, which is the default for every card."""

    def __init__(self):
        self._manual: dict[str, set[tuple[int, int]]] = {}
        self._snapshots: dict[str, tuple] = {}

    def mode_of(self, card_id: str) -> str:
        return MANUAL if card_id in self._manual else AUTO

    def chosen_for(self, card_id: str) -> set[tuple[int, int]] | None:
        """The card's hand-picked set, or None when it is in auto mode.

        None and an empty set mean different things: None leaves the card to
        the browser fit, while an empty set is a deliberate "print no examples"
        and is honoured as such."""
        chosen = self._manual.get(card_id)
        # A copy, so a caller ticking and unticking cannot rewrite the stored
        # choice behind this object's back.
        return set(chosen) if chosen is not None else None

    def set_manual(self, card: Card, pairs) -> None:
        """Record an explicit set for the card, switching it to manual mode.
        The card's examples are snapshotted alongside, so a later edit can be
        noticed by drop_stale."""
        self._manual[card.id] = set(pairs)
        self._snapshots[card.id] = example_snapshot(card)

    def reset(self, card_id: str) -> None:
        """Return the card to auto mode (a no-op when it is already auto)."""
        self._manual.pop(card_id, None)
        self._snapshots.pop(card_id, None)

    def as_render_map(self) -> dict[str, set[tuple[int, int]]]:
        """The manual cards, in the shape render_html expects. Auto cards are
        absent, which is what leaves them to the fit."""
        return {card_id: set(pairs) for card_id, pairs in self._manual.items()}

    def drop_stale(self, cards: list[Card]) -> list[str]:
        """Drop the choice of every card whose examples no longer match the
        snapshot taken when the choice was made, and of every card that has
        gone from the store entirely. Returns the dropped ids.

        This is called on every store change, so it covers edits made anywhere:
        the print window's own editor, the flashcard dock and the graph window
        alike. A change that touches no example (flipping printed or starred)
        leaves the snapshot equal and so keeps the choice."""
        by_id = {card.id: card for card in cards}
        dropped = []
        for card_id in list(self._manual):
            card = by_id.get(card_id)
            if card is None or example_snapshot(card) != self._snapshots.get(card_id):
                self.reset(card_id)
                dropped.append(card_id)
        return dropped
