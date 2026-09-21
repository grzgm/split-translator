"""Tabbed book panel showing original and translation editions in web views, with
native full-text search and section-based scroll sync."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
)

from .anchor_editor import AnchorEditor
from .anchor_groups import resolve
from .anchor_store import READER_SURFACE, AnchorStore, anchor_path_for
from .block_ids import resolve_position
from .book_loader import load_book
from .book_sync import SectionMap, kept_range
from .book_view import BookView
from .config import Config
from .layout import LAYOUT_BOOK, normalise_layout
from .normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE, NormaliseSpec
from .sync_gesture import SyncGesture


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

        # A workspace can be opened before its books are chosen, so this panel
        # has an empty state. Everything below that reads a document, an anchor
        # store or a view is skipped, and init_ui puts a placeholder where the
        # tabs would go. Only the both-blank case reaches here: a path that is
        # set but unreadable is caught by the workspace session in app.py,
        # which returns to the picker.
        self.has_books = bool(config.original_path and config.translation_path)

        if self.has_books:
            self.original_document = load_book(config.original_path)
            self.translation_document = load_book(config.translation_path)

            self.anchor_store = AnchorStore(
                anchor_path_for(
                    config.original_path,
                    config.translation_path,
                    config.dir,
                ),
                config.original_path,
                config.translation_path,
            )
            self.section_map = self._build_section_map()
        else:
            # No anchor store either: its file is keyed on a hash of the two
            # book paths, so building one here would leave a junk file keyed on
            # the empty pair.
            self.original_document = None
            self.translation_document = None
            self.anchor_store = None
            self.section_map = None

        self.anchor_editor = None

        # Latest scroll position per edition, updated as the views scroll and
        # written on close so the next launch reopens where reading stopped.
        # Seeded from the store so an unchanged session re-saves the same spot.
        # The reader and the anchor editor track their positions separately.
        if self.has_books:
            original, translation = self.anchor_store.get_scroll(READER_SURFACE)
            # A saved position can name a block that is no longer a paragraph,
            # so it reopens at the next paragraph instead.
            self._original_scroll = resolve_position(
                self.original_document.block_ids, original
            )
            self._translation_scroll = resolve_position(
                self.translation_document.block_ids, translation
            )
        else:
            self._original_scroll, self._translation_scroll = None, None

        # Paragraph-spacing normalisation for the reader, persisted per book pair
        # (default ON). Seeded here so the views can be built with it already
        # applied, avoiding a flash of the book's raw spacing on open.
        self._normalise = (
            self.anchor_store.get_normalise(READER_SURFACE) if self.has_books else True
        )

        # This book pair's per-edition normalisation multipliers, set in the
        # anchor editor and shared with the reader: they exist to line the two
        # editions up with each other, so one set serves both surfaces.
        self._original_spec, self._translation_spec = (
            self.anchor_store.get_normalise_specs()
            if self.has_books
            else (NormaliseSpec(), NormaliseSpec())
        )

        # The section position the hidden tab SHOULD be at, set when a scroll
        # on the active tab is mirrored. This is the source of truth for the
        # hidden side on a tab switch: a section position is re-measured
        # against the shown layout, unlike the hidden view's own
        # self-reported scroll, which drifts because a hidden page lays out at a
        # provisional width. None until the first mirror. Cleared once the
        # user scrolls the tab themselves (their position then supersedes the
        # mirrored one), and when the sections are rebuilt (the numbers belonged
        # to the old sections).
        self._original_sync_target: tuple[int, float] | None = None
        self._translation_sync_target: tuple[int, float] | None = None

        # Which arrangement the two editions sit in. Set before init_ui because
        # it decides what init_ui builds, and fixed for the life of the window:
        # choosing the other view rebuilds it (see layout.py).
        self._layout = normalise_layout(config.layout)

        # With both editions on screen, a mirrored scroll echoes back from the
        # edition it moved, so only the edition last touched may drive (see
        # sync_gesture). Tabs need no guard: a hidden tab never mirrors.
        self._gesture = SyncGesture(self) if self._layout == LAYOUT_BOOK else None

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

        # Even out paragraph spacing across books (see normalise_spec.NormaliseSpec).
        # Seeded from the persisted per-book-pair flag (default on).
        self.normalise_checkbox = QCheckBox("Normalise")
        self.normalise_checkbox.setChecked(self._normalise)
        self.normalise_checkbox.stateChanged.connect(self.toggle_normalise)

        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)
        nav_layout.addWidget(self.match_label)
        nav_layout.addStretch()
        nav_layout.addWidget(self.normalise_checkbox)
        nav_layout.addWidget(self.sync_checkbox)
        nav_layout.addWidget(self.position_label)
        layout.addLayout(nav_layout)

        if not self.has_books:
            # No books yet. The nav row above is built and disabled rather than
            # hidden, so every widget the rest of this class refers to exists.
            self.original_view = None
            self.translation_view = None
            self.tabs = None
            for widget in (
                self.prev_button,
                self.next_button,
                self.sync_checkbox,
                self.normalise_checkbox,
            ):
                widget.setEnabled(False)
            placeholder = QLabel(
                "No books set for this workspace.\n\n"
                "Choose them from View, then Workspaces..."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setWordWrap(True)
            # The placeholder takes every spare pixel, the way the tab widget
            # does when there are books. Without the stretch the nav row above
            # absorbs it instead, because its two QLabels grow vertically, and
            # the buttons end up floating a quarter of the way down the panel.
            layout.addWidget(placeholder, 1)
            return

        self.original_view = BookView(
            self.original_document,
            self.profile,
            initial_scroll=self._original_scroll,
            normalise=self._normalise,
            spec=self._original_spec,
        )
        self.translation_view = BookView(
            self.translation_document,
            self.profile,
            initial_scroll=self._translation_scroll,
            normalise=self._normalise,
            spec=self._translation_spec,
        )

        # Stretch 1 for the same reason the placeholder above has it: the nav
        # row's two QLabels grow vertically, so without it they swallow the
        # spare height and the editions end up in a short band down the panel.
        layout.addWidget(self._build_views(), 1)

        self.original_view.scrolled.connect(
            lambda bid, frac, section, share: self._sync_from(
                self.original_view, bid, frac, section, share
            )
        )
        self.translation_view.scrolled.connect(
            lambda bid, frac, section, share: self._sync_from(
                self.translation_view, bid, frac, section, share
            )
        )
        self._push_sections()

    def _build_views(self):
        """The container holding the two editions, in this window's layout."""
        if self._layout == LAYOUT_BOOK:
            return self._build_side_by_side_views()
        return self._build_tabbed_views()

    def _build_tabbed_views(self) -> QTabWidget:
        """One edition at a time, the other hidden behind its tab."""
        self.tabs = QTabWidget()
        self.tabs.addTab(self.original_view, "Original")
        self.tabs.addTab(self.translation_view, "Translation")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        return self.tabs

    def _build_side_by_side_views(self) -> QSplitter:
        """Both editions at once, the Original on the left. There are no tabs,
        so neither edition is ever the hidden one and the corrections that exist
        for a hidden tab have nothing to correct."""
        self.tabs = None
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.original_view)
        split.addWidget(self.translation_view)
        split.setSizes([1, 1])
        return split

    def _on_tab_changed(self, _index: int) -> None:
        self._update_position_label()
        # The tab that just became visible was laid out against a provisional
        # (hidden) height, so any scroll mirrored into it while hidden landed at
        # a wrong pixel offset, and the view's own self-reported position
        # drifted to that wrong spot. Re-apply the right position against the
        # now-visible layout; BookView re-runs it as the layout settles.
        #
        # Prefer the section target (where sync DECIDED this tab should be) over
        # the view's drifted scroll cache. Fall back to the cache when there is
        # no pending target (sync off, the user last moved this tab themselves,
        # or the sections were rebuilt since).
        view = self.current_view()
        if view is self.original_view:
            target, position = self._original_sync_target, self._original_scroll
        else:
            target, position = (
                self._translation_sync_target,
                self._translation_scroll,
            )
        if target is not None:
            view.reapply_section(*target)
            return
        if position is None:
            return
        block_id, fraction = position
        if block_id:
            view.reapply_scroll(block_id, fraction)

    def _is_active(self, view) -> bool:
        """Whether this view is one the reader can see.

        In the book view both editions are on screen, so both are active and a
        scroll mirrors whichever way the reader moves. With tabs only the front
        one is, which is what keeps a mirrored scroll from bouncing back.
        """
        if self._layout == LAYOUT_BOOK:
            return True
        return view is self.current_view()

    def _sync_from(
        self,
        source_view,
        block_id: str,
        fraction: float,
        section: int = -1,
        share: float = 0.0,
    ) -> None:
        self._update_position_label()
        # A scroll reported by the HIDDEN tab while it has a pending sync target
        # is a drift echo of the mirrored scroll: the hidden page laid out at a
        # provisional width, so the position it reports is wrong. Ignore it
        # entirely, so it neither corrupts the persisted cache nor bounces back
        # as a reverse sync. The correct position is the target, already
        # recorded and re-applied on the next tab switch.
        is_hidden = not self._is_active(source_view)
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
        # Only mirror from an edition the reader can see.
        if not self._is_active(source_view):
            return
        # In the book view the edition just mirrored into reports the scroll
        # back a moment later. Mirrored again, that echo would pull the edition
        # the reader is scrolling.
        if self._gesture is not None and not self._gesture.allow(source_view):
            return
        # The active tab is the one the user is moving, so its own sync target
        # is now stale: their position supersedes it. Clear it so a later
        # switch back re-applies the user's real spot, not an old mirrored one.
        if source_view is self.original_view:
            self._original_sync_target = None
        else:
            self._translation_sync_target = None
        # No section: a restored position, or a page whose section starts have
        # not arrived yet. A section this map does not have: a report measured
        # against starts from before a rebuild. Neither can be passed on.
        if section < 0 or section >= self.section_map.section_count:
            return

        if source_view is self.original_view:
            other_view = self.translation_view
            other_side = TRANSLATION_SIDE
            other_document = self.translation_document
        else:
            other_view = self.original_view
            other_side = ORIGINAL_SIDE
            other_document = self.original_document
        if not other_document.block_ids:
            # The other edition has no text paragraphs (a scanned PDF, say), so
            # there is nothing to follow this scroll.
            return
        # The same section at the same share of its height, passed unchanged:
        # both editions measure their own sections, so no mapping runs here.
        # Record it as the other side's target (re-applied on a tab switch,
        # since a hidden tab's scroll can land wrong) and cache the paragraph it
        # falls in, so close persists the right spot and not a hidden drift.
        target = (section, share)
        position = self.section_map.paragraph_at(other_side, section, share)
        if other_view is self.translation_view:
            self._translation_sync_target = target
            self._translation_scroll = position
        else:
            self._original_sync_target = target
            self._original_scroll = position
        self._begin_mirror()
        other_view.scroll_to_section(section, share)

    def _begin_mirror(self) -> None:
        """Open the echo window just before scrolling the other edition. Only
        the book view has a guard; with tabs this does nothing."""
        if self._gesture is not None:
            self._gesture.begin_mirror()

    def _update_position_label(self) -> None:
        view = self.current_view()
        if view is self.original_view:
            total = len(self.original_document.block_ids)
        else:
            total = len(self.translation_document.block_ids)
        self.position_label.setText(f"{total} paragraphs")

    def toggle_sync(self, state):
        self.sync_enabled = state == Qt.CheckState.Checked.value

    def toggle_normalise(self, state):
        # Flip paragraph-spacing normalisation on both editions live (no reload,
        # so the scroll position is kept) and persist the choice for this book
        # pair. The hidden tab picks up the same flag; its style toggle is
        # layout-independent, so it is correct when the user switches to it.
        if not self.has_books:
            return
        self._normalise = state == Qt.CheckState.Checked.value
        self.original_view.set_normalise(self._normalise)
        self.translation_view.set_normalise(self._normalise)
        self.anchor_store.set_normalise(READER_SURFACE, self._normalise)

    def current_view(self) -> BookView | None:
        if not self.has_books:
            return None
        # No tabs means the book view, where both editions are on screen. The
        # Original is the answer there: it is the search target, and the block
        # count in the nav row describes it.
        if self.tabs is None or self.tabs.currentIndex() == 0:
            return self.original_view
        return self.translation_view

    def update_match_label(self):
        if not self.match_count:
            self.match_label.setText("No matches" if self.search_term else "")
        else:
            self.match_label.setText(f"{self.current_match} / {self.match_count}")

    def _ensure_original_tab(self) -> None:
        # The reader searches the Original edition only, so every find runs
        # against original_view. If the Translation tab is showing, switch to
        # Original first so the highlighted match the user steps through is on
        # the tab they are looking at. (The Translation edition is still fully
        # readable; it just is not the search target.)
        if self.tabs is None:
            # Book view: both editions are on screen, so there is no tab to
            # bring to the front.
            return
        if self.tabs.currentIndex() != 0:
            self.tabs.setCurrentIndex(0)

    def search(self, term: str) -> None:
        if not self.has_books:
            return
        self.search_term = term.strip()
        if not self.search_term:
            # Clearing the term clears the search marks in both editions.
            self.original_view.clear_search_mark()
            self.translation_view.clear_search_mark()
            return
        self.current_match = 0
        self._ensure_original_tab()
        self.original_view.find(self.search_term, True, self._on_find_result)

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
        # Auto-fill the flashcard's first example from the book. Search always
        # runs on the Original edition (no cross-edition fuzzing), so read the
        # sentence around the active match and re-emit it. The flashcard side
        # decides whether to use it (never on a saved card, and only while the
        # example is still free).
        if count:
            self.original_view.match_sentence(
                self.search_term, active, self.book_sentence_matched.emit
            )

    def current_match_sentence(self, callback) -> None:
        """Extract the sentence around the CURRENT match on demand and pass it to
        callback(str). Search always runs on the Original edition, so the current
        match is always an Original one; yields its sentence, or "" when there is
        no current match. Used by the Ctrl+T contextual-translation prompt. The
        active tab is not consulted: the user may have switched to Translation to
        read after searching, but the match still belongs to the Original."""
        if not self.has_books:
            callback("")
            return
        if self.current_match:
            self.original_view.match_sentence(
                self.search_term, self.current_match, callback
            )
        else:
            callback("")

    def go_to_next(self) -> None:
        if not self.match_count:
            return
        self._ensure_original_tab()
        self.original_view.find(self.search_term, True, self._on_find_result)

    def go_to_previous(self) -> None:
        if not self.match_count:
            return
        self._ensure_original_tab()
        self.original_view.find(self.search_term, False, self._on_find_result)

    def _mark_current_match(self, active: int, count: int) -> None:
        # Highlight the paragraph holding the active match, and its counterpart
        # paragraphs in the other edition. Search always runs on the
        # Original edition, so the active match is always an Original one: mark
        # original_view and mirror onto translation_view, without inferring the
        # side from the active tab. With no match (or a blank term) clear both
        # marks. The paragraph is located from `active` (the find's 1-based match
        # index), not the scroll position, so a wrap-around to the first match
        # marks the right paragraph even though the findText callback can fire before
        # the scroll has moved.
        view = self.original_view
        other = self.translation_view
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
        active.mark_search_blocks([block_id])
        # Mark the counterpart paragraphs in the other edition. Marking is a
        # layout-independent CSS toggle, so it is safe on the hidden tab
        # (unlike a scroll, it cannot drift); the mark is already in place
        # when the user switches to it. Only mirror when sync is on, consistent
        # with scroll sync; otherwise clear the other side's stale mark.
        if not self.sync_enabled:
            other.clear_search_mark()
            return
        side = ORIGINAL_SIDE if active is self.original_view else TRANSLATION_SIDE
        # A paragraph in a group marks the whole group on the other side;
        # elsewhere, the paragraph at the same share of the section's text.
        counterpart = self.section_map.counterpart(side, block_id)
        if counterpart:
            other.mark_search_blocks(counterpart)
        else:
            other.clear_search_mark()

    def _build_section_map(self) -> SectionMap:
        """Sections from the anchors and skip fields as they stand, manual and
        automatic groups together. An anchor that cannot hold (a manual one
        overlapping or crossing earlier ones, an automatic one touching a
        manual group) is left out of sync; the anchor editor lists it."""
        original = self.original_document
        translation = self.translation_document
        resolved = resolve(
            self.anchor_store.anchors,
            self.anchor_store.auto_anchors,
            original.block_ids,
            translation.block_ids,
        )
        return SectionMap(
            original.block_ids,
            original.block_texts,
            translation.block_ids,
            translation.block_texts,
            resolved.groups,
            original_kept=kept_range(
                original.block_ids, *self.anchor_store.get_skip(ORIGINAL_SIDE)
            ),
            translation_kept=kept_range(
                translation.block_ids, *self.anchor_store.get_skip(TRANSLATION_SIDE)
            ),
        )

    def _push_sections(self) -> None:
        """Hand each view its section starts, live, with no reload."""
        self.original_view.set_sections(
            self.section_map.section_starts(ORIGINAL_SIDE)
        )
        self.translation_view.set_sections(
            self.section_map.section_starts(TRANSLATION_SIDE)
        )

    def _rebuild_sections(self) -> None:
        """The anchors or skip fields changed in the editor. Rebuild the
        sections, push them to the reader's views and to the open editor,
        which uses the same map."""
        self.section_map = self._build_section_map()
        # Section numbers from the old map point at the wrong place now.
        self._original_sync_target = None
        self._translation_sync_target = None
        self._push_sections()
        if self.anchor_editor is not None:
            self.anchor_editor.set_section_map(self.section_map)

    def open_anchor_editor(self) -> None:
        if not self.has_books:
            return
        if self.anchor_editor is None:
            self.anchor_editor = AnchorEditor(
                self.original_document,
                self.translation_document,
                self.anchor_store,
                self.section_map,
                self.profile,
                self._rebuild_sections,
                on_spec_changed=self._apply_normalise_spec,
            )
            self.anchor_editor.setWindowTitle("Anchor editor")
            self.anchor_editor.resize(1200, 800)
        self.anchor_editor.show()
        self.anchor_editor.raise_()

    def _apply_normalise_spec(self, side: str, spec: NormaliseSpec) -> None:
        """A multiplier changed in the anchor editor. Apply it to the reader's
        matching edition too, live, so both windows show the same spacing while
        it is being tuned. The editor never touches these views itself; this
        panel owns the editor and does the wiring."""
        if not self.has_books:
            return
        if side == ORIGINAL_SIDE:
            self._original_spec = spec
            self.original_view.set_normalise_spec(spec)
        else:
            self._translation_spec = spec
            self.translation_view.set_normalise_spec(spec)

    def close_doc(self) -> None:
        if not self.has_books:
            return
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
