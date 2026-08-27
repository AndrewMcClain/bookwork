# Bookwork

Impose a PDF for booklet printing: reorder pages into signatures, lay them out
two-up with margins and a binding gutter, check the result as a bound book, and
print it duplex. Cut, fold, bind — and the pages read in order.

A cross-platform desktop replacement for the `pdf2ps | psbook | psnup | lp`
chain, which worked but was Linux-only and gave you no way to catch an
off-by-one before it cost a print run.

**Status:** used for real printing on Linux. Windows and macOS builds are
written but have never been run — see [Known gaps](#known-gaps).

## Run it

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run bookwork [file.pdf]
```

```bash
uv run pytest        # QT_QPA_PLATFORM=offscreen if there's no display
```

## What it does

Three tabs, in the order you work:

- **Source** — the document. Right-click a thumbnail to insert or delete pages,
  with undo/redo. Edits are in memory; your file is never written to.
- **Imposed** — the actual sheets, plus settings: signature size, paper size
  (Letter/Legal/A3–A5/B5, or type your own), margin, gutter, crop marks,
  endpapers, wrap cover, and whether to pad the last signature. Named presets
  persist across runs.
- **Bound Preview** — those same sheets recomposed into what a reader sees.
  Click, arrow-key or drag to turn pages; the leaf carries the right page on
  its front and the next left page on its back, exactly as one sheet does.
  Edge stacks show how thick the finished block will be.

Every edit regenerates the other two tabs immediately. Bound Preview is where
you catch an off-by-one, because it shows the book as you'll hold it.

## Printing

File → Print Imposed (Ctrl+P). Pre-sized to the sheet, short-edge duplex.

**Pages come out slightly smaller than nominal** — around 95% on a typical
laser printer. Printers can't image to the paper edge, and the crop marks live
there, so each sheet is shrunk until they fit and centred on the paper. Marks
scale too, so pages stay consistent within a run. The scale depends on the
printer, so print a whole book on one machine.

## Docs

| | |
|---|---|
| [docs/design.md](docs/design.md) | How it's built |
| [docs/decisions.md](docs/decisions.md) | Why it's built that way, and the bugs behind it |
| [docs/background.md](docs/background.md) | The manual process this replaces |
| [docs/third-party.md](docs/third-party.md) | Dependency licences |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, tests, commit format, AI policy |
| [packaging/README.md](packaging/README.md) | Building a standalone app |

Read [decisions.md](docs/decisions.md) before changing anything — several
deliberate choices look like bugs until you know why.

## Known gaps

- **Windows and macOS builds are unverified.** The spec should be correct;
  nobody has run it. CI on hosted runners is the intended fix.
- No app icon, code signing, or notarization.
- Paper thickness is hardcoded at 0.1mm for the preview's edge stacks.
- The thumbnail sidebar has stray blank space — cosmetic.

## License

GPL v3-or-later ([COPYING](COPYING)).

**PyMuPDF, which every build depends on, is AGPL v3** — compatible, but it
carries the AGPL network clause into anything you redistribute. See
[docs/third-party.md](docs/third-party.md).
