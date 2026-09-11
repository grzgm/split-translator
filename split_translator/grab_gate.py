"""Which Cambridge English page load the passive grab belongs to.

A search points the Cambridge English view at one address, and the page that
arrives from it is grabbed into the flashcard editor: its headword, IPA,
spelling and audio, and its plural marker. No other load of that view is. A page
the user reaches by searching or clicking inside the view, or by going Back, is
the user's own, and grabbing it would write another word into the card.

"The first load after a search" used to be the whole rule, and a bot check
breaks it. Cambridge sits behind Cloudflare, which can answer a search with its
"Just a moment..." check instead of the entry. The check is a load in its own
right, so it used the grab up, and the entry that followed once the check was
passed was never grabbed, however long the card had been kept open for typing.
So a check settles nothing here: it holds the grab for the next load at its own
address. That is how a check hands over. Its script sends the answer back to
that address (a token in the query), and any redirect Cambridge makes after
that is part of the same load. A load that starts at any other address was
begun by the user (Back, a link on the check page) and lets the grab go.

No Qt import, so this unit-tests headless like flashcard_autofill."""

from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit


def is_challenge_response(headers: Mapping[str, Iterable[str]]) -> bool:
    """Whether a load was Cloudflare's check rather than the page asked for.

    Cloudflare marks every challenge page it serves, whatever the challenge
    type, with the response header ``cf-mitigated: challenge``, and "challenge"
    is the only value it sends. headers maps lower-case header names to their
    values, a list per name, the shape Qt reports them in."""
    return any(
        value.strip().lower() == "challenge"
        for value in headers.get("cf-mitigated", ())
    )


def _address(url: str) -> str:
    """A URL without its query and fragment, so a check's answer, which goes
    back to the check's address with a token in the query, counts as a load at
    that same address."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


class GrabGate:
    """The passive grab's claim on the Cambridge English view's loads.

    Armed when a search starts a load, disarmed when a lookup that must not grab
    starts one, and told of every load as it starts and finishes. load_finished
    answers the one question the panel asks: grab this page now, or not."""

    def __init__(self) -> None:
        #: True from a search until the load that settles it.
        self._armed = False
        #: The address of the check holding the grab, or None while no check
        #: stands in front of the searched page.
        self._held_at: str | None = None

    @property
    def is_armed(self) -> bool:
        """Whether a search is still waiting for its page."""
        return self._armed

    def arm(self) -> None:
        """A search has just pointed the view at its page: grab that page when
        it arrives. Replaces whatever an earlier search was still waiting for."""
        self._armed = True
        self._held_at = None

    def disarm(self) -> None:
        """Grab nothing the view loads from now on, until the next search."""
        self._armed = False
        self._held_at = None

    def load_started(self, url: str) -> None:
        """A load has begun. While a check holds the grab, a load at any other
        address is the user leaving the check, so the grab is let go."""
        if self._held_at is not None and _address(url) != self._held_at:
            self.disarm()

    def load_finished(self, ok: bool, url: str, challenge: bool = False) -> bool:
        """A load has ended. Returns True when it is the searched page, to be
        grabbed now.

        A check keeps the grab and holds it at the check's own address. Any
        other load settles it: the grab is spent whether that load succeeded or
        not, so a failed search load never passes it on to a later one, and
        only a page that loaded is grabbed."""
        if not self._armed:
            return False
        if challenge:
            self._held_at = _address(url)
            return False
        self.disarm()
        return ok
