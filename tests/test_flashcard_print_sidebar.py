import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_print_choices import AUTO, MANUAL, PrintChoices
from split_translator.flashcard_print_sidebar import PrintSidebar
from split_translator.flashcards import Card, Sense

app = QApplication.instance() or QApplication([])


def _card(card_id="c"):
    return Card(
        headword="cat", id=card_id,
        senses=[
            Sense(pos="v", polish="biegac", examples=["a1", "a2"]),
            Sense(pos="n", polish="kot", examples=["b1"]),
        ],
    )


class SidebarBuildTests(unittest.TestCase):
    def _sidebar(self):
        choices = PrintChoices()
        sidebar = PrintSidebar(choices)
        self.addCleanup(sidebar.deleteLater)
        return sidebar, choices

    def test_no_card_shows_a_placeholder_and_no_rows(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(None, False)
        self.assertIsNone(sidebar.card_id())
        self.assertEqual(sidebar.ticked_pairs(), [])

    def test_a_row_per_example(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), True)
        self.assertEqual(sidebar.card_id(), "c")
        self.assertEqual(
            sorted(sidebar._boxes), [(0, 0), (0, 1), (1, 0)]
        )

    def test_each_example_row_shows_its_text(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), True)
        self.assertEqual(sidebar._boxes[(0, 0)].text(), "a1")
        self.assertEqual(sidebar._boxes[(1, 0)].text(), "b1")

    def test_a_card_with_no_examples_builds_without_rows(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(Card(headword="bare", id="b"), True)
        self.assertEqual(sidebar._boxes, {})
        self.assertEqual(sidebar.ticked_pairs(), [])


class SidebarTickStateTests(unittest.TestCase):
    def _sidebar(self):
        choices = PrintChoices()
        sidebar = PrintSidebar(choices)
        self.addCleanup(sidebar.deleteLater)
        return sidebar, choices

    def test_a_card_with_no_measurement_shows_everything_ticked(self):
        # Not in the print selection, so it never reached the preview to be
        # measured. Showing everything ticked lets it be tuned in advance.
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), False)
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0), (0, 1), (1, 0)])

    def test_a_measured_card_shows_the_measured_default(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0), (1, 0)]})
        sidebar.set_card(_card(), True)
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0), (1, 0)])

    def test_a_measurement_arriving_later_retticks_an_auto_card(self):
        # The reload is debounced, so the measurement lands after the card is
        # already on screen.
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), True)
        sidebar.set_auto_fit({"c": [(0, 0)]})
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0)])

    def test_a_measurement_for_another_card_is_ignored(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), True)
        sidebar.set_auto_fit({"somebody-else": [(0, 0)]})
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0), (0, 1), (1, 0)])

    def test_a_measurement_does_not_disturb_a_manual_card(self):
        sidebar, choices = self._sidebar()
        card = _card()
        choices.set_manual(card, [(0, 1)])
        sidebar.set_card(card, True)
        sidebar.set_auto_fit({"c": [(0, 0)]})
        self.assertEqual(sidebar.ticked_pairs(), [(0, 1)])

    def test_a_manual_card_shows_its_chosen_set(self):
        sidebar, choices = self._sidebar()
        card = _card()
        choices.set_manual(card, [(1, 0)])
        sidebar.set_card(card, True)
        self.assertEqual(sidebar.ticked_pairs(), [(1, 0)])

    def test_status_matches_the_ticks_for_a_measured_card_out_of_selection(self):
        # _default_pairs prefers a stored measurement over "everything ticked"
        # regardless of whether the card is in the print selection, so the
        # status text must not claim there is no measured default once one
        # exists, even after the card is unticked from the selection.
        sidebar, _choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0), (1, 0)]})
        sidebar.set_card(_card(), False)
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0), (1, 0)])
        self.assertNotIn("no measured default", sidebar.status_label.text())

    def test_a_measurement_arriving_with_no_card_shown_is_kept_for_later(self):
        # The preview measures every card it renders, which is rarely the
        # moment that card is loaded. The measurement has to survive until the
        # card is shown, rather than being dropped for having no home yet.
        sidebar, _choices = self._sidebar()
        sidebar.set_card(None, False)
        sidebar.set_auto_fit({"c": [(0, 0)]})
        self.assertIsNone(sidebar.card_id())
        sidebar.set_card(_card(), True)
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0)])


class SidebarPromotionTests(unittest.TestCase):
    def _sidebar(self):
        choices = PrintChoices()
        sidebar = PrintSidebar(choices)
        self.addCleanup(sidebar.deleteLater)
        return sidebar, choices

    def test_unticking_promotes_an_auto_card_to_manual(self):
        sidebar, choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0), (0, 1), (1, 0)]})
        sidebar.set_card(_card(), True)
        seen = []
        sidebar.choice_changed.connect(seen.append)
        sidebar._boxes[(0, 1)].setChecked(False)
        self.assertEqual(choices.mode_of("c"), MANUAL)
        self.assertEqual(choices.chosen_for("c"), {(0, 0), (1, 0)})
        self.assertEqual(seen, ["c"])

    def test_promotion_starts_from_the_ticks_on_screen_not_from_everything(self):
        # The measured default was two of the three examples. Ticking the third
        # must give three, not "everything the card has" and not just the one
        # just clicked.
        sidebar, choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0), (0, 1)]})
        sidebar.set_card(_card(), True)
        sidebar._boxes[(1, 0)].setChecked(True)
        self.assertEqual(choices.chosen_for("c"), {(0, 0), (0, 1), (1, 0)})

    def test_a_further_tick_updates_the_manual_set(self):
        sidebar, choices = self._sidebar()
        card = _card()
        choices.set_manual(card, [(0, 0)])
        sidebar.set_card(card, True)
        sidebar._boxes[(1, 0)].setChecked(True)
        self.assertEqual(choices.chosen_for("c"), {(0, 0), (1, 0)})

    def test_unticking_everything_is_an_empty_manual_set(self):
        sidebar, choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0)]})
        sidebar.set_card(_card(), True)
        sidebar._boxes[(0, 0)].setChecked(False)
        self.assertEqual(choices.mode_of("c"), MANUAL)
        self.assertEqual(choices.chosen_for("c"), set())

    def test_building_the_rows_does_not_promote_the_card(self):
        # set_card ticks boxes programmatically; those must not be read as the
        # user hand-picking anything.
        sidebar, choices = self._sidebar()
        seen = []
        sidebar.choice_changed.connect(seen.append)
        sidebar.set_auto_fit({"c": [(0, 0)]})
        sidebar.set_card(_card(), True)
        self.assertEqual(choices.mode_of("c"), AUTO)
        self.assertEqual(seen, [])

    def test_a_measurement_does_not_promote_the_card(self):
        sidebar, choices = self._sidebar()
        sidebar.set_card(_card(), True)
        seen = []
        sidebar.choice_changed.connect(seen.append)
        sidebar.set_auto_fit({"c": [(0, 0)]})
        self.assertEqual(choices.mode_of("c"), AUTO)
        self.assertEqual(seen, [])


class SidebarResetTests(unittest.TestCase):
    def _sidebar(self):
        choices = PrintChoices()
        sidebar = PrintSidebar(choices)
        self.addCleanup(sidebar.deleteLater)
        return sidebar, choices

    def test_reset_is_disabled_for_an_auto_card(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), True)
        self.assertFalse(sidebar.reset_button.isEnabled())

    def test_reset_is_enabled_once_the_card_is_manual(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), True)
        sidebar._boxes[(0, 0)].setChecked(False)
        self.assertTrue(sidebar.reset_button.isEnabled())

    def test_reset_returns_the_card_to_auto_and_reticks(self):
        sidebar, choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0), (1, 0)]})
        sidebar.set_card(_card(), True)
        sidebar._boxes[(0, 0)].setChecked(False)
        seen = []
        sidebar.choice_changed.connect(seen.append)
        sidebar.reset_button.click()
        self.assertEqual(choices.mode_of("c"), AUTO)
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0), (1, 0)])
        self.assertEqual(seen, ["c"])
        self.assertFalse(sidebar.reset_button.isEnabled())

    def test_reset_with_no_card_shown_is_inert(self):
        # The button is disabled with no card loaded, so a real click on it
        # short-circuits in Qt before ever reaching the handler. Calling the
        # handler directly is what actually exercises its own
        # "if self._card is None: return" guard.
        sidebar, _choices = self._sidebar()
        sidebar.set_card(None, False)
        seen = []
        sidebar.choice_changed.connect(seen.append)
        sidebar._on_reset()
        self.assertEqual(seen, [])
        self.assertIsNone(sidebar.card_id())


class SidebarMeasurementDropTests(unittest.TestCase):
    def _sidebar(self):
        choices = PrintChoices()
        sidebar = PrintSidebar(choices)
        self.addCleanup(sidebar.deleteLater)
        return sidebar, choices

    def test_dropping_the_shown_cards_measurement_reticks_it(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0)]})
        sidebar.set_card(_card(), True)
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0)])
        sidebar.drop_measurement("c")
        # No measurement left, so the default falls back to everything ticked,
        # exactly as it would for a card that was never measured.
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0), (0, 1), (1, 0)])

    def test_dropping_a_measurement_for_a_card_not_shown_is_harmless(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_auto_fit({"c": [(0, 0)]})
        sidebar.set_card(_card(), True)
        sidebar.drop_measurement("somebody-else")
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0)])

    def test_dropping_an_unknown_measurement_is_a_no_op(self):
        sidebar, _choices = self._sidebar()
        sidebar.set_card(_card(), True)
        sidebar.drop_measurement("never-measured")  # must not raise
        self.assertEqual(sidebar.ticked_pairs(), [(0, 0), (0, 1), (1, 0)])


class SidebarOptionTests(unittest.TestCase):
    """The print config lives in the sidebar. Defaults must match what the
    preview renders with before anything is touched."""

    def _sidebar(self):
        sidebar = PrintSidebar(PrintChoices())
        self.addCleanup(sidebar.deleteLater)
        return sidebar

    def test_defaults(self):
        sidebar = self._sidebar()
        self.assertFalse(sidebar.show_borders())
        self.assertTrue(sidebar.print_cut_lines())
        self.assertTrue(sidebar.blank_headwords())
        self.assertEqual(sidebar.back_offset(), 3.0)
        self.assertEqual(sidebar.back_offset_x(), 0.0)

    def test_toggling_borders_announces_it(self):
        sidebar = self._sidebar()
        seen = []
        sidebar.borders_toggled.connect(seen.append)
        sidebar.borders_checkbox.setChecked(True)
        self.assertEqual(seen, [True])

    def test_toggling_cut_lines_announces_it(self):
        sidebar = self._sidebar()
        seen = []
        sidebar.cut_lines_toggled.connect(seen.append)
        sidebar.cut_lines_checkbox.setChecked(False)
        self.assertEqual(seen, [False])

    def test_toggling_blank_headwords_announces_it(self):
        sidebar = self._sidebar()
        seen = []
        sidebar.blank_headwords_toggled.connect(seen.append)
        sidebar.blank_headwords_checkbox.setChecked(False)
        self.assertEqual(seen, [False])

    def test_changing_an_offset_announces_it(self):
        sidebar = self._sidebar()
        seen = []
        sidebar.back_offset_changed.connect(lambda: seen.append(True))
        sidebar.back_offset_spin.setValue(5.0)
        sidebar.back_offset_x_spin.setValue(2.0)
        self.assertEqual(len(seen), 2)
        self.assertEqual(sidebar.back_offset(), 5.0)
        self.assertEqual(sidebar.back_offset_x(), 2.0)

    def test_the_print_button_announces_a_request(self):
        sidebar = self._sidebar()
        seen = []
        sidebar.print_requested.connect(lambda: seen.append(True))
        sidebar.print_button.click()
        self.assertEqual(seen, [True])


if __name__ == "__main__":
    unittest.main()
