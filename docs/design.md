# Design

How Bookwork is built. Why it's built this way is [decisions.md](decisions.md);
what it replaces is [background.md](background.md).

## Terms

- **Signature** — leaves folded together as one section. Counted in **pages,
  not sheets** (matching `psbook`); must be 0 or a multiple of 4.
- **Sheet side** — one face of a sheet, holding two pages.
- **Recto / verso** — front and back of a leaf.
- **Gutter** — extra inner margin next to the spine, to survive binding.

## Stack

Python 3.12+, [PyMuPDF](https://pymupdf.readthedocs.io/) for PDF work,
PySide6 (Qt) for the GUI, PyInstaller for packaging.

PyMuPDF does rendering *and* page composition, so it replaces the entire
Ghostscript/psutils chain with testable Python. Qt's `QPrinter` abstracts CUPS
and the Windows spooler with no per-platform branching.

## Modules

```
src/bookwork/
  app.py              entry point
  main_window.py      tabs, menus, wiring
  pdf_document.py     PyMuPDF wrapper
  imposition.py       signature order, 2-up placement, crop marks, stats
  printing.py         renders onto a QPrinter
  presets.py          named settings via QSettings
  widgets/
    pdf_viewer_pane.py   thumbnails + page display, reused per tab
    page_view.py         flat page display
    page_turn_view.py    animated page turn, Bound Preview only
    thumbnail_list.py    thumbnails; editable on Source
    imposition_panel.py  settings form, presets, stats
```

`imposition.py` is pure page math with no Qt dependency, which is why it
carries the densest tests. Widgets know nothing about imposition beyond the
`ImpositionParams` they emit.

## Pipeline

```
source.pdf
   │  in-memory fitz document; the file on disk is never written to.
   │  Page edits here re-run everything below.
   ▼
_SignatureLayout.resolve()
   │  turns params + page count into concrete arguments — one place, so the
   │  imposed sheets and the Bound Preview cannot disagree.
   ▼
compute_signature_order()
   │  psbook's algorithm. Chunk lengths from _chunk_sizes(), each chunk
   │  reordered by _signature_block_order().
   ▼
_build_sheets()
   │  two pages per sheet side via show_pdf_page(keep_proportion=True).
   │  Margin on all edges; gutter is an extra inset on the spine side.
   │  Crop marks go at the *fitted* content rect, not the nominal cell.
   ▼
   ├─▶ Imposed tab          the sheets as they print
   ├─▶ Bound Preview tab    the same sheets cropped back into reading order
   └─▶ printing.py          shrunk to the printable area, centred on the paper
```

Bound Preview crops from the imposed sheets rather than re-rendering the
source, so it shows real output — margin shift, gutter, crop marks and padding
blanks included — instead of an idealised version that could agree with you
while the print disagrees.

## Parameters

`ImpositionParams`, all distances in points (1/72"):

| Parameter | Default | |
|---|---|---|
| `signature_size_pages` | 20 | Pages, not sheets. 0 = one signature; else a multiple of 4 |
| `sheet_width_pt` / `_height_pt` | 792 × 612 | Letter landscape — two 5.5×8.5" halves |
| `margin_pt` | 18 | All four edges of each cell |
| `gutter_pt` | 18 | *Additional* inset on the spine side only |
| `show_crop_marks` | True | Outward L-ticks at the placed page's corners |
| `include_endpapers` | False | Blank leading/trailing page for a hardcover case |
| `separate_cover` | False | First/last page as a wrap folio. Excludes endpapers |
| `pad_last_signature_to_full` | False | Off = pad only to a multiple of 4 |

There's no scale percentage — `keep_proportion=True` fits each page to its
cell, so scale falls out of the margin and gutter.

## Testing

`uv run pytest` (`QT_QPA_PLATFORM=offscreen` with no display).

- Page math is checked against known-good `psbook` output.
- Page-turn geometry lives in module-level pure functions, so most of it needs
  no window and no running animation.
- An autouse fixture forces animations to zero duration; without it tests race
  the animation and can tear a widget down mid-flight.
- Printing is tested by pointing a `QPrinter` at a PDF file.

**Check your fix's test fails without the fix.** Two bugs here were covered by
tests that passed either way — see [decisions.md](decisions.md).
