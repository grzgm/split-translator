"""One edition's paragraph normalisation, as multipliers of the default spec.

Both surfaces strip each book's own stylesheet, so a book falls back to the
browser's default sheet and the Normalise toggle imposes one uniform set of
spacing rules on top (see book_view). That levels out the difference between
<p>-paragraph and <div>-paragraph books, but it applies the same rules to both
editions, so it cannot help when one book simply runs longer than the other. A
Polish translation of an English novel typically does, and equivalent passages
then drift further apart the longer you scroll.

This module makes those rules adjustable per edition. The values are multipliers
of the defaults rather than sizes, so x1.0 everywhere renders exactly as the
fixed spec always has, "reset to default" is "every field back to 1.0", and a
later change to the defaults carries into every customised book pair.

Font is the coarse lever and the other two are trim within it: line-height is
unitless and margin-block is in em, so both already follow the font size.
Changing font scales that edition's whole layout; changing line_height or gap
adjusts inside it.

No Qt import, so this unit-tests headless like book_sync and flashcard_autofill.
"""

import math
from dataclasses import dataclass

# The two editions a book pair holds. They live here, in the module with no
# dependencies, rather than beside the store's reader/editor surface names,
# so the panel widget can name a side without importing the persistence layer.
ORIGINAL_SIDE = "original"
TRANSLATION_SIDE = "translation"

#: The fixed spec every multiplier is relative to. x1.0 reproduces it exactly.
#: The font percentage is new (the stylesheet this replaces set no font size),
#: and 100% is neutral: the book HTML sets none on body either, so it resolves
#: to the browser default already in effect.
DEFAULT_FONT_PERCENT = 100.0
DEFAULT_LINE_HEIGHT = 1.55
DEFAULT_GAP_EM = 0.6

#: The range a multiplier is held to, in the stored file and in the spin boxes
#: alike. Wide enough to bring two ordinary editions into step, narrow enough
#: that a malformed file cannot render a book unreadable.
MIN_SCALE = 0.5
MAX_SCALE = 2.0


def _clamp(value) -> float:
    """A multiplier held inside the allowed range. Anything that is not a
    finite number (a missing key, a string, None, a NaN from a hand-edited
    file) falls back to 1.0, so one bad field never costs its neighbours."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(number):  # NaN and inf both survive min/max unchanged
        return 1.0
    return min(max(number, MIN_SCALE), MAX_SCALE)


def _css_number(value: float) -> str:
    """A CSS number with no binary-floating-point noise. 0.6 * 1.05 is
    0.6300000000000001 in Python and must reach the stylesheet as 0.63."""
    return f"{round(value, 3):.3f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class NormaliseSpec:
    """One edition's normalisation, as multipliers of the default spec.

    Frozen, so a spec handed to a view cannot be mutated behind its back; a
    change makes a new one. The three fields are clamped on construction, which
    means a spec read from a hand-edited file is as safe as one built from the
    spin boxes."""

    font: float = 1.0
    line_height: float = 1.0
    gap: float = 1.0

    def __post_init__(self) -> None:
        # object.__setattr__ because the dataclass is frozen; this is the one
        # sanctioned way to normalise fields at construction time.
        object.__setattr__(self, "font", _clamp(self.font))
        object.__setattr__(self, "line_height", _clamp(self.line_height))
        object.__setattr__(self, "gap", _clamp(self.gap))

    @property
    def is_default(self) -> bool:
        """True when this renders exactly as the fixed spec always has. Drives
        whether the panel's Reset button is live."""
        return (self.font, self.line_height, self.gap) == (1.0, 1.0, 1.0)

    def css(self) -> str:
        """This edition's normalisation stylesheet.

        The three rules after `body` carry no scaled value. Their order matters
        and must not change: the zeroing rule has to precede margin-block, and
        the spacer rule comes last.

        Blank spacer blocks collapse here. The loader marks every block with no
        visible text and no image with a data-st-spacer attribute (see
        book_loader), whether it is truly empty or holds only whitespace, a
        non-breaking space or empty inline wrappers, so one attribute selector
        catches them all without any work in the page."""
        return (
            "body { font-size: "
            f"{_css_number(DEFAULT_FONT_PERCENT * self.font)}%; line-height: "
            f"{_css_number(DEFAULT_LINE_HEIGHT * self.line_height)}; }}"
            " p, div, blockquote, li, h1, h2, h3, h4, h5, h6 { margin: 0; }"
            " p, div, blockquote, li { margin-block: "
            f"{_css_number(DEFAULT_GAP_EM * self.gap)}em; }}"
            " [data-st-spacer] { margin: 0; height: 0; }"
        )

    def to_dict(self) -> dict:
        """The stored form. The keys are the field names, so the anchor file is
        readable by eye and from_dict needs no mapping table."""
        return {
            "font": self.font,
            "line_height": self.line_height,
            "gap": self.gap,
        }

    @classmethod
    def from_dict(cls, raw) -> "NormaliseSpec":
        """Read a stored spec, tolerating anything. A non-dict, a missing field
        or a malformed one each fall back to 1.0 for that field alone, matching
        how every other store here loads."""
        if not isinstance(raw, dict):
            return cls()
        return cls(
            font=raw.get("font", 1.0),
            line_height=raw.get("line_height", 1.0),
            gap=raw.get("gap", 1.0),
        )
