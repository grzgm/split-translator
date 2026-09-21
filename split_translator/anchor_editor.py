"""Side-by-side anchor editor: click a paragraph in each edition to select it,
then bind the two selections into an anchor. Saved anchors stay highlighted in
both views, over every paragraph their group covers; clicking an anchor in the
list jumps both views to it."""

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .anchor_book_view import AnchorBookView
from .anchor_groups import add_conflict, group_paragraphs, resolve_manual
from .anchor_store import EDITOR_SURFACE, AnchorStore
from .book_loader import BookDocument, resolve_position
from .book_sync import SectionMap, kept_range
from .normalise_panel import NormalisePanel
from .normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE, NormaliseSpec
from .skip_panel import AT_END, AT_START, SkipPanel
from .sync_gesture import SyncGesture

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
        section_map: SectionMap,
        profile: QWebEngineProfile,
        on_changed,
        on_spec_changed=None,
        parent=None,
    ):
        super().__init__(parent)
        self.original_document = original_document
        self.translation_document = translation_document
        self.anchor_store = anchor_store
        self.section_map = section_map
        self._profile_ref = profile
        self._on_changed = on_changed
        # Called with (side, NormaliseSpec) whenever a multiplier changes, so
        # the owner can apply the same change to the reader's views. The two
        # surfaces share one set of multipliers, because they exist to line the
        # editions up with each other rather than to suit one screen.
        self._on_spec_changed = on_spec_changed

        self._selected_original: str | None = None
        self._selected_translation: str | None = None
        self.sync_enabled = True

        # Both editions are visible at once (unlike the reader's tabs), so a
        # mirrored scroll echoes back from the view it moved. Only the side the
        # user last touched drives sync; see sync_gesture.
        self._gesture = SyncGesture(self)

        # The editor remembers its own scroll position, separate from the
        # reader. Seed from the editor surface and write it back on close. A
        # saved position can name a block that is no longer a paragraph, so it
        # reopens at the next paragraph instead.
        original, translation = self.anchor_store.get_scroll(EDITOR_SURFACE)
        self._original_scroll = resolve_position(
            self.original_document.block_ids, original
        )
        self._translation_scroll = resolve_position(
            self.translation_document.block_ids, translation
        )

        # Paragraph-spacing normalisation for the editor, persisted per book pair
        # and independent of the reader's flag (default ON). Seeded so both views
        # build with it already applied.
        self._normalise = self.anchor_store.get_normalise(EDITOR_SURFACE)

        # This book pair's per-edition multipliers, shared with the reader.
        # Seeded so both views build with them already applied.
        self._original_spec, self._translation_spec = (
            self.anchor_store.get_normalise_specs()
        )
        # Multipliers changed but not yet written. Every AnchorStore.save()
        # spawns a write worker, so a held-down spin box arrow would spawn one
        # per step; the timer coalesces them. Applying to the views is NOT
        # debounced, which is what makes tuning feel live.
        self._spec_save_timer = QTimer(self)
        self._spec_save_timer.setSingleShot(True)
        self._spec_save_timer.timeout.connect(self._save_specs)

        # Skip fields changed but not yet written, coalesced the same way as the
        # multipliers. The store already holds them in memory, so the sections
        # are rebuilt at once; only the write waits.
        self._skip_save_timer = QTimer(self)
        self._skip_save_timer.setSingleShot(True)
        self._skip_save_timer.timeout.connect(self._save_skip)

        self.init_ui()
        self._push_sections()
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
            normalise=self._normalise,
            spec=self._original_spec,
        )
        self.translation_view = AnchorBookView(
            self.translation_document,
            self._profile_ref,
            initial_scroll=self._translation_scroll,
            normalise=self._normalise,
            spec=self._translation_spec,
        )
        self.original_view.block_clicked.connect(self._on_original_clicked)
        self.translation_view.block_clicked.connect(self._on_translation_clicked)
        # Optional synced scrolling between the two sides, by section, like the
        # main reader. The scrolled signal is separate from block_clicked, so
        # syncing never interferes with click-to-select.
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
        # Even out paragraph spacing across books, independent of the reader's
        # flag. Seeded from the persisted editor-surface value (default on).
        self.normalise_checkbox = QCheckBox("Normalise")
        self.normalise_checkbox.setChecked(self._normalise)
        self.normalise_checkbox.stateChanged.connect(self.toggle_normalise)
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        controls.addWidget(self.normalise_checkbox)
        controls.addWidget(self.sync_checkbox)
        controls.addStretch()
        bottom.addLayout(controls)

        # Explains a refused anchor. Empty otherwise.
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        bottom.addWidget(self.status_label)

        self.anchor_list = QListWidget()
        self.anchor_list.itemClicked.connect(self._on_anchor_clicked)

        # The multipliers sit beside the list rather than under it: they are
        # tuned while watching the two books above, so they must not push the
        # books off the screen.
        self.normalise_panel = NormalisePanel()
        self.normalise_panel.set_specs(self._original_spec, self._translation_spec)
        self.normalise_panel.changed.connect(self._apply_normalise_spec)
        # Start greyed to match the seeded flag: the multipliers do nothing in
        # this window while normalisation is off (see toggle_normalise).
        self.normalise_panel.setEnabled(self._normalise)

        # How many paragraphs each edition leaves out at its start and end,
        # seeded from the stored first and last kept paragraphs.
        self.skip_panel = SkipPanel(
            len(self.original_document.block_ids),
            len(self.translation_document.block_ids),
        )
        for side in (ORIGINAL_SIDE, TRANSLATION_SIDE):
            ids = self._ids(side)
            kept = kept_range(ids, *self.anchor_store.get_skip(side))
            self.skip_panel.set_skip(side, kept.start, len(ids) - kept.stop)
        self.skip_panel.changed.connect(self._on_skip_changed)
        self.skip_panel.from_selection.connect(self._skip_from_selection)

        # One tab per tool, so the books above keep their height.
        self.side_tabs = QTabWidget()
        self.side_tabs.addTab(self.skip_panel, "Skip")
        self.side_tabs.addTab(self.normalise_panel, "Spacing")

        # Even by default and draggable, like the vertical splitter above.
        self.bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.bottom_splitter.addWidget(self.anchor_list)
        self.bottom_splitter.addWidget(self.side_tabs)
        self.bottom_splitter.setStretchFactor(0, 1)
        self.bottom_splitter.setStretchFactor(1, 1)
        self.bottom_splitter.setSizes([400, 400])
        bottom.addWidget(self.bottom_splitter)
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

    def set_section_map(self, section_map: SectionMap) -> None:
        """The owner rebuilt the sections after an anchor change. Use the new
        map and give both views its starts."""
        self.section_map = section_map
        self._push_sections()

    def _push_sections(self) -> None:
        self.original_view.set_sections(
            self.section_map.section_starts(ORIGINAL_SIDE)
        )
        self.translation_view.set_sections(
            self.section_map.section_starts(TRANSLATION_SIDE)
        )

    def toggle_normalise(self, state) -> None:
        # Flip paragraph-spacing normalisation on both editor views live (no
        # reload, so scroll positions are kept) and persist for this book pair
        # under the editor surface, independent of the reader's flag.
        self._normalise = state == Qt.CheckState.Checked.value
        self.original_view.set_normalise(self._normalise)
        self.translation_view.set_normalise(self._normalise)
        self.anchor_store.set_normalise(EDITOR_SURFACE, self._normalise)
        # The multipliers do nothing in this window while normalisation is off
        # (the injected stylesheet is disabled outright), so say so rather than
        # leaving live-looking controls that change nothing. The reader's own
        # Normalise flag is separate and independent (default ON), so its views
        # keep applying these same multipliers regardless of this toggle.
        self.normalise_panel.setEnabled(self._normalise)

    def _apply_normalise_spec(self, side: str, spec: NormaliseSpec) -> None:
        """One edition's multipliers changed in the panel. Apply to that side's
        view at once, schedule the write, and tell the owner so the reader's
        matching view follows."""
        if side == ORIGINAL_SIDE:
            self._original_spec = spec
            self.original_view.set_normalise_spec(spec)
        else:
            self._translation_spec = spec
            self.translation_view.set_normalise_spec(spec)
        self._spec_save_timer.start(300)
        if self._on_spec_changed is not None:
            self._on_spec_changed(side, spec)

    def _save_specs(self) -> None:
        """Write both editions' multipliers. Called by the debounce timer, and
        directly on close so a pending edit is not lost.

        Reads straight from the panel rather than self._original_spec /
        self._translation_spec: those two fields are updated only by
        _apply_normalise_spec, so they would go stale against any future call
        to NormalisePanel.set_specs (which deliberately does not emit) made
        outside construction and reset(). The panel is the source of truth for
        what gets written; the two fields still just seed the views at
        construction."""
        self._spec_save_timer.stop()
        self.anchor_store.set_normalise_specs(*self.normalise_panel.specs())

    def _ids(self, side: str) -> list[str]:
        if side == ORIGINAL_SIDE:
            return self.original_document.block_ids
        return self.translation_document.block_ids

    def _view(self, side: str):
        if side == ORIGINAL_SIDE:
            return self.original_view
        return self.translation_view

    def _on_skip_changed(self, side: str, which: str) -> None:
        """A skip field changed. Store the first and last kept paragraphs (the
        write waits for the debounce), have the owner rebuild the sections in
        both windows, and show where the kept range now begins or ends."""
        ids = self._ids(side)
        if not ids:
            return
        start, end = self.skip_panel.skip(side)
        first_kept = ids[start]
        last_kept = ids[len(ids) - 1 - end]
        self.anchor_store.set_skip(
            side, first_kept if start else None, last_kept if end else None
        )
        self._skip_save_timer.start(300)
        self._on_changed()
        self.refresh()
        boundary = first_kept if which == AT_START else last_kept
        view = self._view(side)
        view.scroll_to(boundary, 0.0)
        view.set_jump(boundary)

    def _skip_from_selection(self, side: str, which: str) -> None:
        """Skip everything before (at the start) or after (at the end) the
        paragraph selected in that edition. A selection outside the kept range
        (after the last kept paragraph for the start, before the first kept
        paragraph for the end) is refused with a status message rather than
        clamped, since clamping it would silently collapse the kept range
        instead of doing what was asked."""
        if side == ORIGINAL_SIDE:
            selected = self._selected_original
        else:
            selected = self._selected_translation
        ids = self._ids(side)
        if selected is None or selected not in ids:
            self.status_label.setText(f"Select a paragraph in the {side} first")
            return
        position = ids.index(selected)
        start, end = self.skip_panel.skip(side)
        if which == AT_START and position > len(ids) - 1 - end:
            self.status_label.setText(
                "The selected paragraph is after the last kept paragraph"
            )
            return
        if which == AT_END and position < start:
            self.status_label.setText(
                "The selected paragraph is before the first kept paragraph"
            )
            return
        self.status_label.setText("")
        value = position if which == AT_START else len(ids) - 1 - position
        self.skip_panel.box(side, which).setValue(value)

    def _save_skip(self) -> None:
        """Write the skip fields. Called by the debounce timer."""
        self._skip_save_timer.stop()
        self.anchor_store.save()

    def _sync_from(
        self,
        source_view,
        block_id: str,
        fraction: float,
        section: int = -1,
        share: float = 0.0,
    ) -> None:
        """Mirror a scroll on one side to the other: same section, same share
        of its height.

        Only the side the user last touched drives sync. A scroll from the other
        side while a mirror settles is that mirror's echo; ignoring it keeps the
        scrolled side smooth instead of both sides snapping (see sync_gesture)."""
        # Remember the latest position of whichever side moved so the editor
        # reopens here next time (independent of the reader). Cache before any
        # early return so positions are tracked even with sync off or on an echo.
        if source_view is self.original_view:
            self._original_scroll = (block_id, fraction)
        else:
            self._translation_scroll = (block_id, fraction)
        if not self.sync_enabled:
            return
        if not self._gesture.allow(source_view):
            return
        # No section, or one from before the sections were rebuilt: nothing to
        # pass on (see BookPanel._sync_from).
        if section < 0 or section >= self.section_map.section_count:
            return
        if source_view is self.original_view:
            other_view, other_document = (
                self.translation_view,
                self.translation_document,
            )
        else:
            other_view, other_document = self.original_view, self.original_document
        if not other_document.block_ids:
            # The other edition has no text paragraphs (a scanned PDF, say),
            # so there is nothing to follow this scroll.
            return
        self._gesture.begin_mirror()
        other_view.scroll_to_section(section, share)

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
        original_id = self._selected_original
        translation_id = self._selected_translation
        if (original_id, translation_id) in self.anchor_store.anchors:
            self.status_label.setText(
                f"{original_id} = {translation_id} is already an anchor"
            )
            self._clear_selection()
            return
        # An anchor on a paragraph that is already anchored joins that group,
        # which is how one paragraph is matched to several. One that would
        # overlap or cross another group is refused, and the selection stays so
        # either side can be moved and tried again.
        blocking = add_conflict(
            self.anchor_store.anchors,
            (original_id, translation_id),
            self.original_document.block_ids,
            self.translation_document.block_ids,
        )
        if blocking is not None:
            self.status_label.setText(
                f"Not added: {original_id} = {translation_id} would overlap or "
                f"cross the anchor {blocking[0]} = {blocking[1]}"
            )
            return
        self.anchor_store.add(original_id, translation_id)
        self.status_label.setText("")
        self.refresh()
        self._on_changed()
        # The just-bound paragraphs now show as anchored.
        self._clear_selection()
        self._refresh_highlights()

    def _clear_selection(self) -> None:
        self._selected_original = None
        self._selected_translation = None
        self.original_view.set_selected("")
        self.translation_view.set_selected("")
        self._update_add_enabled()

    def _refresh_highlights(self) -> None:
        # Every paragraph a group covers is highlighted, the ones between its
        # first and last included, so a paragraph matched to several shows the
        # whole run it matches. Anchors ignored on load are not drawn.
        groups, _conflicting = resolve_manual(
            self.anchor_store.anchors,
            self.original_document.block_ids,
            self.translation_document.block_ids,
        )
        original_ids: list[str] = []
        translation_ids: list[str] = []
        for group in groups:
            originals, translations = group_paragraphs(
                group,
                self.original_document.block_ids,
                self.translation_document.block_ids,
            )
            original_ids.extend(originals)
            translation_ids.extend(translations)
        self.original_view.set_anchored(original_ids)
        self.translation_view.set_anchored(translation_ids)

    def refresh(self) -> None:
        self.anchor_list.clear()
        # An anchor that overlaps or crosses earlier ones (only possible in a
        # hand-edited or older file) is kept but ignored for sync; say so.
        groups, conflicting = resolve_manual(
            self.anchor_store.anchors,
            self.original_document.block_ids,
            self.translation_document.block_ids,
        )
        # Anchors in front or back matter are kept but ignored for sync.
        original_kept = kept_range(
            self.original_document.block_ids,
            *self.anchor_store.get_skip(ORIGINAL_SIDE),
        )
        translation_kept = kept_range(
            self.translation_document.block_ids,
            *self.anchor_store.get_skip(TRANSLATION_SIDE),
        )
        skipped = {
            anchor
            for group in groups
            if not group.within(original_kept, translation_kept)
            for anchor in group.anchors
        }
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
            label = f"{original_id}  =  {translation_id}"
            if (original_id, translation_id) in conflicting:
                label += "  (conflicts)"
            if (original_id, translation_id) in skipped:
                label += "  (skipped)"
            item = QListWidgetItem(label)
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
        self.anchor_store.remove(
            item.data(_ORIGINAL_ID_ROLE), item.data(_TRANSLATION_ID_ROLE)
        )
        self.status_label.setText("")
        self.refresh()
        self._refresh_highlights()
        self._on_changed()

    def closeEvent(self, event) -> None:
        # Flush a pending spec edit BEFORE the scroll write below, not after.
        # The scroll write always runs; the spec flush only runs when an edit
        # is still sitting in the debounce. AnchorStore.save() always dumps
        # the store's full current state (scroll and specs together), so
        # flushing the spec first means the ALWAYS-needed scroll write is also
        # the LAST write, and its save() call is the one that ends up carrying
        # the just-flushed spec to disk together with the scroll position,
        # rather than the reverse order leaving the (rarer) spec flush as an
        # extra, separate write tacked on after the routine scroll one.
        # BookPanel.close_doc closes this window before shutting the store
        # down, so any edit still sitting in the debounce must be flushed here.
        if self._spec_save_timer.isActive():
            self._save_specs()
        # A pending skip change is already in the store's memory, and the
        # scroll write below saves the whole store, so the debounce can go.
        self._skip_save_timer.stop()
        # Persist the editor's own scroll position so it reopens here next time,
        # separately from the reader. The shared store flushes in-flight writes
        # on app shutdown (BookPanel.close_doc -> anchor_store.shutdown).
        self.anchor_store.set_scroll(
            EDITOR_SURFACE, self._original_scroll, self._translation_scroll
        )
        super().closeEvent(event)
