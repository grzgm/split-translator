"""Side-by-side anchor editor: click a paragraph in each edition to select it,
then bind the two selections into an anchor. Saved anchors stay highlighted in
both views; clicking an anchor in the list jumps both views to it."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .anchor_book_view import AnchorBookView
from .anchor_store import EDITOR_SURFACE, AnchorStore
from .book_loader import BookDocument
from .book_sync import BookSync

_ORIGINAL_ID_ROLE = 256  # Qt.UserRole
_TRANSLATION_ID_ROLE = 257  # Qt.UserRole + 1


class _EditorSearch:
    """Drives one editor view's find bar. Independent per side: it owns the
    current term and match position for its own view and never touches the other.

    Numbers come from Chromium's own activeMatch/numberOfMatches (like the
    reader's BookPanel), so the counter is the match's absolute position and
    cannot disagree with the highlighted block. A hit is highlighted with the
    same dashed jump outline the anchor-list click uses; a miss (or a cleared
    box) clears it."""

    def __init__(self, view, on_label):
        self._view = view
        self._on_label = on_label
        self._term = ""
        self._count = 0
        self._current = 0

    def search(self, term: str) -> None:
        self._term = term.strip()
        if not self._term:
            # Clearing the box clears this side's match highlight and counter.
            self._count = 0
            self._current = 0
            self._view.set_jump("")
            self._on_label("")
            return
        self._current = 0
        self._view.find(self._term, True, self._on_result)

    def next(self) -> None:
        if self._term:
            self._view.find(self._term, True, self._on_result)

    def prev(self) -> None:
        if self._term:
            self._view.find(self._term, False, self._on_result)

    def _on_result(self, active: int, count: int) -> None:
        self._count = count
        self._current = active if count else 0
        if not count:
            self._on_label("No matches")
            self._view.set_jump("")
            return
        self._on_label(f"{self._current} / {self._count}")
        # Highlight the block holding the active match, located by its 1-based
        # index (not the scroll), matching the reader's approach.
        self._view.matched_block_id(
            self._term, self._current, self._view.set_jump
        )


class AnchorEditor(QWidget):
    """Two editions side by side; click to select a block on each, then bind."""

    def __init__(
        self,
        original_document: BookDocument,
        translation_document: BookDocument,
        anchor_store: AnchorStore,
        book_sync: BookSync,
        profile: QWebEngineProfile,
        on_changed,
        parent=None,
    ):
        super().__init__(parent)
        self.original_document = original_document
        self.translation_document = translation_document
        self.anchor_store = anchor_store
        self.book_sync = book_sync
        self._profile_ref = profile
        self._on_changed = on_changed

        self._selected_original: str | None = None
        self._selected_translation: str | None = None
        self.sync_enabled = True

        # Scroll-sync gesture ownership. Both editions are visible at once (unlike
        # the reader's tabs), so a mirrored scroll on the follower echoes back a
        # scrollPositionChanged that, unguarded, reverse-maps and snaps the side
        # the user is driving: both views jitter. The cure is to let only the side
        # the user last touched (the gesture owner) drive sync; the follower's
        # mirrored-scroll echo is ignored while the gesture is in flight.
        #
        # _sync_owner is that side; _sync_in_flight is True from the moment a
        # mirror is issued until a short timer fires, the window in which the
        # echo arrives. A genuine scroll on the other side while NOT in flight
        # transfers ownership (last-touched wins).
        self._sync_owner = None
        self._sync_in_flight = False
        self._sync_gesture_timer = QTimer(self)
        self._sync_gesture_timer.setSingleShot(True)
        # 150ms comfortably covers the echo and its settle chain (a few ms in
        # practice) without blocking the user from grabbing the other view after
        # a brief pause.
        self._sync_gesture_timer.setInterval(150)
        self._sync_gesture_timer.timeout.connect(self._end_sync_gesture)

        # The editor remembers its own scroll position, separate from the
        # reader. Seed from the editor surface and write it back on close.
        self._original_scroll, self._translation_scroll = (
            self.anchor_store.get_scroll(EDITOR_SURFACE)
        )

        self.init_ui()
        self.refresh()
        self._refresh_highlights()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # A vertical splitter so the boundary between the two book views (top)
        # and the controls + anchor list (bottom) can be dragged to give the
        # list more or less height.
        splitter = QSplitter(Qt.Orientation.Vertical)

        views_container = QWidget()
        views = QHBoxLayout(views_container)
        views.setContentsMargins(0, 0, 0, 0)
        self.original_view = AnchorBookView(
            self.original_document,
            self._profile_ref,
            initial_scroll=self._original_scroll,
        )
        self.translation_view = AnchorBookView(
            self.translation_document,
            self._profile_ref,
            initial_scroll=self._translation_scroll,
        )
        self.original_view.block_clicked.connect(self._on_original_clicked)
        self.translation_view.block_clicked.connect(self._on_translation_clicked)
        # Optional synced scrolling between the two sides (anchor-based, like the
        # main reader). The `scrolled` signal is separate from `block_clicked`,
        # so syncing never interferes with click-to-select.
        self.original_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.original_view, bid, frac)
        )
        self.translation_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.translation_view, bid, frac)
        )
        # Each edition gets its own find bar above it. The two are independent:
        # one searches the original, the other the translation.
        self.original_search = _EditorSearch(
            self.original_view, self._set_original_match_label
        )
        self.translation_search = _EditorSearch(
            self.translation_view, self._set_translation_match_label
        )
        # Equal stretch so the two columns split the width evenly.
        views.addWidget(
            self._make_search_column(
                self.original_view, self.original_search, "Find in original"
            ),
            1,
        )
        views.addWidget(
            self._make_search_column(
                self.translation_view,
                self.translation_search,
                "Find in translation",
            ),
            1,
        )
        splitter.addWidget(views_container)

        # The controls stay attached to the list so they are not squashed when
        # the views are given most of the height.
        bottom_container = QWidget()
        bottom = QVBoxLayout(bottom_container)
        bottom.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self.add_button = QPushButton("Add anchor here")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._on_add_clicked)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove_selected)
        self.sync_checkbox = QCheckBox("Sync")
        self.sync_checkbox.setChecked(True)
        self.sync_checkbox.stateChanged.connect(self.toggle_sync)
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        controls.addWidget(self.sync_checkbox)
        controls.addStretch()
        bottom.addLayout(controls)

        self.anchor_list = QListWidget()
        self.anchor_list.itemClicked.connect(self._on_anchor_clicked)
        bottom.addWidget(self.anchor_list)
        splitter.addWidget(bottom_container)

        # Give the book views most of the height by default; both stay resizable.
        # setSizes seeds the initial split (book-heavy); the stretch factors keep
        # that ratio as the window resizes.
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 160])

        layout.addWidget(splitter)

    def _make_search_column(self, view, search, placeholder: str) -> QWidget:
        """Build a column: a find bar (box, Search, Prev, Next, match counter)
        above the given view. The bar drives `search`, which searches only
        `view`. The view takes all the vertical space so it stays large on a
        tall screen; the bar keeps its natural height."""
        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        box = QLineEdit()
        box.setPlaceholderText(placeholder)
        box.returnPressed.connect(lambda: search.search(box.text()))
        search_button = QPushButton("Search")
        search_button.clicked.connect(lambda: search.search(box.text()))
        prev_button = QPushButton("Prev")
        prev_button.clicked.connect(search.prev)
        next_button = QPushButton("Next")
        next_button.clicked.connect(search.next)
        label = QLabel("")
        # The box takes the horizontal slack; the buttons and counter stay at
        # their natural width so the bar does not sprawl on a wide screen.
        bar.addWidget(box, 1)
        bar.addWidget(search_button)
        bar.addWidget(prev_button)
        bar.addWidget(next_button)
        bar.addWidget(label)
        # Stretch 0 for the bar (natural height), 1 for the view (all the rest),
        # so on a 4K screen the book view grows instead of leaving empty space
        # around the controls.
        column_layout.addLayout(bar, 0)
        column_layout.addWidget(view, 1)

        # The label setter (passed into _EditorSearch) writes here.
        if view is self.original_view:
            self._original_match_label = label
        else:
            self._translation_match_label = label
        return column

    def _set_original_match_label(self, text: str) -> None:
        self._original_match_label.setText(text)

    def _set_translation_match_label(self, text: str) -> None:
        self._translation_match_label.setText(text)

    def toggle_sync(self, state) -> None:
        self.sync_enabled = state == Qt.CheckState.Checked.value

    def _sync_from(self, source_view, block_id: str, fraction: float) -> None:
        """Mirror a scroll on one side to the other through the anchor mapping.

        Only the gesture owner (the side the user last touched) drives sync. A
        scroll from the other side while a mirror is in flight is the follower's
        echo of that mirror; ignoring it keeps the scrolled side smooth instead
        of both sides snapping. See the _sync_owner notes in __init__."""
        # Remember the latest position of whichever side moved so the editor
        # reopens here next time (independent of the reader). Cache before any
        # early return so positions are tracked even with sync off or on an echo.
        if source_view is self.original_view:
            self._original_scroll = (block_id, fraction)
        else:
            self._translation_scroll = (block_id, fraction)
        if not self.sync_enabled:
            return
        # Echo guard: a scroll from the non-owner side while a mirror is settling
        # is that mirror bouncing back. Drop it so it cannot reverse-drive the
        # owner (the jitter). The owner keeps driving; the follower may snap.
        if (
            self._sync_in_flight
            and self._sync_owner is not None
            and source_view is not self._sync_owner
        ):
            return
        # A genuine scroll: the source becomes (or stays) the gesture owner.
        # Last-touched wins, so grabbing the other side after a pause hands it
        # ownership and sync flows the other way.
        self._sync_owner = source_view
        if source_view is self.original_view:
            try:
                index = self.original_document.block_ids.index(block_id)
            except ValueError:
                return
            dst_index, dst_fraction = self.book_sync.original_to_translation(
                index, fraction
            )
            target_id = self.translation_document.block_ids[dst_index]
            self._arm_sync_gesture()
            self.translation_view.scroll_to(target_id, dst_fraction)
        else:
            try:
                index = self.translation_document.block_ids.index(block_id)
            except ValueError:
                return
            dst_index, dst_fraction = self.book_sync.translation_to_original(
                index, fraction
            )
            target_id = self.original_document.block_ids[dst_index]
            self._arm_sync_gesture()
            self.original_view.scroll_to(target_id, dst_fraction)

    def _arm_sync_gesture(self) -> None:
        """Open the in-flight window in which the follower's echo is ignored, and
        (re)start the timer that closes it. Re-arming on each mirror keeps
        ownership while the user keeps scrolling one side."""
        self._sync_in_flight = True
        self._sync_gesture_timer.start()

    def _end_sync_gesture(self) -> None:
        """Close the in-flight window. The next genuine scroll on either side now
        claims ownership, so the user can drive whichever view they grab."""
        self._sync_in_flight = False

    def _on_original_clicked(self, block_id: str) -> None:
        self._selected_original = block_id
        self.original_view.set_selected(block_id)
        self._update_add_enabled()

    def _on_translation_clicked(self, block_id: str) -> None:
        self._selected_translation = block_id
        self.translation_view.set_selected(block_id)
        self._update_add_enabled()

    def _update_add_enabled(self) -> None:
        self.add_button.setEnabled(
            self._selected_original is not None
            and self._selected_translation is not None
        )

    def _on_add_clicked(self) -> None:
        if self._selected_original is None or self._selected_translation is None:
            return
        self.anchor_store.add(self._selected_original, self._selected_translation)
        self.refresh()
        self._on_changed()

        # Clear both selections; the just-bound blocks now show as anchored.
        self._selected_original = None
        self._selected_translation = None
        self.original_view.set_selected("")
        self.translation_view.set_selected("")
        self._update_add_enabled()
        self._refresh_highlights()

    def _refresh_highlights(self) -> None:
        original_ids = [pair[0] for pair in self.anchor_store.anchors]
        translation_ids = [pair[1] for pair in self.anchor_store.anchors]
        self.original_view.set_anchored(original_ids)
        self.translation_view.set_anchored(translation_ids)

    def refresh(self) -> None:
        self.anchor_list.clear()
        # Show the anchors lowest-first by the original block's position in the
        # document. Sorting by block index (not the id string) keeps "b100" after
        # "b7". Anchors whose id is no longer in the document sort to the end.
        # This orders the display only; the stored order is untouched.
        block_index = {
            bid: i for i, bid in enumerate(self.original_document.block_ids)
        }
        ordered = sorted(
            self.anchor_store.anchors,
            key=lambda pair: block_index.get(pair[0], len(block_index)),
        )
        for original_id, translation_id in ordered:
            item = QListWidgetItem(f"{original_id}  =  {translation_id}")
            item.setData(_ORIGINAL_ID_ROLE, original_id)
            item.setData(_TRANSLATION_ID_ROLE, translation_id)
            self.anchor_list.addItem(item)

    def _on_anchor_clicked(self, item: QListWidgetItem) -> None:
        original_id = item.data(_ORIGINAL_ID_ROLE)
        translation_id = item.data(_TRANSLATION_ID_ROLE)
        # Jump both views to the pair and emphasise it; this does NOT change the
        # selection state, so it cannot enable "Add anchor here".
        self.original_view.scroll_to(original_id, 0.0)
        self.translation_view.scroll_to(translation_id, 0.0)
        self.original_view.set_jump(original_id)
        self.translation_view.set_jump(translation_id)

    def _remove_selected(self) -> None:
        item = self.anchor_list.currentItem()
        if item is None:
            return
        original_id = item.data(_ORIGINAL_ID_ROLE)
        self.anchor_store.remove(original_id)
        self.refresh()
        self._refresh_highlights()
        self._on_changed()

    def closeEvent(self, event) -> None:
        # Persist the editor's own scroll position so it reopens here next time,
        # separately from the reader. The shared store flushes in-flight writes
        # on app shutdown (BookPanel.close_doc -> anchor_store.shutdown).
        self.anchor_store.set_scroll(
            EDITOR_SURFACE, self._original_scroll, self._translation_scroll
        )
        super().closeEvent(event)
