# Bookwork

A cross-platform desktop tool for [imposing](https://en.wikipedia.org/wiki/Imposition)
a PDF for booklet and signature printing: reorder pages into signatures, arrange them
two-up per sheet with margins and a binding gutter, check the result as a bound book,
and print it duplex — so that after cutting, folding and binding, the pages read in
order.

It exists to replace a hand-run chain of Linux-only PostScript commands
(`pdf2ps | psbook | psnup | lp`) that worked but was fiddly, unportable, and gave you
no way to spot an off-by-one before it cost you a print run. See
[docs/background.md](docs/background.md).

**Status:** works and is used for real printing on Linux. Windows and macOS builds are
written but unverified — see [Known gaps](#known-gaps).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup and run

```bash
uv sync
```

```bash
uv run bookwork [path/to/file.pdf]
```

The path is optional; File → Open works too.

## Tests

```bash
uv run pytest
```

On a machine with no display attached (CI, an SSH session), prefix with
`QT_QPA_PLATFORM=offscreen`.

## How you use it

Three tabs, left to right, matching the order you work in.

### Source

The document as loaded. Right-click a thumbnail to insert a blank page before or
after it, or delete any page — a bad scan, a duplicate, a miscount. Undo/redo
(Ctrl+Z / Ctrl+Shift+Z) covers all of it, and edits are in-memory only: the file
on disk is never written to.

Every edit immediately regenerates the other two tabs, so you see what it does to
signature layout straight away.

### Imposed

The actual sheets, as they will print, with the settings panel beside them.

- **Signature size** — pages per signature, not sheets. `0` puts the whole
  document in one signature; otherwise a multiple of 4.
- **Sheet size, margin, gutter** — the gutter is an *extra* inset on each page's
  spine-adjacent edge, on top of the margin, to survive binding.
- **Show crop marks** — an L-shaped tick at each corner of the placed page,
  pointing outward so cutting along them leaves no ink on the finished page.
- **Add blank endpapers** — one real blank page front and back, for gluing into a
  hardcover case.
- **Separate wrap cover** — first and last page become a single folded folio
  wrapping the interior signatures, for a booklet with heavier cover stock.
  Mutually exclusive with endpapers.
- **Pad last signature to full size** — off by default, so a leftover partial
  signature is padded only to the next multiple of 4. A 4-page document at a
  20-page signature size then prints on 1 sheet instead of 5. Switch it on for
  uniform signatures, matching `psbook`.

Below the form, layout stats spell out what you are about to print, e.g.
"20 pages/signature, 2 full signatures + 1 signature of 4 pages".

**Presets** save the whole settings set under a name, persisted in the OS's own
settings store and shared across documents. Picking one applies it immediately.

### Bound Preview

The same imposed sheets, recomposed into what a reader actually sees: covers
alone, two-page spreads in between. This is the best place to catch an off-by-one
or a swapped signature, because it shows the book as you will hold it rather than
asking you to mentally fold the Imposed tab's sheets.

Moving between adjacent spreads animates a **page turn** — a leaf rotates about
the spine carrying the page you are leaving on its front and the page you are
arriving at on its back, exactly as one sheet of paper does. That pairing is the
point: a leaf whose two sides do not belong together is immediately wrong to look
at.

Turn pages by **clicking** the page you want to turn (left goes back, right goes
forward), with the **arrow keys**, or by **dragging a page across** — the leaf
follows your pointer, and letting go past halfway completes the turn while
letting go short of it puts the page back.

The leaf bows as it goes over and shades along the curl, and the pages either
side are drawn as **edge stacks** at the real thickness of that many sheets of
paper, so you can see roughly how thick the finished text block will be and how
far into it you are. Paper is assumed to be 0.1mm (about 80gsm bond).

## Printing

File → Print Imposed (Ctrl+P) opens the system print dialog, pre-sized to the
imposed sheet and set to short-edge duplex. It always prints the Imposed tab's
output regardless of which tab is showing.

Most printers — laser especially — have a hardware margin they cannot image
into. Bookwork shrinks each sheet just enough to fit what the printer can
actually put ink on, and centres it on the paper so the spine lands on the
paper's centreline and folds come out straight.

That keeps the crop marks — which is the point, since they are what you fold
and cut along. The trade is that the finished page ends up slightly smaller
than the nominal trim size (about 95% on a typical laser printer). The marks
scale with everything else, so cutting on them still gives you consistent
pages; just be aware the scale can differ between printers, so print a whole
book on one.

## Project layout

```
src/bookwork/
  app.py              QApplication entry point
  main_window.py      tabs, menus, and the wiring between them
  pdf_document.py     PyMuPDF wrapper
  imposition.py       signature order, 2-up placement, crop marks, stats
  printing.py         renders an imposed document onto a QPrinter
  presets.py          named settings, via QSettings
  widgets/            viewer pane, page views, thumbnails, settings form
docs/                 design, decisions, background
packaging/            PyInstaller spec and Linux .deb build
tests/
```

[docs/](docs/) is worth reading before changing anything —
[decisions.md](docs/decisions.md) in particular records choices that are not
obvious from the code, and the bugs that motivated them.

## Packaging

See [packaging/README.md](packaging/README.md). A Linux `.deb` builds and is
smoke-tested; the PyInstaller spec is written to be correct on Windows and macOS
but has not been run there.

## Known gaps

- **Windows and macOS builds are unverified.** The spec is cross-platform but has
  only ever been built and run on Linux. CI on hosted runners is the intended fix
  and is not set up yet.
- **No app icon**, and no code signing or notarization — needed before
  distributing to anyone else on Windows (SmartScreen) or macOS (Gatekeeper).
- **Paper thickness is a constant**, not a setting, so the Bound Preview's edge
  stacks assume 0.1mm stock.
- The thumbnail sidebar has some extra blank space in its layout — cosmetic.

## License

GPL v3 — see [COPYING](COPYING).

Development dependencies (`pytest`, `pytest-qt`, `pyinstaller`) are permissively
licensed and are not included in distributed binaries.
