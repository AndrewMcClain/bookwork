# Bookwork

A cross-platform (Windows/macOS/Linux) desktop tool for
[imposing](https://en.wikipedia.org/wiki/Imposition) a PDF for booklet/signature
printing: view a PDF, reorder and arrange pages 2-up per sheet, and produce a
print-ready file. See [DESIGN.md](DESIGN.md) for the project's design doc and roadmap.

**Status:** early development — milestone v1 (native imposition pipeline,
Source/Imposed/Bound Preview viewer tabs, layout stats, crop marks) done.

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
  app.py              # QApplication entry point
  main_window.py      # main window: menu, Source/Imposed/Bound Preview tabs
  pdf_document.py     # PyMuPDF wrapper (all `pymupdf` usage lives here)
  imposition.py       # signature order, 2-up placement, crop marks, bound
                       # preview, layout stats (no shell tools)
  widgets/
    pdf_viewer_pane.py    # thumbnail sidebar + page view, reused per tab
    page_view.py          # single-page display, scaled to fit
    thumbnail_list.py     # page thumbnail sidebar
    imposition_panel.py   # signature/sheet/margin/gutter form + layout stats
tests/
```

The **Bound Preview** tab reconstructs the book's actual reading order
(page 1, 2, 3, ...) by cropping each page back out of the already-imposed
sheets, so a pagination mistake shows up visually in the order you'd actually
read it, rather than requiring you to mentally fold/unfold the Imposed tab's
sheet order.

## Known follow-ups

- The thumbnail sidebar (`widgets/thumbnail_list.py`) has some extra blank
  space in its layout that needs a pass — cosmetic, not functional.
