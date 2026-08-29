"""The workspace picker: choose which reading project to open, and edit the
selected one's name and book paths.

Like every panel in the app this widget knows nothing about the others. It talks
only to workspace.py, and the main window reads its result and acts on it.

It writes every config.json it changes itself. The one thing it cannot do is
move the folder of the workspace that is currently open, because that
workspace's stores hold absolute paths into it and their save workers may have a
write in flight. That move is handed back through `rename` for the caller to
perform once closeEvent has flushed them.
"""

import json

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
    both_books_resolve,
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
        form.addWidget(self.summary_label, 3, 1, 1, 2)
        form.addWidget(self.problem_label, 4, 1, 1, 2)
        form.setColumnStretch(1, 1)
        form.setRowStretch(5, 1)

        detail = QWidget()
        detail.setLayout(form)

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
            label = workspace.name
            if workspace.slug == self.current_slug:
                label = f"{label}   (open)"
            self.list_widget.addItem(label)
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

    def select_slug(self, slug: str):
        """Select a workspace by slug. Used by the tests and after New."""
        slugs = [workspace.slug for workspace in self._workspaces]
        if slug in slugs:
            self.list_widget.setCurrentRow(slugs.index(slug))

    def on_row_changed(self, row: int):
        """Flush the outgoing workspace's edits, then show the incoming one."""
        if self._loading:
            return
        self.flush()
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
            self.summary_label.setText(_NO_SELECTION)
            self._loaded_name = ""
        else:
            self.name_input.setText(workspace.name)
            self.original_input.setText(workspace.original_path)
            self.translation_input.setText(workspace.translation_path)
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

    def form_workspace(self) -> Workspace | None:
        """The selected workspace with the form's current values applied."""
        if self._selected is None:
            return None
        return Workspace(
            slug=self._selected.slug,
            # A blank name would give a nameless row, so the slug stands in.
            name=self.name_input.text().strip() or self._selected.slug,
            dir=self._selected.dir,
            original_path=self.original_input.text().strip(),
            translation_path=self.translation_input.text().strip(),
        )

    def update_buttons(self):
        """Open needs both books; Delete refuses to empty the list."""
        workspace = self.form_workspace()
        resolves = workspace is not None and both_books_resolve(workspace)
        self.open_button.setEnabled(resolves)
        self.duplicate_button.setEnabled(self._selected is not None)
        self.delete_button.setEnabled(
            self._selected is not None and len(self._workspaces) > 1
        )
        if workspace is None or resolves:
            self.problem_label.setText("")
        elif not workspace.original_path or not workspace.translation_path:
            self.problem_label.setText("Set both book paths to open this workspace.")
        else:
            self.problem_label.setText("A book file is missing. Fix the path above.")

    def browse(self, field: QLineEdit, title: str):
        """Pick a book file into one of the two path fields."""
        path, _ = QFileDialog.getOpenFileName(
            self, title, field.text(), "Books (*.epub *.pdf);;All files (*)"
        )
        if path:
            field.setText(path)

    def flush(self):
        """Write the form back into the selected workspace's config.json."""
        if self._selected is None or not self._dirty:
            return
        workspace = self.form_workspace()
        save_workspace(workspace)
        index = self._workspaces.index(self._selected)
        self._workspaces[index] = workspace
        self._selected = workspace
        self._dirty = False

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

    def new_workspace(self):
        """Create an empty workspace and select it."""
        name = self._ask_name("New workspace")
        if name is None:
            return
        self.flush()
        created = create_workspace(name)
        self.reload(select=created.slug)

    def duplicate_selected(self):
        """Copy the selected workspace, deck, history, anchors and all."""
        if self._selected is None:
            return
        self.flush()
        name = self._ask_name(
            "Duplicate workspace", f"{self._selected.name} copy"
        )
        if name is None:
            return
        copy = duplicate_workspace(self._selected.slug, name)
        self.reload(select=copy.slug)

    def delete_selected(self):
        """Delete the selected workspace after confirmation."""
        if self._selected is None or len(self._workspaces) <= 1:
            return
        workspace = self._selected
        if not self._confirm_delete(workspace):
            return
        # Nothing to write back for a workspace about to be destroyed.
        self._dirty = False
        delete_workspace(workspace.slug)
        select = self.current_slug if self.current_slug != workspace.slug else None
        self.reload(select=select)

    def accept(self):
        """Write pending edits, work out the folder move, and report the slug."""
        self.flush()
        workspace = self._selected
        if workspace is None:
            return
        slug = workspace.slug
        # A folder move is only considered when the name actually changed here.
        if workspace.name != self._loaded_name:
            desired = slugify(workspace.name, taken_slugs() - {workspace.slug})
            if desired != workspace.slug:
                if workspace.slug == self.current_slug:
                    # Deferred: this workspace's stores still hold paths into
                    # the folder, so the move waits for closeEvent to flush.
                    self.rename = (workspace.slug, desired)
                else:
                    rename_workspace_folder(workspace.slug, desired)
                slug = desired
        self.chosen = slug
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
