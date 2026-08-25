# Bookwork

A cross-platform (Windows/macOS/Linux) desktop tool for
[imposing](https://en.wikipedia.org/wiki/Imposition) a PDF for booklet/signature
printing: view a PDF, reorder and arrange pages 2-up per sheet, and produce a
print-ready file. See [DESIGN.md](DESIGN.md) for the project's design doc and roadmap.

**Status:** early development — milestone v0 (core app shell + PDF viewer).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management

## Setup

```bash
uv sync
```

## Run

```bash
uv run bookwork [path/to/file.pdf]
```

The PDF path argument is optional; you can also use File → Open in the app.

## Test

```bash
uv run pytest
```

On a Linux machine with no display attached (e.g. CI, SSH session), set
`QT_QPA_PLATFORM=offscreen` first.

## Project layout

```
src/bookwork/
  app.py            # QApplication entry point
  main_window.py    # main window: menu, thumbnail sidebar, page view
  pdf_document.py   # PyMuPDF wrapper (all `pymupdf` usage lives here)
  widgets/
    page_view.py       # single-page display
    thumbnail_list.py  # page thumbnail sidebar
tests/
```
