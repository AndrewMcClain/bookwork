# Background: the manual process this replaces

Bookwork exists to replace a hand-run chain of Linux-only PostScript commands.
Keeping the original here serves two purposes: it explains why the project
exists at all, and it is the reference behaviour the imposition engine was
verified against.

## The original workflow

```bash
# Convert from pdf, to a PS file
pdf2ps Player-Survival-Guide-v1.2.pdf Player-Survival-Guide-v1.2.ps

# Convert from standard PS to 2 up, signature organized pages
# This assumes no margin or border, but maybe that would be good to explore
psbook -s20 Player-Survival-Guide-v1.2.ps \
  | psnup -2 -m0 -b0 -P5.5inx8.5in -pletter > Player-Survival-Guide-v1.2-book.ps

# Print, 2 sided, flipped on the short edge
lp -d HL-2280DW -o sides=two-sided-short-edge -P 1,2,3,4,5,6,7,8,9,10 \
  Player-Survival-Guide-v1.2-book.ps
```

Experiments that were never resolved, kept because they name real problems:

```bash
# Shifting images around to allow for the spine — sign/direction never settled
# pstops "2:0(36pt,0pt),1(-36pt,0pt)"

# Printing without borders: smallest possible margin, then fit to page
lp -d HL-2280DW -o sides=two-sided-short-edge \
   -o page-left=0 -o page-right=0 -o page-top=0 -o page-bottom=0 -o fit-to-page \
   Player-Survival-Guide-v1.2-book.ps

# Shrink pages 3%, centre vertically, alternate offset — intended to run between
# psbook and psnup (i.e. on signature-ordered, still-1-up pages)
# pstops "2:0@.97(18pt,9pt),1@.97(0pt,9pt)"
# Note: observed an off-by-one issue, never diagnosed.
```

## What each step was doing

1. **`pdf2ps`** — `psutils` operates on PostScript, not PDF, so everything had
   to make a lossy round trip through Ghostscript first.
2. **`psbook -s20`** — groups pages into signatures of 20 *pages* (5 sheets)
   and reorders them so that folding produces reading order.
3. **`psnup -2`** — places two already-reordered pages onto each Letter sheet
   side, with no margin (`-m0`) and no border (`-b0`), trimming to 5.5"×8.5".
4. **`lp -o sides=two-sided-short-edge`** — duplexes so that cutting, folding
   and gathering yields a correctly paginated booklet.

## The rough edges it left, and where they went

| Problem | Where it is handled now |
|---|---|
| No margin or gutter — pages butted edge to edge, no room for binding or cutting tolerance | `margin_pt` / `gutter_pt` in `ImpositionParams`; the gutter is an extra inset on each cell's spine-adjacent edge |
| Spine shift attempted with `pstops`, sign never settled | `_place_in_cell` applies the inset to the correct edge explicitly, keyed off `spine_on_right` rather than an implicit parity check |
| 3% shrink to keep content on-page after shifting | Not needed. `show_pdf_page(..., keep_proportion=True)` fits each page into its cell, so shrink falls out of the target rect |
| No cut or fold marks | `show_crop_marks` draws L-shaped ticks at the real placed content edge |
| Off-by-one, never diagnosed | The Bound Preview tab. Rather than reasoning about it, you look at the book as a reader would |
| `-o fit-to-page` guessing at print time | The imposed PDF is already the right size; `printing.py` sizes the printer to the sheet |

## `psbook` compatibility

The signature-order algorithm was verified byte-for-byte against real `psbook`
(psutils 3.3.14) output for several signature sizes, including how it pads a
trailing partial signature. Those expectations are pinned in
`tests/test_imposition.py`.

Bookwork deliberately diverges from `psbook` in one respect: **by default the
last signature is padded only to the next multiple of 4, not to a full
signature.** `psbook` always pads to a full signature, which wastes paper — a
4-page document at a 20-page signature size costs 5 sheets instead of 1. Set
`pad_last_signature_to_full` to get the original behaviour back. The tests that
encode `psbook`'s exact output pass that flag explicitly.
