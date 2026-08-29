import unittest

from PySide6.QtWidgets import QApplication, QWidget

from split_translator.main_window import TranslationTool

app = QApplication.instance() or QApplication([])


class CloseEventTests(unittest.TestCase):
    """The graph and print windows have no parent, so they are independent
    top-level windows. Left open they keep app.exec() from returning, which
    would hang a workspace switch, and they hold the outgoing workspace's store,
    so a survivor would show the previous workspace's deck."""

    def test_close_event_closes_the_graph_and_print_windows(self):
        graph = QWidget()
        printer = QWidget()
        graph.show()
        printer.show()
        # Called unbound against a stub: the method reads two attributes and
        # nothing else, so building a real window (which needs books on disk and
        # a web profile) would buy nothing.
        stub = type("Stub", (), {
            "flashcard_graph_window": graph,
            "flashcard_print_window": printer,
        })()
        TranslationTool.close_child_windows(stub)
        self.assertFalse(graph.isVisible())
        self.assertFalse(printer.isVisible())

    def test_close_child_windows_tolerates_windows_never_opened(self):
        stub = type("Stub", (), {
            "flashcard_graph_window": None,
            "flashcard_print_window": None,
        })()
        # Must not raise.
        TranslationTool.close_child_windows(stub)


if __name__ == "__main__":
    unittest.main()
