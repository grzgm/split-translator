"""The Fill button, wiring side.

The panel only announces the click; the main window owns the three sources it
fills from. The grab is taken with its own callback
rather than through pronunciation_grabbed, so this one-shot fill is answered by
the page on screen and no passive listener acts on it. The window methods are
driven as unbound functions against a lightweight carrier, avoiding the
WebEngine-heavy real window (the same trick as test_headword_source)."""

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from split_translator.dictionary_panel import DictionaryPanel, _parse_grab
from split_translator.main_window import TranslationTool

app = QApplication.instance() or QApplication([])


class FillEmptyRoutingTests(unittest.TestCase):
    def _carrier(self, search_text="running", sentence="A sentence."):
        calls = []

        def on_fill_empty_grabbed(data):
            calls.append(("grabbed", data))

        carrier = SimpleNamespace(
            # The real window's own bound method; the carrier stands in for it
            # so the grab's callback can be identified.
            on_fill_empty_grabbed=on_fill_empty_grabbed,
            flashcard_dock=SimpleNamespace(
                show=lambda: calls.append(("show",)),
                setFloating=lambda value: calls.append(("float", value)),
            ),
            flashcard_panel=SimpleNamespace(
                fill_empty_headword=lambda word: calls.append(("headword", word)),
                fill_empty_book_example=lambda s, tag="": calls.append(
                    ("example", s, tag)
                ),
            ),
            dictionary_panel=SimpleNamespace(
                search_input=SimpleNamespace(text=lambda: search_text),
                grab_pronunciation=lambda cb: calls.append(("grab", cb)),
            ),
            book_panel=SimpleNamespace(
                current_match_sentence=lambda cb: cb(sentence)
            ),
            book_tag="book:alice",
        )
        return carrier, calls

    def test_it_fills_from_all_three_sources(self):
        carrier, calls = self._carrier()
        TranslationTool.fill_empty_flashcard(carrier)
        kinds = [call[0] for call in calls]
        self.assertIn("headword", kinds)
        self.assertIn("grab", kinds)
        self.assertIn("example", kinds)

    def test_it_seeds_the_headword_from_the_search_box(self):
        carrier, calls = self._carrier(search_text="running")
        TranslationTool.fill_empty_flashcard(carrier)
        self.assertIn(("headword", "running"), calls)

    def test_it_passes_the_book_tag_with_the_sentence(self):
        carrier, calls = self._carrier(sentence="A sentence.")
        TranslationTool.fill_empty_flashcard(carrier)
        self.assertIn(("example", "A sentence.", "book:alice"), calls)

    def test_it_opens_the_editor_docked(self):
        carrier, calls = self._carrier()
        TranslationTool.fill_empty_flashcard(carrier)
        self.assertIn(("float", False), calls)
        self.assertIn(("show",), calls)

    def test_it_never_clears_the_card(self):
        # new_card is what New calls to empty the editor. A carrier without it
        # would raise if this action ever reached for it.
        carrier, _ = self._carrier()
        self.assertFalse(hasattr(carrier.flashcard_panel, "new_card"))
        TranslationTool.fill_empty_flashcard(carrier)

    def test_it_takes_the_grab_with_its_own_callback(self):
        carrier, calls = self._carrier()
        TranslationTool.fill_empty_flashcard(carrier)
        grab = next(call for call in calls if call[0] == "grab")
        self.assertEqual(grab[1], carrier.on_fill_empty_grabbed)


class FillEmptyGrabTests(unittest.TestCase):
    def _carrier(self, search_text="running"):
        captured = {}
        return (
            SimpleNamespace(
                dictionary_panel=SimpleNamespace(
                    search_input=SimpleNamespace(text=lambda: search_text)
                ),
                flashcard_panel=SimpleNamespace(
                    fill_empty_pronunciation=lambda *a, **kw: captured.update(
                        {"args": a, **kw}
                    )
                ),
            ),
            captured,
        )

    def test_the_page_headword_wins_over_the_search_term(self):
        carrier, captured = self._carrier(search_text="running")
        TranslationTool.on_fill_empty_grabbed(
            carrier, {"headword": "run", "ipa_uk": "/run/"}
        )
        self.assertEqual(captured["word"], "run")

    def test_it_falls_back_to_the_search_term(self):
        carrier, captured = self._carrier(search_text="running")
        TranslationTool.on_fill_empty_grabbed(carrier, {"ipa_uk": "/run/"})
        self.assertEqual(captured["word"], "running")

    def test_an_empty_grab_fills_nothing(self):
        carrier, captured = self._carrier()
        TranslationTool.on_fill_empty_grabbed(carrier, {})
        self.assertEqual(captured, {})

    def test_it_passes_the_whole_grab_through(self):
        carrier, captured = self._carrier()
        TranslationTool.on_fill_empty_grabbed(
            carrier,
            {
                "ipa_uk": "/uk/",
                "ipa_us": "/us/",
                "audio_uk_url": "uk.mp3",
                "audio_us_url": "us.mp3",
                "spelling_uk": "colour",
                "spelling_us": "color",
            },
        )
        self.assertEqual(
            captured["args"],
            ("/uk/", "/us/", "uk.mp3", "us.mp3", "colour", "color"),
        )


class OneShotGrabTests(unittest.TestCase):
    """grab_pronunciation with a callback answers that caller alone; without
    one it goes out on the signal, as every page load does."""

    def _panel(self):
        panel = DictionaryPanel(QWebEngineProfile.defaultProfile())
        # Stand in for the live page: the grab script is not what is under test
        # here, only where its result is delivered.
        panel.cambridge_en_view = SimpleNamespace(
            page=lambda: SimpleNamespace(
                runJavaScript=lambda js, cb: cb('{"ipa_uk": "/uk/"}')
            )
        )
        return panel

    def test_a_callback_receives_the_parsed_grab(self):
        panel = self._panel()
        got = []
        panel.grab_pronunciation(got.append)
        self.assertEqual(got, [{"ipa_uk": "/uk/"}])

    def test_a_callback_grab_stays_off_the_signal(self):
        panel = self._panel()
        emitted = []
        panel.pronunciation_grabbed.connect(emitted.append)
        panel.grab_pronunciation(lambda data: None)
        self.assertEqual(emitted, [])

    def test_without_a_callback_it_still_emits(self):
        panel = self._panel()
        emitted = []
        panel.pronunciation_grabbed.connect(emitted.append)
        panel.grab_pronunciation()
        self.assertEqual(emitted, [{"ipa_uk": "/uk/"}])


class ParseGrabTests(unittest.TestCase):
    def test_it_parses_the_json_string(self):
        self.assertEqual(_parse_grab('{"ipa_uk": "/uk/"}'), {"ipa_uk": "/uk/"})

    def test_an_empty_result_is_an_empty_grab(self):
        self.assertEqual(_parse_grab(""), {})
        self.assertEqual(_parse_grab(None), {})

    def test_unparseable_output_is_an_empty_grab(self):
        self.assertEqual(_parse_grab("not json"), {})


if __name__ == "__main__":
    unittest.main()
