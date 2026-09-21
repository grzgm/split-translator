"""Runs the aligner off the UI thread, like the stores' SaveWorker. The anchor
editor starts it and reads the result when QThread.finished arrives, so a
novel's few seconds of alignment never freeze the window."""

from PySide6.QtCore import QThread

from .book_align import align_batch


class AlignWorker(QThread):
    """Aligns one batch. Once finished, `anchors` holds the result, or `error`
    says why there is none. `arguments` are align_batch's keyword arguments."""

    def __init__(self, arguments: dict):
        super().__init__()
        self.arguments = arguments
        self.anchors: list[tuple[str, str]] = []
        self.error: str | None = None

    def run(self):
        try:
            self.anchors = align_batch(**self.arguments)
        except Exception as exc:  # reported by the editor, which changes nothing
            self.error = str(exc) or type(exc).__name__
