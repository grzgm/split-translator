"""The workspace picker: choose which reading project to open, and edit the
selected one's name and book paths.

Like every panel in the app this widget knows nothing about the others. It talks
only to workspace.py, and the main window reads its result and acts on it.

Edits to the detail form are written only by pressing Save. Leaving a workspace
with unsaved edits, by picking another row or by pressing Open, asks whether to
save them, discard them or stay put. Renaming moves the workspace's folder, so
it waits for that explicit press rather than happening as a side effect of
clicking elsewhere.

It writes every config.json it changes itself. The one thing it cannot do is
move the folder of the workspace that is currently open, because that
workspace's stores hold absolute paths into it and their save workers may have a
write in flight. That move is handed back through `rename` for the caller to
perform once closeEvent has flushed them.
"""

import json
from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .flashcards import load_cards
from .workspace import (
    Workspace,
    can_open,
    create_workspace,
    delete_workspace,
    duplicate_workspace,
    list_workspaces,
    rename_workspace_folder,
    save_workspace,
    slugify,
    taken_slugs,
)

# Shown in place of the counts while nothing is selected.
_NO_SELECTION = "No workspace selected"


def workspace_counts(workspace: Workspace) -> tuple[int, int]:
    """(cards, searches) for the summary line.

    The cards go through the flashcard store's own tolerant loader so the file
    shape is not duplicated. The history file is a plain JSON list and is read
    directly, because HistoryPanel.load_history is a method on a widget and this
    is not a widget's job.
    """
    cards = len(load_cards(workspace.dir / "flashcards.json"))
    try:
        with open(workspace.dir / "history.json", "r", encoding="utf-8") as f:
            history = json.load(f)
    except (json.JSONDecodeError, OSError):
        history = []
    return cards, len(history) if isinstance(history, list) else 0


class WorkspaceDialog(QDialog):
    """Pick a workspace to open, and edit the selected one's name and books.

    After an accepted exec(), `chosen` is the slug to open and `rename` is either
    None or the (old_slug, new_slug) folder move the caller must perform once the
    open workspace's stores have flushed.
    """

    def __init__(self, current_slug: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workspaces")
        self.resize(760, 380)

        self.current_slug = current_slug
        self.chosen: str | None = None
        self.rename: tuple[str, str] | None = None

        self._workspaces: list[Workspace] = []
        self._selected: Workspace | None = None
        # The name the selected workspace had when it was loaded into the form.
        # A folder move is only ever considered when this changes, so merely
        # opening a workspace whose slug no longer matches its name (an old
        # collision suffix) never quietly moves it.
        self._loaded_name = ""
        self._dirty = False
        # Set while the form is being populated, so filling the fields in code
        # does not look like the user typing.
        self._loading = False

        self.init_ui()
        self.reload(select=current_slug)

    def init_ui(self):
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self.on_row_changed)

        self.name_input = QLineEdit()
        self.original_input = QLineEdit()
        self.translation_input = QLineEdit()
        for field in (
            self.name_input,
            self.original_input,
            self.translation_input,
        ):
            field.textChanged.connect(self.on_edited)

        original_browse = QPushButton("Browse...")
        original_browse.clicked.connect(
            lambda: self.browse(self.original_input, "Choose the original book")
        )
        translation_browse = QPushButton("Browse...")
        translation_browse.clicked.connect(
            lambda: self.browse(
                self.translation_input, "Choose the translated book"
            )
        )

        # Which folder on disk this workspace is, so two workspaces sharing a
        # display name can still be told apart, and so the folder a rename will
        # move is visible before it happens.
        self.folder_label = QLabel("")
        self.summary_label = QLabel(_NO_SELECTION)
        # Reports a book that has moved, which is the main thing this screen is
        # here to repair, so it is shown rather than blocking the dialog.
        self.problem_label = QLabel("")

        form = QGridLayout()
        form.addWidget(QLabel("Name:"), 0, 0)
        form.addWidget(self.name_input, 0, 1, 1, 2)
        form.addWidget(QLabel("Original:"), 1, 0)
        form.addWidget(self.original_input, 1, 1)
        form.addWidget(original_browse, 1, 2)
        form.addWidget(QLabel("Translation:"), 2, 0)
        form.addWidget(self.translation_input, 2, 1)
        form.addWidget(translation_browse, 2, 2)
        form.addWidget(QLabel("Folder:"), 3, 0)
        form.addWidget(self.folder_label, 3, 1, 1, 2)
        form.addWidget(self.summary_label, 4, 1, 1, 2)
        form.addWidget(self.problem_label, 5, 1, 1, 2)
        form.setColumnStretch(1, 1)

        # Save governs the whole detail form, so it sits with the form rather
        # than in the dialog's own button row, where it would read as saving the
        # dialog. It is live only while there is something to write.
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_selected)
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_row.addWidget(self.save_button)

        detail_layout = QVBoxLayout()
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addLayout(form)
        detail_layout.addLayout(save_row)
        # Keeps the form and its Save button together at the top. The grid used
        # to hold a stretch row of its own for this; the stretch belongs out
        # here now, below the button, or the button would float to the bottom.
        detail_layout.addStretch()

        detail = QWidget()
        detail.setLayout(detail_layout)

        columns = QHBoxLayout()
        columns.addWidget(self.list_widget, 1)
        columns.addWidget(detail, 2)

        self.new_button = QPushButton("New")
        self.new_button.clicked.connect(self.new_workspace)
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        self.open_button = QPushButton("Open")
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.duplicate_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.open_button)

        layout = QVBoxLayout(self)
        layout.addLayout(columns)
        layout.addLayout(buttons)

    def selected(self) -> Workspace | None:
        """The workspace the form is currently showing."""
        return self._selected

    def reload(self, select: str | None = None):
        """Rebuild the list from disk and select a slug, or the first entry."""
        self._workspaces = list_workspaces()
        self._selected = None
        self._loading = True
        self.list_widget.clear()
        for workspace in self._workspaces:
            self.list_widget.addItem(self.label_for(workspace))
        self._loading = False

        if not self._workspaces:
            self.show_workspace(None)
            self.update_buttons()
            return
        row = 0
        if select is not None:
            slugs = [workspace.slug for workspace in self._workspaces]
            if select in slugs:
                row = slugs.index(select)
        self.list_widget.setCurrentRow(row)

    def label_for(self, workspace: Workspace) -> str:
        """The list row for a workspace, marking the one that is open."""
        if workspace.slug == self.current_slug:
            return f"{workspace.name}   (open)"
        return workspace.name

    def select_slug(self, slug: str):
        """Select a workspace by slug. Used by the tests and after New."""
        slugs = [workspace.slug for workspace in self._workspaces]
        if slug in slugs:
            self.list_widget.setCurrentRow(slugs.index(slug))

    def on_row_changed(self, row: int):
        """Settle the outgoing workspace's edits, then show the incoming one."""
        if self._loading:
            return
        if not self.leave_selected():
            self._restore_row()
            return
        if 0 <= row < len(self._workspaces):
            self.show_workspace(self._workspaces[row])
        else:
            self.show_workspace(None)

    def show_workspace(self, workspace: Workspace | None):
        """Populate the form. Does not count as user editing."""
        self._selected = workspace
        self._dirty = False
        self._loading = True
        if workspace is None:
            self.name_input.clear()
            self.original_input.clear()
            self.translation_input.clear()
            self.folder_label.setText("")
            self.summary_label.setText(_NO_SELECTION)
            self._loaded_name = ""
        else:
            self.name_input.setText(workspace.name)
            self.original_input.setText(workspace.original_path)
            self.translation_input.setText(workspace.translation_path)
            # The folder as it stands now, not the one a pending rename would
            # move it to: that slug is only allocated when the move happens.
            self.folder_label.setText(workspace.slug)
            cards, searches = workspace_counts(workspace)
            self.summary_label.setText(f"{cards} cards, {searches} searches")
            self._loaded_name = workspace.name
        self._loading = False
        self.update_buttons()

    def on_edited(self):
        """A field changed. Mark dirty and re-check whether Open is possible."""
        if self._loading:
            return
        self._dirty = True
        self.update_buttons()

    def _typed_name(self) -> str:
        """The name currently in the field, as it would be saved."""
        return self.name_input.text().strip()

    def _name_taken(self, name: str, excluding_slug: str | None = None) -> bool:
        """Whether another workspace already uses this display name.

        Compared case insensitively and ignoring surrounding space, because
        "Lalka" and " lalka " are the same name to a reader, and two rows that
        read alike cannot be told apart in the list.
        """
        wanted = name.strip().casefold()
        if not wanted:
            return False
        return any(
            workspace.name.strip().casefold() == wanted
            and workspace.slug != excluding_slug
            for workspace in self._workspaces
        )

    def _name_conflict(self) -> bool:
        """Whether the name being typed would duplicate another workspace's.

        Only a name the user is actually changing counts. A workspace that
        already shares its name with another, from before this rule or from a
        hand-edited config file, still opens: refusing it would strand the user
        with two workspaces neither of which can be opened.
        """
        if self._selected is None:
            return False
        typed = self._typed_name()
        if typed.casefold() == self._selected.name.strip().casefold():
            return False
        return self._name_taken(typed, excluding_slug=self._selected.slug)

    def form_workspace(self) -> Workspace | None:
        """The selected workspace with the form's current values applied."""
        if self._selected is None:
            return None
        return Workspace(
            slug=self._selected.slug,
            # A blank name would give a nameless row, so the slug stands in. A
            # name that collides with another workspace is not applied either:
            # Save and Open are both disabled while it does, rather than letting
            # two rows that read alike be written.
            name=(
                self._selected.name
                if self._name_conflict()
                else self._typed_name() or self._selected.slug
            ),
            dir=self._selected.dir,
            original_path=self.original_input.text().strip(),
            translation_path=self.translation_input.text().strip(),
        )

    def update_buttons(self):
        """Open needs both books; Delete refuses to empty the list."""
        workspace = self.form_workspace()
        conflict = self._name_conflict()
        openable = workspace is not None and can_open(workspace) and not conflict
        self.open_button.setEnabled(openable)
        self.save_button.setEnabled(
            self._dirty and self._selected is not None and not conflict
        )
        self.duplicate_button.setEnabled(self._selected is not None)
        self.delete_button.setEnabled(self.can_delete())
        if conflict:
            self.problem_label.setText(
                "Another workspace is already called that. Choose a different name."
            )
        elif workspace is None or openable:
            # No books at all is a workspace waiting for them, not a problem:
            # it opens with a placeholder where the book view would be.
            self.problem_label.setText("")
        elif not workspace.original_path or not workspace.translation_path:
            self.problem_label.setText(
                "Set both book paths, or clear both to open without books."
            )
        else:
            self.problem_label.setText("A book file is missing. Fix the path above.")

    def browse(self, field: QLineEdit, title: str):
        """Pick a book file into one of the two path fields."""
        path, _ = QFileDialog.getOpenFileName(
            self, title, field.text(), "Books (*.epub *.pdf);;All files (*)"
        )
        if path:
            field.setText(path)

    def save_selected(self) -> bool:
        """Write the form back into the selected workspace's config.json.

        The Save button, and the Save answer to the unsaved-edits prompt. Every
        path that writes edits goes through here, so this is also where a name
        change moves the folder: doing that in accept() instead would leave a
        workspace renamed from the list with a folder name that no longer
        matches, and no way to catch up short of renaming it a second time.

        Returns whether the workspace now matches the form, so a caller on its
        way elsewhere knows whether it may carry on. Nothing to write counts as
        success; a name another workspace already uses does not, and is refused
        here as well as on the button, so the prompt's Save cannot slip one
        through.
        """
        if self._selected is None or not self._dirty:
            return True
        if self._name_conflict():
            self._reject_taken_name(self._typed_name())
            return False
        index = self._workspaces.index(self._selected)
        workspace = self.form_workspace()
        save_workspace(workspace)
        workspace = self.apply_rename(workspace)
        self._workspaces[index] = workspace
        self._selected = workspace
        self._loaded_name = workspace.name
        self._dirty = False
        item = self.list_widget.item(index)
        if item is not None:
            item.setText(self.label_for(workspace))
        self.update_buttons()
        return True

    def _ask_leaving(self, name: str):
        """Ask what to do with unsaved edits. Split out so tests can drive it."""
        return QMessageBox.question(
            self,
            "Unsaved changes",
            f"'{name}' has unsaved changes.\n\nSave them before leaving?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

    def leave_selected(self) -> bool:
        """Settle unsaved edits before the form stops showing this workspace.

        Returns False when the user cancelled, or when saving was refused, in
        which case the caller must stay where it is. Named for what it guards
        rather than what it asks, because the common case asks nothing: with no
        edits pending there is no prompt.
        """
        if self._selected is None or not self._dirty:
            return True
        answer = self._ask_leaving(self._loaded_name)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_selected()
        if answer == QMessageBox.StandardButton.Discard:
            # Repopulating from the workspace as it stands drops the edits and
            # clears the dirty flag, so nothing is carried to the next row.
            self.show_workspace(self._selected)
            return True
        return False

    def _restore_row(self):
        """Put the list selection back on the workspace the form is showing.

        The list has already moved by the time currentRowChanged reaches us, so
        cancelling means moving it back. Guarded, or this would re-enter
        on_row_changed and ask about the same edits again.
        """
        if self._selected is None:
            return
        self._loading = True
        self.list_widget.setCurrentRow(self._workspaces.index(self._selected))
        self._loading = False

    def apply_rename(self, workspace: Workspace) -> Workspace:
        """Move a just-saved workspace's folder to match its new name.

        Returns the workspace as it now stands on disk, so the list and the
        selection never drift from it. A move is only ever considered when the
        name changed in this dialog, so merely opening a workspace whose slug no
        longer matches its name (an old collision suffix) never moves it.
        """
        if workspace.name == self._loaded_name:
            return workspace
        desired = slugify(workspace.name, taken_slugs() - {workspace.slug})
        if desired == workspace.slug:
            # The slug already matches, so nothing moves. Drop any deferred move
            # recorded earlier in this dialog: a name edited away and then back
            # again would otherwise still move the folder to the abandoned name.
            if workspace.slug == self.current_slug:
                self.rename = None
            return workspace
        if workspace.slug == self.current_slug:
            # Deferred: this workspace's stores still hold paths into the
            # folder, so the move waits for closeEvent to flush them. The folder
            # has not moved, so the slug and dir here stay as they are.
            self.rename = (workspace.slug, desired)
            return workspace
        try:
            rename_workspace_folder(workspace.slug, desired)
        except OSError as exc:
            # The new name is already in config.json and the workspace still
            # loads from its old folder, so the failure is reported and the work
            # carries on. Rolling back would need a second move that can fail
            # the same way.
            QMessageBox.warning(
                self,
                "Could not rename the workspace folder",
                f"'{workspace.name}' is saved, but its folder is still named "
                f"'{workspace.slug}':\n\n{exc}\n\n"
                "The workspace still opens normally.",
            )
            return workspace
        return replace(
            workspace, slug=desired, dir=workspace.dir.parent / desired
        )

    def _ask_name(self, title: str, default: str = "") -> str | None:
        """Prompt for a workspace name. Split out so tests can drive it."""
        name, ok = QInputDialog.getText(self, title, "Name:", text=default)
        name = name.strip()
        return name if ok and name else None

    def _confirm_delete(self, workspace: Workspace) -> bool:
        """Confirm destroying a workspace, naming what is being destroyed."""
        cards, searches = workspace_counts(workspace)
        answer = QMessageBox.question(
            self,
            "Delete workspace",
            f"Delete '{workspace.name}' and everything in it?\n\n"
            f"{cards} cards and {searches} searches will be lost. "
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _reject_taken_name(self, name: str) -> bool:
        """Warn and refuse when a new workspace would reuse an existing name.

        Two workspaces reading alike in the list cannot be told apart, so the
        name is refused at the point it would be created rather than allowed and
        disambiguated afterwards.
        """
        if not self._name_taken(name):
            return False
        QMessageBox.warning(
            self,
            "Name already used",
            f"Another workspace is already called '{name}'.\n\n"
            "Choose a different name.",
        )
        return True

    def new_workspace(self):
        """Create an empty workspace and select it."""
        name = self._ask_name("New workspace")
        if name is None:
            return
        if self._reject_taken_name(name):
            return
        if not self.leave_selected():
            return
        created = create_workspace(name)
        self.reload(select=created.slug)

    def duplicate_selected(self):
        """Copy the selected workspace, deck, history, anchors and all."""
        if self._selected is None:
            return
        if not self.leave_selected():
            return
        name = self._ask_name(
            "Duplicate workspace", f"{self._selected.name} copy"
        )
        if name is None:
            return
        if self._reject_taken_name(name):
            return
        copy = duplicate_workspace(self._selected.slug, name)
        self.reload(select=copy.slug)

    def can_delete(self) -> bool:
        """Whether the selected workspace may be deleted.

        Two refusals. The last remaining workspace, so there is always one to
        fall back to, and the workspace that is currently open: its history,
        flashcard and anchor stores hold absolute paths into that folder and
        recreate it on their next write, so removing it would lose the deck the
        user asked to keep and leave behind a folder with no config.json that
        the picker can never show again.
        """
        return (
            self._selected is not None
            and len(self._workspaces) > 1
            and self._selected.slug != self.current_slug
        )

    def delete_selected(self):
        """Delete the selected workspace after confirmation."""
        # Guarded here as well as on the button, so the rule holds even when
        # this is called directly.
        if not self.can_delete():
            return
        workspace = self._selected
        if not self._confirm_delete(workspace):
            return
        # Nothing to write back for a workspace about to be destroyed.
        self._dirty = False
        delete_workspace(workspace.slug)
        self.reload(select=self.current_slug)

    def accept(self):
        """Settle pending edits and report the slug to open.

        The folder move itself belongs to save_selected(); all this adds is that
        the deferred move of the open workspace has already allocated the slug
        that folder is about to take, so that is the slug to open.
        """
        if not self.leave_selected():
            return
        workspace = self._selected
        if workspace is None:
            return
        if self.rename is not None and self.rename[0] == workspace.slug:
            self.chosen = self.rename[1]
        else:
            self.chosen = workspace.slug
        super().accept()

    def reject(self):
        """Cancel, offering to keep unsaved edits."""
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Discard changes",
                "Discard the unsaved changes to this workspace?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().reject()
