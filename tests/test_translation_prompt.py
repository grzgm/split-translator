import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.main_window import TranslationTool

app = QApplication.instance() or QApplication([])


class CopyTranslationPromptTests(unittest.TestCase):
    """copy_translation_prompt builds the contextual-translation prompt from the
    search word and the current Original-match sentence and copies it to the
    clipboard. Empty word or no sentence is a silent no-op (clipboard left
    unchanged). Driven as an unbound method against a lightweight carrier (no
    WebEngine window); the real system clipboard is asserted."""

    def _carrier(self, word, sentence):
        # book_panel.current_match_sentence(cb) immediately calls cb(sentence).
        book_panel = SimpleNamespace(
            current_match_sentence=lambda cb: cb(sentence)
        )
        dictionary_panel = SimpleNamespace(
            search_input=SimpleNamespace(text=lambda: word)
        )
        messages = []
        carrier = SimpleNamespace(
            dictionary_panel=dictionary_panel,
            book_panel=book_panel,
            statusBar=lambda: SimpleNamespace(
                showMessage=lambda msg, *a: messages.append(msg)
            ),
        )
        return carrier, messages

    def _run(self, carrier):
        TranslationTool.copy_translation_prompt(carrier)

    def _seed_clipboard(self, sentinel):
        QApplication.clipboard().setText(sentinel)

    def test_copies_prompt_for_word_and_sentence(self):
        self._seed_clipboard("SENTINEL")
        carrier, _ = self._carrier("run", "She saw the dog run.")
        self._run(carrier)
        self.assertEqual(
            QApplication.clipboard().text(),
            'Translate "run" to Polish in the context of "She saw the dog run."',
        )

    def test_empty_word_is_noop(self):
        self._seed_clipboard("SENTINEL")
        carrier, messages = self._carrier("   ", "She saw the dog run.")
        self._run(carrier)
        self.assertEqual(QApplication.clipboard().text(), "SENTINEL")
        self.assertTrue(messages)  # a status note was shown

    def test_no_sentence_is_noop(self):
        self._seed_clipboard("SENTINEL")
        carrier, messages = self._carrier("run", "")
        self._run(carrier)
        self.assertEqual(QApplication.clipboard().text(), "SENTINEL")
        self.assertTrue(messages)  # a status note was shown


if __name__ == "__main__":
    unittest.main()
