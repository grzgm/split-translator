"""Which sentence of the other edition answers a sentence of this one.

Sync and search marks work in paragraphs: an anchor group says that these
original paragraphs correspond to those translation paragraphs (see
anchor_groups and book_sync). This goes one level down, inside a group, to say
which sentence of it answers which. The group is the whole context: both sides
are known to say the same thing, so the question is never whether two
sentences belong together but where the other side was cut.

The cutting is worked out by the aligner (book_align.align_sentences), not by
counting sentences and not by taking a share of the text. Counting assumes the
translator kept one sentence per sentence; a share of the characters assumes
the text is spread evenly across them. Measured over the manual anchors of a
real book pair, two thirds of groups hold the same number of sentences on both
sides, a quarter differ by one and a tenth by more, usually because the
translation splits a line of dialogue in two, which breaks both assumptions at
once. Comparing lengths the way the aligner does gets those right.

Pure logic with no Qt import, so it unit-tests headless."""

import re

from .book_align import align_sentences

# A sentence ends at . ! or ? followed by whitespace or the end of the text.
# _SENTENCE_BOUNDS_JS in book_view cuts the page's own text by the same rule,
# the way _FOLD_JS mirrors book_align.fold. The two must agree, so every mark
# carries the sentence count it was worked out from and the page marks nothing
# when its own count differs (see BookView.mark_sentence).
_END = re.compile(r"[.!?](?=\s|$)")


def split(text: str) -> list[str]:
    """The text cut into sentences, each keeping its terminator and stripped of
    surrounding space. Always at least one, so a paragraph of one sentence
    reports a count of 1, which means there is nothing to distinguish inside
    it.

    Abbreviations are cut too ("Mr. Smith" is two sentences). That is left
    alone on purpose: the page cuts identically, so the two sides agree on
    what sentence 3 is, and the aligner absorbs the extra piece as a
    one-to-two bead instead of running out of step the way counting would."""
    pieces, start = [], 0
    for match in _END.finditer(text):
        piece = text[start : match.end()].strip()
        if piece:
            pieces.append(piece)
        start = match.end()
    rest = text[start:].strip()
    if rest:
        pieces.append(rest)
    return pieces or [text]


def counterpart_sentence(
    texts_here: list[str],
    texts_there: list[str],
    paragraph: int,
    index: int,
    count: int,
) -> tuple[int, int, int] | None:
    """The sentence to mark on the other side of a group, as the paragraph it
    sits in (a position in `texts_there`), its index in that paragraph, and how
    many sentences that paragraph holds.

    `texts_here` and `texts_there` are one group's paragraph texts, in order.
    `paragraph` and `index` locate the sentence on this side, and `count` is
    how many sentences the page counted in that paragraph: a count that does
    not match this side's own cutting means the index may not refer to the same
    sentence, so nothing is marked.

    None when there is nothing to mark: an unknown paragraph or index, a count
    that disagrees, a translation that dropped the sentence, or a group whose
    other side holds a single sentence, where a mark would only repaint the
    paragraph that is already marked."""
    if not texts_here or not texts_there:
        return None
    if not 0 <= paragraph < len(texts_here):
        return None
    here = [split(text) for text in texts_here]
    there = [split(text) for text in texts_there]
    if len(here[paragraph]) != count or not 0 <= index < count:
        return None
    flat_there = [sentence for group in there for sentence in group]
    if len(flat_there) <= 1:
        return None
    flat_here = [sentence for group in here for sentence in group]
    target = _answering(
        flat_here, flat_there, sum(len(group) for group in here[:paragraph]) + index
    )
    if target is None:
        return None
    for position, group in enumerate(there):
        if target < len(group):
            return (position, target, len(group))
        target -= len(group)
    return None


def _answering(here: list[str], there: list[str], index: int) -> int | None:
    """The sentence of `there` that answers `here[index]`: the first one of the
    bead covering it, so a sentence split in two is answered by the half it
    starts in. None when the bead covers nothing on the other side, which is a
    sentence the translation left out."""
    for first, last, other_first, other_last in align_sentences(here, there):
        if first <= index < last:
            return other_first if other_last > other_first else None
    return None
