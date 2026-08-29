# Split Translator

A PySide6 desktop app for reading a book and its translation side by side. The original and translated versions are shown in synced tabs, with page numbers mapped between the two editions through interpolated anchor points. It includes full-text search within the PDFs, a dictionary lookup panel with "meaning" and "po polsku" tabs for selected words, and a saved search history.

## Setup

```
pip install -r requirements.txt
```

On first launch the app opens the workspace picker, because there are no
workspaces yet. Create one, give it a name, and point it at the original book
and its translation. Everything that workspace collects (its search history,
flashcard deck and content anchors) is stored in its own folder, so a second
workspace for a different book starts empty.

Switch workspace, or change a workspace's book paths, from *View* then
*Workspaces...*.

Then run the app with either:

```
python translation_tool.py
python -m split_translator
```

## Project layout

The app is split into a package for easier maintenance:

| Module | Responsibility |
| --- | --- |
| [split_translator/app.py](split_translator/app.py) | Bootstrap: Qt setup, web profile, runs the window |
| [split_translator/config.py](split_translator/config.py) | Loads one workspace's *config.json* (name, book paths) |
| [split_translator/workspace.py](split_translator/workspace.py) | Finds, creates, renames and deletes workspaces |
| [split_translator/workspace_dialog.py](split_translator/workspace_dialog.py) | The workspace picker dialog |
| [split_translator/page_mapper.py](split_translator/page_mapper.py) | Maps page numbers between editions via interpolated anchors |
| [split_translator/pdf_viewer.py](split_translator/pdf_viewer.py) | Single-PDF viewer with lazy rendering and search worker |
| [split_translator/pdf_panel.py](split_translator/pdf_panel.py) | Tabbed original/translation viewer with synced scrolling |
| [split_translator/web.py](split_translator/web.py) | Persistent web profile, ad-block interceptor, page scripts |
| [split_translator/dictionary_panel.py](split_translator/dictionary_panel.py) | Search bar and dictionary/translation web views |
| [split_translator/history.py](split_translator/history.py) | Persistent search-history sidebar |
| [split_translator/main_window.py](split_translator/main_window.py) | Wires the panels together and owns shortcuts |

## Browsing behaviour

The dictionary views use a single persistent [QWebEngineProfile](split_translator/web.py) stored under the OS app-data directory (on Linux: `~/.local/share/split-translator/web-profile/`). Because cookies, cache and Cloudflare clearance are kept on disk, cookie banners and bot checks do not reappear on every launch. Ad/tracker requests are blocked at the network layer, and a small injected script removes leftover ad slots and auto-dismisses common cookie-consent dialogs.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+L` / `F6` | Focus the search box |
| `F3` / `Ctrl+F` | Next PDF match (or focus search if not focused) |
| `Shift+F3` | Previous PDF match |
| `Alt+1` ... `Alt+9` | Play the matching Cambridge audio clip |
