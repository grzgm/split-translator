"""Which Cambridge English load the passive grab belongs to.

Pure logic, so no Qt and no display. How the dictionary panel feeds Qt's load
reports into it is in test_dictionary_panel (AppSearchGrabGateTests)."""

import unittest

from split_translator.grab_gate import GrabGate, is_challenge_response

#: The address a search for "running" points the view at.
SEARCHED = "https://dictionary.cambridge.org/dictionary/english/running"
#: Where Cambridge redirects that search to serve the entry.
ENTRY = "https://dictionary.cambridge.org/dictionary/english/run"
#: A passed check's answer: the check's own address, with a token in the query.
ANSWER = SEARCHED + "?__cf_chl_f_tk=abc"
#: Anywhere else: the previous word's page, or a link on the check page.
ELSEWHERE = "https://dictionary.cambridge.org/dictionary/english/walk"


class ChallengeResponseTests(unittest.TestCase):
    def test_cloudflare_marks_its_check(self):
        self.assertTrue(is_challenge_response({"cf-mitigated": ["challenge"]}))

    def test_a_page_served_through_cloudflare_is_not_a_check(self):
        # Every Cambridge page carries Cloudflare's own headers; only the check
        # carries cf-mitigated.
        headers = {"server": ["cloudflare"], "cf-ray": ["<ray>"]}
        self.assertFalse(is_challenge_response(headers))

    def test_a_load_with_no_response_is_not_a_check(self):
        # A load that never reached a server (no connection) has no headers.
        self.assertFalse(is_challenge_response({}))

    def test_the_value_is_read_without_regard_to_case_or_spacing(self):
        self.assertTrue(is_challenge_response({"cf-mitigated": [" Challenge "]}))


class GrabGateTests(unittest.TestCase):
    def _load(self, gate, url, ok=True, challenge=False, started_at=None):
        """One load, reported the way the panel reports it: started, then
        finished. A redirected load starts at one address and ends at another.
        Returns whether the finished load is to be grabbed."""
        gate.load_started(started_at or url)
        return gate.load_finished(ok, url, challenge=challenge)

    def _held(self):
        """A gate whose search was answered with a check."""
        gate = GrabGate()
        gate.arm()
        self.assertFalse(self._load(gate, SEARCHED, ok=False, challenge=True))
        return gate

    def test_nothing_is_grabbed_without_a_search(self):
        self.assertFalse(self._load(GrabGate(), ENTRY))

    def test_the_searched_page_is_grabbed(self):
        gate = GrabGate()
        gate.arm()
        self.assertTrue(self._load(gate, ENTRY, started_at=SEARCHED))

    def test_only_the_searched_page_is_grabbed(self):
        # The load after it is the user searching or clicking inside the page.
        gate = GrabGate()
        gate.arm()
        self._load(gate, ENTRY, started_at=SEARCHED)
        self.assertFalse(self._load(gate, ELSEWHERE))

    def test_a_failed_search_load_spends_the_grab(self):
        # Not a check, so nothing replaces it by itself: the load after it is
        # the user's own.
        gate = GrabGate()
        gate.arm()
        self.assertFalse(self._load(gate, SEARCHED, ok=False))
        self.assertFalse(self._load(gate, SEARCHED))

    # --- a bot check in front of the page ---------------------------------

    def test_the_check_keeps_the_grab_armed(self):
        self.assertTrue(self._held().is_armed)

    def test_the_page_behind_the_check_is_grabbed(self):
        # The answer starts a load at the check's own address, and Cambridge's
        # redirect after it is part of that same load.
        gate = self._held()
        self.assertTrue(self._load(gate, ENTRY, started_at=ANSWER))

    def test_only_the_page_behind_the_check_is_grabbed(self):
        gate = self._held()
        self._load(gate, ENTRY, started_at=ANSWER)
        self.assertFalse(self._load(gate, ELSEWHERE))

    def test_a_check_that_comes_back_still_holds(self):
        # A rejected answer is met with another check at the same address.
        gate = self._held()
        self.assertFalse(
            self._load(
                gate, SEARCHED, ok=False, challenge=True, started_at=ANSWER
            )
        )
        self.assertTrue(self._load(gate, ENTRY, started_at=ANSWER))

    def test_leaving_the_check_lets_the_grab_go(self):
        # Back, or a link on the check page: a load that starts at another
        # address is the user's, and so is everything after it.
        gate = self._held()
        self.assertFalse(self._load(gate, ELSEWHERE))
        self.assertFalse(gate.is_armed)
        self.assertFalse(self._load(gate, ENTRY, started_at=SEARCHED))

    def test_a_new_search_during_the_check_is_grabbed_instead(self):
        gate = self._held()
        gate.arm()  # another word, searched from the app
        self.assertTrue(self._load(gate, ELSEWHERE))

    def test_disarming_during_the_check_lets_the_grab_go(self):
        # A flashcard selection, even one for the very word the check holds the
        # grab for, whose page loads at the same address.
        gate = self._held()
        gate.disarm()
        self.assertFalse(self._load(gate, ENTRY, started_at=SEARCHED))

    def test_a_check_with_no_search_behind_it_holds_nothing(self):
        gate = GrabGate()
        self.assertFalse(self._load(gate, SEARCHED, ok=False, challenge=True))
        self.assertFalse(gate.is_armed)
        self.assertFalse(self._load(gate, ENTRY, started_at=ANSWER))


if __name__ == "__main__":
    unittest.main()
