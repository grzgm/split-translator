"""Tabbed book panel showing original and translation editions in web views, with
native full-text search and content-anchor scroll sync."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from .anchor_editor import AnchorEditor
from .anchor_store import READER_SURFACE, AnchorStore, anchor_path_for
from .book_loader import load_book
from .book_sync import BookSync
from .book_view import BookView
from .config import Config, CONFIG_DIR


class BookPanel(QFrame):
    # Emitted with the sentence around the active book match, but only for a
    # match on the Original edition. The main window routes it into the
    # flashcard editor's first example (see main_window.on_book_sentence_matched).
    book_sentence_matched = Signal(str)

    def __init__(self, config: Config, profile: QWebEngineProfile, parent=None):
        super().__init__(parent)
        self.config = config
        self.profile = profile

        self.search_term = ""
        self.match_count = 0
        self.current_match = 0
        self.sync_enabled = True

        self.original_document = load_book(config.original_path)
        self.translation_document = load_book(config.translation_path)

        self.anchor_store = AnchorStore(
            anchor_path_for(
                config.original_path,
                config.translation_path,
                CONFIG_DIR,
            ),
            config.original_path,
            config.translation_path,
        )
        self.book_sync = BookSync(
            len(self.original_document.block_ids),
            len(self.translation_document.block_ids),
        )
        self.book_sync.set_anchors(
            self.anchor_store.resolve(
                self.original_document.block_ids,
                self.translation_document.block_ids,
            )
        )

        self.anchor_editor = None

        # Latest scroll position per edition, updated as the views scroll and
        # written on close so the next launch reopens where reading stopped.
        # Seeded from the store so an unchanged session re-saves the same spot.
        # The reader and the anchor editor track their positions separately.
        self._original_scroll, self._translation_scroll = (
            self.anchor_store.get_scroll(READER_SURFACE)
        )

        # The anchor-mapped target the hidden tab SHOULD be at, set when a scroll
        # on the active tab is mirrored. This is the source of truth for the
        # hidden side on a tab switch: it is layout-independent (block id +
        # fraction) and correct, unlike the hidden view's own self-reported
        # scroll, which drifts because a hidden page lays out at a provisional
        # width. None until the first mirror. Cleared once the user scrolls the
        # tab themselves (their position then supersedes the mapped one).
        self._original_sync_target: tuple[str, float] | None = None
        self._translation_sync_target: tuple[str, float] | None = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        nav_layout = QHBoxLayout()

        self.prev_button = QPushButton("Prev")
        self.prev_button.clicked.connect(self.go_to_previous)
        self.prev_button.setEnabled(False)

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.go_to_next)
        self.next_button.setEnabled(False)

        self.match_label = QLabel("")
        self.position_label = QLabel("")

        self.sync_checkbox = QCheckBox("Sync")
        self.sync_checkbox.setChecked(True)
        self.sync_checkbox.stateChanged.connect(self.toggle_sync)

        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)
        nav_layout.addWidget(self.match_label)
        nav_layout.addStretch()
        nav_layout.addWidget(self.sync_checkbox)
        nav_layout.addWidget(self.position_label)
        layout.addLayout(nav_layout)

        self.tabs = QTabWidget()
        self.original_view = BookView(
            self.original_document,
            self.profile,
            initial_scroll=self._original_scroll,
        )
        self.translation_view = BookView(
            self.translation_document,
            self.profile,
            initial_scroll=self._translation_scroll,
        )
        self.tabs.addTab(self.original_view, "Original")
        self.tabs.addTab(self.translation_view, "Translation")
        layout.addWidget(self.tabs)

        self.original_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.original_view, bid, frac)
        )
        self.translation_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.translation_view, bid, frac)
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, _index: int) -> None:
        self._update_position_label()
        # The tab that just became visible was laid out against a provisional
        # (hidden) height, so any scroll mirrored into it while hidden baked a
        # wrong pixel offset, and the view's own self-reported position drifted
        # to that wrong spot. Re-apply the right block-and-fraction against the
        # now-visible layout; BookView re-runs it as the layout settles.
        #
        # Prefer the anchor-mapped sync target (what sync DECIDED this tab should
        # show) over the view's drifted scroll cache: the mapped target is
        # layout-independent and correct, whereas the cache can hold the hidden
        # view's wrong landing. Fall back to the cache when there is no pending
        # mapped target (sync off, or the user last moved this tab themselves).
        view = self.current_view()
        if view is self.original_view:
            position = self._original_sync_target or self._original_scroll
        else:
            position = self._translation_sync_target or self._translation_scroll
        if position is None:
            return
        block_id, fraction = position
        if block_id:
            view.reapply_scroll(block_id, fraction)

    def _sync_from(self, source_view, block_id: str, fraction: float) -> None:
        self._update_position_label()
        # A scroll reported by the HIDDEN tab while it has a pending mapped sync
        # target is a drift echo of the mirrored scroll: the hidden page laid out
        # at a provisional width, so the position it reports is wrong. Ignore it
        # entirely, so it neither corrupts the persisted cache nor bounces back
        # as a reverse sync. The correct position is the mapped target, already
        # recorded and re-applied on the next tab switch.
        is_hidden = source_view is not self.current_view()
        if source_view is self.original_view:
            has_pending = self._original_sync_target is not None
        else:
            has_pending = self._translation_sync_target is not None
        if is_hidden and has_pending:
            return
        # Remember the latest position of whichever view moved, so it can be
        # persisted on close. This fires for both user scrolls and mirrored
        # (synced) scrolls, so both editions stay current.
        if source_view is self.original_view:
            self._original_scroll = (block_id, fraction)
        else:
            self._translation_scroll = (block_id, fraction)
        if not self.sync_enabled:
            return
        # Only mirror from the active tab.
        if source_view is not self.current_view():
            return
        # The active tab is the one the user is moving, so its own mapped sync
        # target is now stale: their position supersedes it. Clear it so a later
        # switch back re-applies the user's real spot, not an old mapped one.
        if source_view is self.original_view:
            self._original_sync_target = None
        else:
            self._translation_sync_target = None

        if source_view is self.original_view:
            try:
                index = self.original_document.block_ids.index(block_id)
            except ValueError:
                return
            dst_index, dst_fraction = self.book_sync.original_to_translation(
                index, fraction
            )
            target_id = self.translation_document.block_ids[dst_index]
            # Record the intended (mapped) target for the hidden translation and
            # scroll it there. The scroll itself may land wrong because the tab
            # is hidden (provisional layout); the recorded target is what the
            # switch re-applies against the settled layout, so it is correct.
            # Also cache it as the side's scroll position so close-time
            # persistence saves the right spot, not the hidden view's drift.
            self._translation_sync_target = (target_id, dst_fraction)
            self._translation_scroll = (target_id, dst_fraction)
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
            self._original_sync_target = (target_id, dst_fraction)
            self._original_scroll = (target_id, dst_fraction)
            self.original_view.scroll_to(target_id, dst_fraction)

    def _update_position_label(self) -> None:
        view = self.current_view()
        if view is self.original_view:
            total = len(self.original_document.block_ids)
        else:
            total = len(self.translation_document.block_ids)
        self.position_label.setText(f"{total} blocks")

    def toggle_sync(self, state):
        self.sync_enabled = state == Qt.CheckState.Checked.value

    def current_view(self) -> BookView:
        if self.tabs.currentIndex() == 0:
            return self.original_view
        return self.translation_view

    def update_match_label(self):
        if not self.match_count:
            self.match_label.setText("No matches" if self.search_term else "")
        else:
            self.match_label.setText(f"{self.current_match} / {self.match_count}")

    def search(self, term: str) -> None:
        self.search_term = term.strip()
        if not self.search_term:
            # Clearing the term clears the section marks in both editions.
            self.original_view.clear_search_mark()
            self.translation_view.clear_search_mark()
            return
        self.current_match = 0
        self.current_view().find(self.search_term, True, self._on_find_result)

    def _on_find_result(self, active: int, count: int) -> None:
        # Single landing point for every find (initial search and Next/Prev). The
        # displayed number and the marked block both come from Chromium's own
        # activeMatch, so the counter is the match's absolute position in the
        # book (not "1 of N") and can never disagree with the highlighted block.
        self.match_count = count
        self.current_match = active if count else 0
        self.prev_button.setEnabled(count > 0)
        self.next_button.setEnabled(count > 0)
        self.update_match_label()
        self._mark_current_match(active, count)
        # Auto-fill the flashcard's first example from the book, but only for a
        # match on the Original edition (no cross-edition fuzzing): read the
        # sentence around the active match and re-emit it. The flashcard side
        # decides whether to use it (only while its card is unaltered).
        if count and self.current_view() is self.original_view:
            self.original_view.match_sentence(
                self.search_term, active, self.book_sentence_matched.emit
            )

    def go_to_next(self) -> None:
        if not self.match_count:
            return
        self.current_view().find(self.search_term, True, self._on_find_result)

    def go_to_previous(self) -> None:
        if not self.match_count:
            return
        self.current_view().find(self.search_term, False, self._on_find_result)

    def _mark_current_match(self, active: int, count: int) -> None:
        # Highlight the section holding the active match in the active edition,
        # and the anchor-equivalent section in the other edition. With no match
        # (or a blank term) clear both marks. The block is located from `active`
        # (the find's 1-based match index), not the scroll position, so a
        # wrap-around to the first match marks the right block even though the
        # findText callback can fire before the scroll has moved.
        view = self.current_view()
        other = (
            self.translation_view
            if view is self.original_view
            else self.original_view
        )
        if not count or not active or not self.search_term:
            view.clear_search_mark()
            other.clear_search_mark()
            return
        view.matched_block_id(
            self.search_term,
            active,
            lambda block_id: self._on_matched_block(view, other, block_id),
        )

    def _on_matched_block(self, active, other, block_id: str) -> None:
        if not block_id:
            active.clear_search_mark()
            other.clear_search_mark()
            return
        active.mark_search_block(block_id)
        # Mirror the mark to the anchor-equivalent block in the other edition.
        # Marking is a layout-independent CSS toggle, so it is safe on the hidden
        # tab (unlike a scroll, it cannot drift); the mark is already in place
        # when the user switches to it. Only mirror when sync is on, consistent
        # with scroll sync; otherwise clear the other side's stale mark.
        if not self.sync_enabled:
            other.clear_search_mark()
            return
        if active is self.original_view:
            src_ids = self.original_document.block_ids
            dst_ids = self.translation_document.block_ids
            mapper = self.book_sync.original_block_to_translation
        else:
            src_ids = self.translation_document.block_ids
            dst_ids = self.original_document.block_ids
            mapper = self.book_sync.translation_block_to_original
        try:
            index = src_ids.index(block_id)
        except ValueError:
            other.clear_search_mark()
            return
        # Map whole-block to whole-block (centre + round), so the marked
        # translation section is the one the original section overlaps, not the
        # block before it that a top-edge + truncate mapping would pick.
        dst_index = mapper(index)
        other.mark_search_block(dst_ids[dst_index])

    def _reseed_sync(self) -> None:
        self.book_sync.set_anchors(
            self.anchor_store.resolve(
                self.original_document.block_ids,
                self.translation_document.block_ids,
            )
        )

    def open_anchor_editor(self) -> None:
        if self.anchor_editor is None:
            self.anchor_editor = AnchorEditor(
                self.original_document,
                self.translation_document,
                self.anchor_store,
                self.book_sync,
                self.profile,
                self._reseed_sync,
            )
            self.anchor_editor.setWindowTitle("Anchor editor")
            self.anchor_editor.resize(1200, 800)
        self.anchor_editor.show()
        self.anchor_editor.raise_()

    def close_doc(self) -> None:
        # Web views own no file handles to close; clear any active find so the
        # native highlight does not linger.
        self.original_view.find("", True, lambda _a, _c: None)
        self.translation_view.find("", True, lambda _a, _c: None)
        # Close the anchor editor if open so its pages are released before the
        # shared web profile is torn down (avoids the "profile released but page
        # not deleted" warning).
        if self.anchor_editor is not None:
            self.anchor_editor.close()
        # Persist the last scroll position of each edition so the next launch
        # reopens where reading stopped. Uses the cached positions (updated as
        # the views scrolled), so no async page read is needed at close time.
        self.anchor_store.set_scroll(
            READER_SURFACE, self._original_scroll, self._translation_scroll
        )
        # Await any in-flight anchor write so anchors are not lost on quit.
        self.anchor_store.shutdown()
        # Delete each edition's backing temp HTML file (see book_render).
        self.original_view.release_rendered()
        self.translation_view.release_rendered()
