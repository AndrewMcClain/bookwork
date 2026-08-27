# Background

Bookwork replaces this, which worked but was Linux-only and fiddly:

```bash
pdf2ps book.pdf book.ps                      # psutils needs PostScript
psbook -s20 book.ps | psnup -2 -m0 -b0 \
  -P5.5inx8.5in -pletter > book-imposed.ps   # signature order, then 2-up
lp -o sides=two-sided-short-edge book-imposed.ps
```

Plus experiments that never resolved — `pstops` to shift pages apart for the
spine (sign never settled), a 3% shrink to keep content on-page after
shifting, and `-o fit-to-page` guessing at print time. There was also a
persistent off-by-one, never diagnosed.

## Where each problem went

| Problem | Now |
|---|---|
| No margin or gutter; pages butted edge to edge | `margin_pt` / `gutter_pt`; the gutter insets the spine-adjacent edge |
| Spine shift, sign never settled | `_place_in_cell` keys the inset off `spine_on_right`, not a parity check |
| 3% shrink to keep content on-page | Unnecessary — `keep_proportion=True` fits each page to its cell |
| No cut or fold marks | `show_crop_marks` draws L-ticks at the real placed content edge |
| Off-by-one, never diagnosed | The Bound Preview tab. You look at the book instead of reasoning about it |
| `-o fit-to-page` guessing | The imposed PDF is already the right size |

## psbook compatibility

The signature-order algorithm was verified byte-for-byte against real `psbook`
(psutils 3.3.14), including how it pads a trailing partial signature. Those
expectations are pinned in `tests/test_imposition.py`.

One deliberate divergence: **by default the last signature is padded only to
the next multiple of 4, not to a full signature.** `psbook` always pads full,
which wastes paper — a 4-page document at a 20-page signature size costs 5
sheets instead of 1. Set `pad_last_signature_to_full` for the original
behaviour; the tests pinning `psbook`'s exact output pass that flag explicitly.
