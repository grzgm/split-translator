"""Automatic anchors: the two editions' paragraphs matched by their text.

A dynamic programme pairs runs of paragraphs (beads: one original paragraph
with one translation paragraph, one with two, and so on). A bead costs more the
further its two lengths are from the usual ratio between the editions, and less
the more rare words (names, numbers) both sides share. Sure points, words rare
enough to pair with certainty, keep the programme to a band around the right
path, so a whole novel takes a few seconds.

The aligner works inside the kept ranges (see the skip fields), between fixed
groups (manual anchors, and automatic ones outside the batch), and returns
anchors only for the batch asked for. Pure logic with no Qt import, so it
unit-tests headless; the anchor editor runs it off the UI thread (see
align_worker)."""

import bisect
import collections
import math
import re
import unicodedata

from .anchor_groups import Anchor, Group

# A right single quotation mark is folded to a straight apostrophe, and a
# Polish l with stroke (which has no decomposition) to a plain l. Built with
# chr so the source stays ASCII.
_CURLY_APOSTROPHE = chr(0x2019)
_L_WITH_STROKE = chr(0x142)
_TOKEN = re.compile(
    r"[^\W\d_]+(?:['" + _CURLY_APOSTROPHE + r"][^\W\d_]+)*|\d+"
)

# How likely each bead is: (original paragraphs, translation paragraphs).
_PRIORS = {
    (1, 1): 0.80,
    (1, 2): 0.08,
    (2, 1): 0.04,
    (2, 2): 0.02,
    (1, 3): 0.02,
    (0, 1): 0.01,
    (1, 0): 0.005,
    (3, 1): 0.005,
}
_BEADS = tuple((a, b, -math.log(p)) for (a, b), p in _PRIORS.items())

_VARIANCE = 6.8  # Gale-Church length variance
_SHARED_WORDS = 3.0  # weight of the shared-word overlap
_PUNCTUATION = 0.7  # weight of differing question and exclamation marks
_BAND = 30  # paragraphs either side of the sure-point line
_MAX_DRIFT = 0.06  # how far apart a sure pair may sit, as a share of the text
_SURE_COUNT = 2  # a sure word occurs at most this often in each edition
_EDGE_COST = 0.5  # per paragraph left unmatched at a kept range's start or end
_WEIGHT_SCALE = 1000  # word weights are whole numbers, so sums never depend on order
_START = (-1, -1)  # back pointer: the path begins here after skipped paragraphs


def fold(word: str) -> str:
    """A word lower-cased, without diacritics, with apostrophes straightened."""
    word = unicodedata.normalize("NFKD", word)
    word = "".join(ch for ch in word if not unicodedata.combining(ch))
    return (
        word.lower()
        .replace(_L_WITH_STROKE, "l")
        .replace(_CURLY_APOSTROPHE, "'")
    )


def tokens(text: str) -> list[str]:
    """The words the editions are compared by: words of four or more letters
    cut to their first five, and numbers kept whole (marked with #). Shorter
    words say little across two languages and are left out."""
    result = []
    for match in _TOKEN.finditer(text):
        word = fold(match.group(0))
        if word.isdigit():
            result.append("#" + word)
        elif len(word) >= 4:
            result.append(word[:5])
    return result


class _Edition:
    """One edition's kept paragraphs, with running totals for fast bead costs."""

    def __init__(self, texts: list[str]):
        self.tokens = [tokens(text) for text in texts]
        self.lengths = [0]
        self.questions = [0]
        self.exclamations = [0]
        for text in texts:
            self.lengths.append(self.lengths[-1] + len(text))
            self.questions.append(self.questions[-1] + text.count("?"))
            self.exclamations.append(self.exclamations[-1] + text.count("!"))

    def __len__(self) -> int:
        return len(self.tokens)

    def share(self, i: int) -> float:
        """Where paragraph i starts, as a share of the edition's text."""
        return self.lengths[i] / self.lengths[-1] if self.lengths[-1] else 0.0


def _shared_vocabulary(a: _Edition, b: _Edition) -> dict[str, tuple[int, int]]:
    """Words found in both editions, with counts within a factor of two."""
    count_a = collections.Counter(t for words in a.tokens for t in words)
    count_b = collections.Counter(t for words in b.tokens for t in words)
    return {
        t: (count_a[t], count_b[t])
        for t in count_a.keys() & count_b.keys()
        if 0.5 <= count_a[t] / count_b[t] <= 2.0
    }


def _sure_points(
    a: _Edition, b: _Edition, shared: dict[str, tuple[int, int]]
) -> list[tuple[int, int]]:
    """Paragraph pairs joined by a rare word: one found once or twice, as often
    in each edition, the n-th occurrence paired with the n-th, kept when the
    two sit at nearly the same share of the text."""
    places_a = collections.defaultdict(list)
    places_b = collections.defaultdict(list)
    for places, edition in ((places_a, a), (places_b, b)):
        for i, words in enumerate(edition.tokens):
            for t in words:
                if t in shared:
                    places[t].append(i)
    points = set()
    for t, (in_a, in_b) in shared.items():
        if in_a != in_b or in_a > _SURE_COUNT:
            continue
        for i, j in zip(places_a[t], places_b[t]):
            if abs(a.share(i) - b.share(j)) <= _MAX_DRIFT:
                points.add((i, j))
    return sorted(points)


def _longest_chain(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest run of points increasing in both editions."""
    ordered = sorted(points, key=lambda p: (p[0], -p[1]))
    tails: list[int] = []
    tail_at: list[int] = []
    previous: list[int | None] = [None] * len(ordered)
    for k, (_i, j) in enumerate(ordered):
        slot = bisect.bisect_left(tails, j)
        if slot == len(tails):
            tails.append(j)
            tail_at.append(k)
        else:
            tails[slot] = j
            tail_at[slot] = k
        previous[k] = tail_at[slot - 1] if slot > 0 else None
    chain = []
    k = tail_at[-1] if tail_at else None
    while k is not None:
        chain.append(ordered[k])
        k = previous[k]
    return chain[::-1]


def _filter_chain(chain: list[tuple[int, int]], window: int = 4, slack: int = 6):
    """The chain without points that stray from the line through their
    neighbours, repeated until nothing more is dropped."""
    while True:
        kept = []
        for k, (i, j) in enumerate(chain):
            before = chain[max(0, k - window) : k]
            after = chain[k + 1 : k + 1 + window]
            if not before or not after:
                kept.append((i, j))
                continue
            (i0, j0), (i1, j1) = before[0], after[-1]
            expected = j0 + (i - i0) * (j1 - j0) / (i1 - i0)
            if abs(j - expected) <= slack + 0.05 * (i1 - i0):
                kept.append((i, j))
        if len(kept) == len(chain):
            return kept
        chain = kept


def _ratio(a: _Edition, b: _Edition, chain: list[tuple[int, int]]) -> float:
    """Translation characters per original character, measured between the
    first and last sure points, or over the whole text when they span none."""
    if len(chain) >= 2:
        (i0, j0), (i1, j1) = chain[0], chain[-1]
        span_a = a.lengths[i1] - a.lengths[i0]
        span_b = b.lengths[j1] - b.lengths[j0]
        if span_a > 0 and span_b > 0:
            return span_b / span_a
    if a.lengths[-1] > 0 and b.lengths[-1] > 0:
        return b.lengths[-1] / a.lengths[-1]
    return 1.0


def _length_cost(length_a: int, length_b: int, ratio: float) -> float:
    """Gale-Church: how unlikely the two lengths are for a true pair."""
    mean = (length_a + length_b / ratio) / 2.0
    if mean <= 0:
        return 0.0
    z = abs(length_b - length_a * ratio) / math.sqrt(mean * _VARIANCE)
    p = math.erfc(z / math.sqrt(2.0))
    return -math.log(p) if p > 1e-30 else 69.0


class _SharedWords:
    """How much of two runs' rare vocabulary they share, from 0 to 1."""

    def __init__(self, a: _Edition, b: _Edition, shared: dict):
        self._a = [frozenset(t for t in words if t in shared) for words in a.tokens]
        self._b = [frozenset(t for t in words if t in shared) for words in b.tokens]
        found_in = collections.Counter()
        for words in self._a + self._b:
            found_in.update(words)
        total = len(self._a) + len(self._b)
        self._weight = {
            t: round(_WEIGHT_SCALE * math.log(total / found_in[t]))
            for t in found_in
        }

    @staticmethod
    def _union(sets: list[frozenset], start: int, stop: int) -> frozenset:
        if stop - start == 1:
            return sets[start]
        return frozenset().union(*sets[start:stop])

    def overlap(self, a0: int, a1: int, b0: int, b1: int) -> float:
        words_a = self._union(self._a, a0, a1)
        if not words_a:
            return 0.0
        words_b = self._union(self._b, b0, b1)
        common = words_a & words_b
        if not common:
            return 0.0
        weight = self._weight
        smaller = min(
            sum(weight[t] for t in words_a), sum(weight[t] for t in words_b)
        )
        if not smaller:
            return 0.0
        return sum(weight[t] for t in common) / smaller


class _Unreachable(Exception):
    """The band was too narrow for any path to reach the end."""


def _path(n1: int, n2: int, points: list[tuple[int, int]]) -> list[float]:
    """For each original paragraph boundary 0..n1, the translation boundary on
    the line through the sure points (from 0,0 to n1,n2)."""
    xs = [0] + [p[0] for p in points] + [n1]
    ys = [0] + [p[1] for p in points] + [n2]
    path = []
    for i in range(n1 + 1):
        k = min(max(bisect.bisect_right(xs, i) - 1, 0), len(xs) - 2)
        x0, x1, y0, y1 = xs[k], xs[k + 1], ys[k], ys[k + 1]
        path.append(float(y0) if x1 == x0 else y0 + (i - x0) * (y1 - y0) / (x1 - x0))
    return path


def _align_stretch(
    a: _Edition,
    b: _Edition,
    offset_a: int,
    n1: int,
    offset_b: int,
    n2: int,
    points: list[tuple[int, int]],
    ratio: float,
    shared_words: _SharedWords,
    head: bool,
    tail: bool,
    band: int,
) -> list[tuple[int, int, int, int]]:
    """The cheapest beads through one stretch, as (a0, a1, b0, b1) in the
    stretch's own paragraph numbers. The stretch holds a's paragraphs
    offset_a..offset_a + n1 and b's offset_b..offset_b + n2.

    With `head`, paragraphs before the first sure point may be left unmatched
    at a flat cost each, and likewise after the last one with `tail`: front or
    back matter only one edition has. Raises _Unreachable when the band is too
    narrow."""
    path = _path(n1, n2, points)
    lo, hi = [], []
    for i in range(n1 + 1):
        lo.append(max(0, int(path[i]) - band))
        hi.append(min(n2, int(path[i]) + band + 1))
    lo[0], hi[n1] = 0, n2
    head = head and bool(points)
    tail = tail and bool(points)
    if head:
        first_i, first_j = points[0]
        for i in range(first_i + 1):
            lo[i], hi[i] = 0, max(hi[i], min(n2, first_j + band))
    if tail:
        last_i, last_j = points[-1]
        for i in range(last_i, n1 + 1):
            lo[i], hi[i] = min(lo[i], last_j), n2
    A = a.lengths
    B = b.lengths
    QA, QB = a.questions, b.questions
    EA, EB = a.exclamations, b.exclamations
    inf = float("inf")
    cost: list[list[float]] = []
    back: list[list] = []
    for i in range(n1 + 1):
        low, high = lo[i], hi[i]
        row = [inf] * (high - low + 1)
        row_back: list = [None] * (high - low + 1)
        if i == 0:
            row[0] = 0.0
        ai = offset_a + i
        for j in range(low, high + 1):
            best, arg = row[j - low], row_back[j - low]
            if head and i <= first_i and j <= first_j and (i or j):
                skipped = _EDGE_COST * (i + j)
                if skipped < best:
                    best, arg = skipped, _START
            bj = offset_b + j
            for da, db, prior in _BEADS:
                pi, pj = i - da, j - db
                if pi < 0 or pj < 0:
                    continue
                if da == 0:
                    if pj < low:
                        continue
                    previous = row[pj - low]
                else:
                    if pj < lo[pi] or pj > hi[pi]:
                        continue
                    previous = cost[pi][pj - lo[pi]]
                if previous == inf:
                    continue
                api, bpj = offset_a + pi, offset_b + pj
                c = previous + prior + _length_cost(A[ai] - A[api], B[bj] - B[bpj], ratio)
                if da and db:
                    c -= _SHARED_WORDS * shared_words.overlap(api, ai, bpj, bj)
                    c += _PUNCTUATION * (
                        abs((QA[ai] - QA[api]) - (QB[bj] - QB[bpj]))
                        + 0.5 * abs((EA[ai] - EA[api]) - (EB[bj] - EB[bpj]))
                    )
                if c < best:
                    best, arg = c, (pi, pj)
            row[j - low], row_back[j - low] = best, arg
        cost.append(row)
        back.append(row_back)

    end, end_cost = None, inf
    if tail:
        for i in range(last_i, n1 + 1):
            for j in range(max(lo[i], last_j), hi[i] + 1):
                c = cost[i][j - lo[i]]
                if c == inf:
                    continue
                c += _EDGE_COST * ((n1 - i) + (n2 - j))
                if c < end_cost:
                    end, end_cost = (i, j), c
    elif cost[n1][n2 - lo[n1]] < inf:
        end = (n1, n2)
    if end is None:
        raise _Unreachable()

    beads = []
    i, j = end
    while True:
        arg = back[i][j - lo[i]]
        if arg is None or arg == _START:
            break
        pi, pj = arg
        beads.append((pi, i, pj, j))
        i, j = pi, pj
    beads.reverse()
    return beads


def _stretches(
    groups: list[Group], original_kept: range, translation_kept: range
) -> list[tuple[int, int, int, int, bool, bool]]:
    """The stretches between fixed groups, in kept-range paragraph numbers:
    (a0, a1, b0, b1, touches the kept start, touches the kept end)."""
    inside = sorted(
        (g for g in groups if g.within(original_kept, translation_kept)),
        key=lambda g: (g.original_first, g.translation_first),
    )
    result = []
    a, b = 0, 0
    first = True
    for group in inside:
        result.append(
            (
                a,
                group.original_first - original_kept.start,
                b,
                group.translation_first - translation_kept.start,
                first,
                False,
            )
        )
        first = False
        a = group.original_last + 1 - original_kept.start
        b = group.translation_last + 1 - translation_kept.start
    result.append((a, len(original_kept), b, len(translation_kept), first, True))
    return result


def _bead_anchors(
    original_ids: list[str],
    translation_ids: list[str],
    a0: int,
    a1: int,
    b0: int,
    b1: int,
) -> list[Anchor]:
    """The anchors for one bead, given as positions in the full id lists. One
    paragraph against several is anchored to the first and the last of them,
    so its group covers the run; two against two are two single pairs."""
    first_a, last_a = original_ids[a0], original_ids[a1 - 1]
    first_b, last_b = translation_ids[b0], translation_ids[b1 - 1]
    anchors = [(first_a, first_b)]
    if (last_a, last_b) != (first_a, first_b):
        if a1 - a0 == 1:
            anchors.append((first_a, last_b))
        elif b1 - b0 == 1:
            anchors.append((last_a, first_b))
        else:
            anchors.append((last_a, last_b))
    return anchors


def align_batch(
    original_ids: list[str],
    original_texts: list[str],
    translation_ids: list[str],
    translation_texts: list[str],
    fixed_groups: list[Group],
    start: int,
    count: int,
    original_kept: range,
    translation_kept: range,
) -> list[Anchor]:
    """Automatic anchors for the original paragraphs at positions
    start..start + count, matched inside the kept ranges and between the fixed
    groups. A bead belongs to the batch when its first original paragraph does.
    The same inputs always give the same anchors."""
    batch = range(
        max(start, original_kept.start), min(start + count, original_kept.stop)
    )
    if not len(batch) or not len(translation_kept):
        return []
    a = _Edition(original_texts[original_kept.start : original_kept.stop])
    b = _Edition(translation_texts[translation_kept.start : translation_kept.stop])
    shared = _shared_vocabulary(a, b)
    chain = _filter_chain(_longest_chain(_sure_points(a, b, shared)))
    ratio = _ratio(a, b, chain)
    shared_words = _SharedWords(a, b, shared)
    first_local = batch.start - original_kept.start
    stop_local = batch.stop - original_kept.start
    anchors: list[Anchor] = []
    for a0, a1, b0, b1, head, tail in _stretches(
        fixed_groups, original_kept, translation_kept
    ):
        if a1 <= first_local or a0 >= stop_local or a1 == a0 or b1 == b0:
            continue
        n1, n2 = a1 - a0, b1 - b0
        points = [(i - a0, j - b0) for i, j in chain if a0 < i < a1 and b0 < j < b1]
        path = _path(n1, n2, points)
        steepest = max(
            (path[i + 1] - path[i] for i in range(n1)), default=0.0
        )
        band = max(_BAND, math.ceil(steepest) + 3)
        while True:
            try:
                beads = _align_stretch(
                    a, b, a0, n1, b0, n2, points, ratio, shared_words, head, tail, band
                )
                break
            except _Unreachable:
                if band > max(n1, n2):
                    raise
                band *= 2
        for i0, i1, j0, j1 in beads:
            if i1 == i0 or j1 == j0:
                continue
            if not first_local <= a0 + i0 < stop_local:
                continue
            anchors.extend(
                _bead_anchors(
                    original_ids,
                    translation_ids,
                    original_kept.start + a0 + i0,
                    original_kept.start + a0 + i1,
                    translation_kept.start + b0 + j0,
                    translation_kept.start + b0 + j1,
                )
            )
    return anchors
