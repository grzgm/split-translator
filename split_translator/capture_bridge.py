"""Bridge between injected web-page buttons and the flashcard editor.

The dictionary web views get small "add to sense" buttons injected next to each
definition and translation. When the user clicks one, page JavaScript calls into
this QObject over a QWebChannel, which re-emits the request as a Qt signal the
main window routes into the flashcard panel.
"""

from PySide6.QtCore import QObject, Signal, Slot


class CaptureBridge(QObject):
    """Receives capture clicks from injected page buttons and re-emits them as signals."""

    # field: "polish" | "english"; pos: "" when unknown. target is one of
    # "current" (replace the active sense), "append" (append into the active
    # sense) or "new" (fresh sense, replace).
    capture_requested = Signal(str, str, str, str)  # text, field, target, pos
    # A pronunciation clip captured from the page: region "uk"/"us", mp3 URL and
    # the clip's IPA notation ("" when the page block has none).
    audio_capture_requested = Signal(str, str, str)  # region, url, ipa

    @Slot(str, str, str, str)
    def capture(self, text: str, field: str, target: str, pos: str) -> None:
        self.capture_requested.emit(text, field, target, pos)

    @Slot(str, str, str)
    def captureAudio(self, region: str, url: str, ipa: str) -> None:
        self.audio_capture_requested.emit(region, url, ipa)
