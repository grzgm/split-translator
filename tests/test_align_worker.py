import unittest

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from split_translator.align_worker import AlignWorker

app = QApplication.instance() or QApplication([])

IDS = ["b0", "b1", "b2"]
TEXTS = ["Zorander walked home.", "Quillon slept late.", "Mervash ate bread."]


def _arguments(**changes):
    arguments = dict(
        original_ids=IDS,
        original_texts=TEXTS,
        translation_ids=IDS,
        translation_texts=TEXTS,
        fixed_groups=[],
        start=0,
        count=3,
        original_kept=range(3),
        translation_kept=range(3),
    )
    arguments.update(changes)
    return arguments


class AlignWorkerTests(unittest.TestCase):
    def _run(self, worker):
        worker.start()
        self.assertTrue(worker.wait(10000))

    def test_the_anchors_are_there_once_it_has_run(self):
        worker = AlignWorker(_arguments())
        self._run(worker)
        self.assertIsNone(worker.error)
        self.assertEqual(worker.anchors, [("b0", "b0"), ("b1", "b1"), ("b2", "b2")])

    def test_an_exception_becomes_the_error_and_no_anchors(self):
        worker = AlignWorker(_arguments(original_kept=None))
        self._run(worker)
        self.assertEqual(worker.anchors, [])
        self.assertTrue(worker.error)

    def test_finished_reaches_the_ui_thread(self):
        worker = AlignWorker(_arguments())
        seen = []
        worker.finished.connect(lambda: seen.append(list(worker.anchors)))
        self._run(worker)
        QCoreApplication.processEvents()
        self.assertEqual(seen, [[("b0", "b0"), ("b1", "b1"), ("b2", "b2")]])


if __name__ == "__main__":
    unittest.main()
