# Bookwork — Design Doc

Status: **draft / living document** — updated as decisions get made.
Last updated: 2026-08-25 — resequenced milestones (§7): GUI + source PDF view first

## 1. Vision

A **cross-platform (Windows, macOS, Linux) desktop tool** that takes a normal 1-up PDF
(e.g. a book or booklet manuscript) and produces a print-ready,
[imposed](https://en.wikipedia.org/wiki/Imposition) PDF: pages reordered and arranged
2-up per sheet in printer-ready signatures, so that after duplex printing,
cutting/folding, and binding, the pages come out in the correct reading order.

The app should let the user **view** the source PDF and the resulting imposed layout
(to catch page-order / rotation / margin mistakes before wasting paper), **interactively
insert or remove pages while viewing** (see §3.2 — the main tool for spotting and fixing
off-by-one/pagination issues before committing to imposition), and drive the imposition
process that today is done by hand with a chain of Linux-only shell commands.
The project started from a Linux-specific manual workflow (§8); the design has since
moved to a single cross-platform stack (§3) so the same app and codebase run unmodified
on all three OSes, rather than branching logic per platform.

## 2. Background

### 2.1 What imposition is doing here

The user's manual process is a standard **booklet / saddle-stitch-style signature
imposition** workflow using classic Unix PostScript tools:

1. **Convert PDF → PS** — `pdf2ps` (Ghostscript) turns the source PDF into PostScript,
   since `psutils` operates on PS, not PDF directly.
2. **Reorder pages into signature/booklet order** — `psbook -s20` groups pages into
   signatures of 20 sheets (i.e. up to 20 physical sheets = 80 pages per signature,
   `psbook`'s `-s` is in *sheets*, must be a multiple of 4) and reorders them so that
   when folded, the pages read in order.
3. **Impose 2-up** — `psnup -2 -m0 -b0 -P5.5inx8.5in -pletter` places two of the
   (already-reordered) logical pages onto each side of a Letter sheet, with no margin
   (`-m0`) and no border (`-b0`), targeting a 5.5"×8.5" final trim size (i.e. Letter cut
   in half).
4. **Print** — `lp -o sides=two-sided-short-edge` duplexes the sheets so that, once cut
   down the middle and gathered/folded, they form a booklet with correct pagination.

### 2.2 Known rough edges from the manual process (to solve in this project)

- **No margin/gutter handling** — pages are butted with zero margin, no room for a
  binding spine/gutter or for cutting tolerance.
- **Shifting content for the spine** — the user was experimenting with `pstops` to
  shift left/right pages apart from center to leave gutter room
  (`pstops "2:0(36pt,0pt),1(-36pt,0pt)"`), but wasn't sure of sign/direction.
- **Shrink + recenter + alternate offset** — a further `pstops` experiment
  (`"2:0@.97(18pt,9pt),1@.97(0pt,9pt)"`) to scale pages down ~3% and nudge them
  vertically, intended to run *between* `psbook` and `psnup` (i.e. operate on
  already-signature-ordered, still-1-up pages, before the 2-up imposition).
- **Off-by-one** — noted but not diagnosed; likely candidates: `psbook -s` sheet count
  not matching actual page count (padding/blank-page miscalculation), or confusion
  between operating on logical pages before vs. after `psnup`'s own reordering.
- **No border/trim marks** — nothing currently marks where to cut/fold, which matters
  once margins are introduced.
- **Border-fit printing** — `-o fit-to-page -o page-*=0` is a workaround at print time;
  ideally the generated file is already sized/margined correctly so no fit-to-page
  guessing is needed at the printer.

### 2.3 Terminology used throughout this doc

- **Leaf / sheet** — one physical piece of paper, printed on both sides.
- **Signature** — a stack of leaves folded together into one section of the book;
  saddle-stitch signatures are typically 4–24 pages (1–6 sheets) folded as a unit.
- **Logical page order vs. imposed order** — logical = normal reading order (1, 2, 3…);
  imposed = the physical layout order after `psbook`/`psnup` reordering so folding
  produces logical order.
- **1-up / 2-up** — one vs. two logical pages placed per physical sheet side.
- **Gutter** — the extra inner margin near the spine/fold to accommodate binding.

## 3. Interaction model & stack (decided)

- **Local, cross-platform GUI app** — same codebase runs on Windows, macOS, and Linux.
- Must include a **PDF viewer/preview**: at minimum to view the source PDF, and
  ideally to preview the imposed output (page layout, order, and margins) before
  sending to the printer — this is the main way to catch the "off by one" class of bug
  visually instead of by wasting a print.

### 3.1 Stack

| Piece | Choice | Why |
|---|---|---|
| Core language | **Python** | Fast iteration on the actual hard part of this project: signature-order and gutter/scale page math. Easy to unit-test in isolation from the GUI. |
| PDF engine | **PyMuPDF (`fitz`)** | Wraps MuPDF; prebuilt wheels for Windows/macOS/Linux (no compiler toolchain needed on any target). Does rendering *and* page composition (`Page.show_pdf_page` with a placement `Matrix`) in one library — this replaces the Ghostscript/`psbook`/`psnup`/`pstops` chain entirely with plain, debuggable, testable Python instead of a terse `pstops` DSL. |
| GUI toolkit | **PySide6 (Qt)** | Official Qt-for-Python bindings, LGPL-licensed. One codebase, native look/feel on all three OSes. Built-in `QPrinter` + print dialog abstracts away CUPS/`lp` (Linux-only) vs. Windows/macOS native print APIs. |
| Packaging | **PyInstaller** or **Briefcase** | Produces a native `.exe` / `.app` / Linux binary per platform from the same source. |

This stack deliberately **drops the PostScript round-trip** (`pdf2ps`/`psbook`/`psnup`/
`pstops`/`ps2pdf`) from §4's earlier PS-pipeline plan — `psutils` is a Linux-packaged
Perl toolset with no good story on Windows, and Ghostscript's PS round-trip risked
mangling fonts/embedded content anyway. PyMuPDF gives full, native control over page
placement/scale/rotation directly on the PDF object, on all three platforms, with one
dependency.

Alternatives considered and set aside: Tauri (Rust) + `mupdf-rs`/`pdfium-render` +
PDF.js frontend — smaller binaries and a more modern packaging story, but Rust's
PDF-manipulation crates are less mature than PyMuPDF and would slow down iteration on
the fiddly page-math. Electron + `pdf-lib` — heavy runtime, and `pdf-lib` doesn't
render pages itself (would need PDF.js bolted on separately just for viewing). Plain
GTK — weakest native support on Windows/macOS of the options considered.

### 3.2 Interactive page editing

The manual process's "off-by-one" bug is fundamentally a **pagination mismatch**: the
required blank/padding pages, or a missing/extra source page, only become obvious once
you can see pages laid out in signature order — by then you've already burned a sheet
of paper. So instead of only auto-padding blindly (old stage 1), the viewer must let
the user fix pagination *before* imposition runs, while looking at the document:

- **Insert a blank page** at a chosen position (e.g. right-click a page thumbnail →
  "insert blank before/after").
- **Delete a page** at a chosen position (e.g. an accidental scanned blank, or a
  duplicate).
- Both operations apply to an **in-memory working copy** of the source PDF (never
  mutate the original file on disk), and take effect immediately in the page
  thumbnail/preview strip, renumbering subsequent pages live.
- The page-count/multiple-of-4 padding step (§4 stage 1) becomes a **suggestion the
  user can review and adjust**, not a silent automatic action — e.g. the app proposes
  "2 blank pages needed at the end for a clean signature" and highlights where, but
  the user can move/reject/add to that before proceeding.
- Undo/redo for insert/delete, since this is exploratory ("did that fix the
  signature?") rather than one-shot.
- PyMuPDF supports this directly and cheaply: `Document.insert_page()` /
  `Document.delete_page()` operate on the in-memory `fitz.Document`, so the same
  object backs both the live preview and the eventual imposition input — no separate
  edit-then-reload step.

## 4. Processing pipeline (target design)

Reimplemented as explicit, testable PyMuPDF stages operating on the PDF directly (no
PostScript round-trip — see §3.1), with the known rough edges addressed:

```
[source.pdf]
   │  (1) open with fitz as the in-memory working document; user reviews/edits
   │      pages interactively (insert/delete blank pages — §3.2, milestone v2)
   │      to reach a page count that's a clean multiple of 4 (this is where the
   │      manual process's off-by-one lived — now a visible, in-viewer step
   │      instead of a silent automatic one)
   ▼
[padded, 1-up logical pages]
   │  (2) compute signature/booklet order (our own port of psbook's algorithm,
   │      parameterized by signature size in sheets)
   ▼
[signature-ordered, 1-up]
   │  (3) build output document: for each output sheet side, create a new page at
   │      the target sheet size and place two source pages onto it via
   │      Page.show_pdf_page(rect, src, pageno, matrix) — matrix encodes scale-down
   │      and the gutter/margin shift, applied per recto/verso (replaces the ad-hoc
   │      pstops experiments with real, debuggable transforms)
   ▼
[imposed, 2-up, ready to print]
   │  (4) optional: crop marks / fold marks drawn directly via fitz's drawing API
   ▼
[print-ready .pdf]
   │  (5) preview in-app (QPdfView or fitz-rendered pixmaps) and/or print via
   │      QPrinter, which maps to CUPS/lp on Linux/macOS and the native spooler
   │      on Windows without app-level branching
   ▼
[printer]
```

### 4.1 Fixing the specific rough edges

- **Off-by-one**: root-cause during implementation by writing an explicit page-count /
  signature-math step (stage 1) with unit tests, instead of trusting a black-box
  `-s` flag to silently pad correctly — compute and insert required blank pages
  ourselves, and unit-test the signature-order function directly against known-good
  page sequences.
- **Gutter/margin**: implement stage 3's placement matrix as small, explicit,
  unit-tested Python (translate + scale via `fitz.Matrix`) instead of a `pstops`
  DSL string, with the shift direction verified against a labeled test PDF (e.g. a
  PDF with big page numbers) rather than by trial and error.
- **Alternating offset**: must be keyed off recto/verso (odd/even *final imposed*
  sheet side, not original page number) — this is a likely source of the sign
  confusion in the notes; encode it as a named `is_verso` condition in code, not an
  implicit parity check.
- **No margin/border config today**: make margin, gutter, and scale-down percentage
  user-configurable parameters, not hardcoded.

## 5. Configurable parameters (draft)

| Parameter | Manual-process value | Notes |
|---|---|---|
| Sheet (paper) size | Letter | target physical sheet size, e.g. via a `fitz.paper_rect("letter")` helper |
| Trim (final page) size | 5.5in × 8.5in | Letter cut in half; drives each half's placement rect |
| Signature size | 20 sheets | our own signature-order function, parameterized; validate against page count |
| Margin | 0 | pages currently butted edge-to-edge; likely needs to become nonzero |
| Gutter shift | ~18–36pt, unresolved | needs a correct, tested value/formula, applied via the placement `Matrix` |
| Scale | ~97% | to keep content on-page after gutter shift; also via the placement `Matrix` |
| Duplex mode | two-sided-short-edge | mapped through `QPrinter`'s duplex setting, not raw `lp -o sides=` |
| Print range | e.g. `1,2,3...` | for partial/test prints, via `QPrinter`'s page-range support |

## 6. Open questions / decisions log

- [x] ~~GUI toolkit~~ — **decided: PySide6 (Qt)**. See §3.1.
- [x] ~~Language for the processing core~~ — **decided: Python**. See §3.1.
- [x] ~~PS pipeline vs. PDF-native pipeline~~ — **decided: PDF-native via PyMuPDF**,
  no PostScript round-trip. See §3.1 and §4.
- [ ] Exact gutter-shift formula/sign and scale percentage — needs empirical
  verification with a labeled test document.
- [ ] Crop/fold marks — nice-to-have, not required for the early milestones (v0–v2).
- [ ] Should the app print directly, or only produce a file for the user to print
  themselves? (Leaning: produce file + optional in-app "print" button via `QPrinter`.)
- [ ] Signature size auto-detection vs. user-specified.
- [ ] Whether inserted blank pages can be plain blanks only, or also duplicated/
  rotated copies of an existing page (useful for fixing a misscan, not just
  pagination) — v2 (page editing) can start blank-only, revisit if needed.
- [ ] Code-signing/notarization for macOS and Windows builds — needed for a
  distributable installer, not needed for local/dev use; revisit near release.

## 7. Milestones (draft)

No milestone tries to auto-fix pagination/imposition problems on the user's behalf —
the app surfaces what it's doing and lets the user correct it (see §3.2); "automatic"
padding/correction is explicitly out of scope until there's a viewer to judge it by.

1. **v0 — Core frameworks + display source PDF**: stand up the actual application
   skeleton first — PySide6 app shell, project/dependency structure, packaging
   config stubbed in — and get it rendering a source PDF on screen. No imposition
   logic yet. Goal: a real, running, cross-platform GUI app that just views a PDF,
   proving out the toolchain (PySide6 + PyMuPDF + packaging) before any page-math
   is built on top of it.
2. **v1 — Show imposed PDF**: implement the imposition pipeline (§4: signature
   order, 2-up placement, margin/gutter shift and scale) and display its *output*
   in the same viewer from v0, alongside or instead of the source. No editing yet —
   this milestone is about the pipeline being correct and visible, verified against
   §8's known-good manual output and a labeled test PDF for gutter direction.
3. **v2 — Editing page count**: add interactive insert/delete of blank pages
   (§3.2) with live renumbering and undo/redo, feeding straight into the v1
   imposition view so the user can add/remove a page and immediately see the
   effect on signature layout — this is the primary tool for catching
   off-by-one/pagination issues before printing.
4. **v3 — Print integration**: in-app print via `QPrinter`, saved presets per
   paper size / signature size / printer; first packaged builds (PyInstaller/
   Briefcase) for Windows/macOS/Linux.

## 8. Reference: original manual process (verbatim, for posterity)

This is the Linux-only, PostScript-based process that inspired the project and that
§2 and §4.1 analyze above. It's no longer the implementation plan (see §3–4 for the
current PyMuPDF-based, cross-platform approach) but stays here as the source of truth
for expected behavior (signature order, sheet layout) to test the new pipeline against.

```bash
# Convert from pdf, to a PS file
pdf2ps Player-Survival-Guide-v1.2.pdf Player-Survival-Guide-v1.2.ps

# Convert from standard PS to 2 up, signature organized pages
# This assumes no margin or border, but maybe that would be good to explore for a better result
psbook -s20 Player-Survival-Guide-v1.2.ps | psnup -2 -m0 -b0 -P5.5inx8.5in -pletter > Player-Survival-Guide-v1.2-book.ps

# Print, 2 sided, flipped on the short edge
lp -d HL-2280DW -o sides=two-sided-short-edge -P 1,2,3,4,5,6,7,8,9,10 Player-Survival-Guide-v1.2-book.ps

# Other things to explore
# pstops for shifting images around to allow for the spine
# pstops "2:0(36pt,0pt),1(-36pt,0pt)" but it seemed the wrong way around

# Trying to print without borders: smallest possible border, then fit to page
lp -d HL-2280DW -o sides=two-sided-short-edge -P 1,2,3,4,5,6,7,8,9,10 \
   -o page-left=0 -o page-right=0 -o page-top=0 -o page-bottom=0 -o fit-to-page \
   Player-Survival-Guide-v1.2-book.ps

# Shrink pages 3%, center vertically, alternate offset — intended to run between
# psbook and psnup (i.e. on signature-ordered, still-1-up pages)
# pstops "2:0@.97(18pt,9pt),1@.97(0pt,9pt)" input output
# Note: observed an off-by-one issue, not yet diagnosed.
```
