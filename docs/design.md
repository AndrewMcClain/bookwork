# Design

How Bookwork is put together and why. For the manual PostScript workflow this
replaces, see [background.md](background.md). For specific choices and the bugs
that motivated them, see [decisions.md](decisions.md).

## What it does

Takes a normal 1-up PDF and produces a print-ready **imposed** PDF: pages
reordered into signatures and placed two-up per sheet side, so that after duplex
printing, cutting, folding and binding, the pages read in order.

The guiding principle throughout: **the app never silently fixes pagination on
your behalf.** It shows you what it is doing and lets you correct it. Blank
padding pages are visibly blank in the output rather than quietly dropped,
because a pagination problem you can see costs nothing and one you cannot costs
a print run.

## Terminology

- **Leaf / sheet** — one physical piece of paper, printed both sides.
- **Signature** — a stack of leaves folded together as one section of the book.
  Counted in **pages, not sheets** (matching `psbook`'s own `-s` unit); must be
  0 or a multiple of 4.
- **Sheet side** — one face of a sheet, holding two logical pages side by side.
- **Recto / verso** — the front and back of a leaf; right- and left-hand pages
  of a spread.
- **Gutter** — extra inner margin next to the spine, to survive binding.
- **Logical vs. imposed order** — reading order (1, 2, 3…) vs. the physical
  layout order that produces it after folding.

## Stack

| Piece | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | The hard part is page math, not performance. Easy to unit-test away from the GUI. |
| PDF engine | PyMuPDF (`fitz`) | Prebuilt wheels on all three OSes, no compiler needed. Does rendering *and* page composition, so it replaces the whole Ghostscript/psutils chain with debuggable Python. |
| GUI | PySide6 (Qt) | One codebase, native behaviour everywhere. `QPrinter` abstracts CUPS vs. the Windows spooler with no per-platform branching. |
| Packaging | PyInstaller | Native bundle per platform from one spec. See [`packaging/`](../packaging/). |

Dropping the PostScript round trip was deliberate: `psutils` is a Linux-packaged
Perl toolset with no good Windows story, and the Ghostscript round trip risked
mangling fonts and embedded content. Alternatives set aside: Tauri + Rust PDF
crates (less mature for manipulation), Electron + `pdf-lib` (heavy, and cannot
render pages without bolting on PDF.js).

## Module map

```
src/bookwork/
  app.py              QApplication entry point
  main_window.py      tabs, menus, and the wiring between them
  pdf_document.py     the only place `pymupdf` is imported outside imposition
  imposition.py       signature order, 2-up placement, crop marks, stats
  printing.py         renders an imposed document onto a QPrinter
  presets.py          named ImpositionParams, persisted via QSettings
  widgets/
    pdf_viewer_pane.py   thumbnail strip + page display, reused per tab
    page_view.py         flat single-page display, scaled to fit
    page_turn_view.py    animated page turn, Bound Preview only
    thumbnail_list.py    page thumbnails; editable on the Source tab
    imposition_panel.py  settings form, presets, layout stats
```

`imposition.py` is pure page math against `fitz` documents with no Qt
dependency, which is why it carries the densest test coverage. The widgets know
nothing about imposition beyond the `ImpositionParams` they emit.

## Pipeline

```
source.pdf
   │  opened as an in-memory fitz document. The file on disk is never
   │  written to. The user can insert or delete pages here, with undo/redo,
   │  and every edit immediately re-runs everything below.
   ▼
reading-order pages
   │  _SignatureLayout.resolve() turns ImpositionParams + a page count into
   │  the concrete arguments the order functions need — one place, so the
   │  imposed sheets and the Bound Preview cannot disagree.
   ▼
signature order
   │  compute_signature_order() ports psbook's algorithm. Chunk lengths come
   │  from _chunk_sizes(); each chunk is reordered by _signature_block_order().
   ▼
imposed sheets
   │  _build_sheets() places two pages per sheet side via show_pdf_page with
   │  keep_proportion=True. Margin applies to all four edges; the gutter is an
   │  extra inset on whichever edge faces the spine. Crop marks are drawn at
   │  the *fitted* content rect, not the nominal cell.
   ▼
   ├──▶ Imposed tab — the sheets as they will print
   ├──▶ Bound Preview tab — the same sheets recomposed into reading order
   └──▶ printing.py — QPrinter, sized and duplexed to the sheet, shrunk
        to the real printable area and centred on the paper
```

## The three tabs

**Source** shows the working document. It is the only editable one: right-click
a thumbnail to insert or delete pages, with undo/redo over whole-document byte
snapshots.

**Imposed** shows the sheets exactly as they will print, alongside the settings
form and layout stats.

**Bound Preview** recomposes those sheets back into what a reader would see:
cover pages alone, two-page spreads in between, with a page-turn animation
between adjacent views. It exists because "is this off by one?" is a question
about the *bound book*, and the Imposed tab requires mentally folding sheets to
answer it. Crucially it crops from the already-imposed sheets rather than
re-rendering the source, so it shows real imposition output — margin shift,
gutter and crop marks included — not an idealised version that could agree with
you while the print disagrees.

## Parameters

All distances in PDF points (1/72"). Defaults in `ImpositionParams`:

| Parameter | Default | Notes |
|---|---|---|
| `signature_size_pages` | 20 | Pages, not sheets. 0 = one signature for the whole document; otherwise a multiple of 4. |
| `sheet_width_pt` / `sheet_height_pt` | 792 × 612 | Letter, landscape — two 5.5×8.5" halves side by side. |
| `margin_pt` | 18 | Quarter inch on all four edges of each cell. |
| `gutter_pt` | 18 | *Additional* inset on the spine-adjacent edge only. |
| `show_crop_marks` | True | Outward L-ticks at each corner of the placed page. |
| `include_endpapers` | False | Blank leading and trailing page for gluing into a hardcover case. |
| `separate_cover` | False | First/last page become a single-folio wrap cover. Mutually exclusive with endpapers. |
| `pad_last_signature_to_full` | False | Off = pad the last signature only to a multiple of 4. On = `psbook`'s uniform behaviour. |

There is no scale percentage. The manual process needed one because it shifted
pages after placing them; here `keep_proportion=True` fits each page into its
target rect, so the scale falls out of the margin and gutter.

## Testing

`uv run pytest` — set `QT_QPA_PLATFORM=offscreen` with no display attached.

- Page math is tested directly against known-good `psbook` output.
- Geometry for the page turn lives in module-level pure functions
  (`leaf_curve`, `book_layout`, `edge_stack_width`, `cast_shadow_strength`) so
  it can be exercised without a window or a running animation.
- Widget tests drive real Qt events. Animations are forced to zero duration by
  an autouse fixture, or tests race the animation and can tear a widget down
  mid-flight.
- Printing is tested by pointing a `QPrinter` at a PDF file, which exercises the
  same QPainter path a real job takes.

When fixing a bug here, check the fix actually fails the test without it. Two
bugs in this codebase were originally "covered" by tests that passed either way
— see [decisions.md](decisions.md).
