import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from split_translator.main_window import TranslationTool


class SenseCaptureRoutingTests(unittest.TestCase):
    """on_sense_capture_requested reads the target string to pick the sense and
    whether to replace or append. Driven as an unbound method against a
    lightweight carrier (no WebEngine window)."""

    def _carrier(self):
        calls = []
        row = SimpleNamespace(
            pos_combo=SimpleNamespace(
                currentText=lambda: "",
                setCurrentText=lambda p: calls.append(("pos", p)),
            )
        )
        panel = SimpleNamespace(
            add_sense=lambda: calls.append(("add_sense",)),
            set_polish_selection=lambda t: calls.append(("set_polish", t)),
            append_polish_selection=lambda t: calls.append(("append_polish", t)),
            set_english_selection=lambda t: calls.append(("set_english", t)),
            append_english_selection=lambda t: calls.append(
                ("append_english", t)
            ),
            add_example_selection=lambda t: calls.append(("example", t)),
            active_row=row,
        )
        carrier = SimpleNamespace(
            flashcard_dock=SimpleNamespace(show=lambda: None),
            flashcard_panel=panel,
        )
        # Exercise the real _route_capture (replace vs append) against the fake
        # panel by binding the unbound method to the carrier.
        carrier._route_capture = (
            lambda field, text, append=False: TranslationTool._route_capture(
                carrier, field, text, append
            )
        )
        return carrier, calls

    def _run(self, carrier, text, field, target, pos=""):
        TranslationTool.on_sense_capture_requested(
            carrier, text, field, target, pos
        )

    def test_new_target_replaces_in_a_fresh_sense(self):
        carrier, calls = self._carrier()
        self._run(carrier, "tom", "polish", "new")
        self.assertIn(("add_sense",), calls)
        self.assertIn(("set_polish", "tom"), calls)
        self.assertNotIn(("append_polish", "tom"), calls)

    def test_current_target_replaces_active_sense(self):
        carrier, calls = self._carrier()
        self._run(carrier, "tom", "polish", "current")
        self.assertNotIn(("add_sense",), calls)
        self.assertIn(("set_polish", "tom"), calls)
        self.assertNotIn(("append_polish", "tom"), calls)

    def test_append_target_appends_to_active_sense(self):
        carrier, calls = self._carrier()
        self._run(carrier, "tom", "polish", "append")
        self.assertNotIn(("add_sense",), calls)
        self.assertIn(("append_polish", "tom"), calls)
        self.assertNotIn(("set_polish", "tom"), calls)

    def test_append_target_routes_english_to_append(self):
        carrier, calls = self._carrier()
        self._run(carrier, "a volume", "english", "append")
        self.assertIn(("append_english", "a volume"), calls)

    def test_append_carries_pos_into_empty_combo(self):
        carrier, calls = self._carrier()
        self._run(carrier, "tom", "polish", "append", pos="noun")
        self.assertIn(("pos", "noun"), calls)


if __name__ == "__main__":
    unittest.main()
