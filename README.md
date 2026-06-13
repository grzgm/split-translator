# Split Translator

A PyQt5 desktop app for reading a book and its translation side by side. The original and translated versions are shown in synced tabs, with page numbers mapped between the two editions through interpolated anchor points. It includes full-text search within the PDFs, a dictionary lookup panel with "meaning" and "po polsku" tabs for selected words, and a saved search history.

## Setup

```
pip install pymupdf PyQt5 PyQtWebEngine
cp config.sample.json config.json
```

Edit *config.json* with your book paths and page anchors, then run `python translation_tool.py`.
