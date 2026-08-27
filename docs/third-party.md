# Third-party licences

Bookwork is GPL v3-or-later ([COPYING](../COPYING)). Its dependencies are not.

| Package | Licence | Shipped? |
|---|---|---|
| PyMuPDF | **AGPL v3**, or commercial from Artifex | yes |
| PySide6 / shiboken6 | LGPL v3 | yes |
| pytest, pytest-qt | MIT | no |
| PyInstaller | GPL v2+, with a bundling exception | no |

## PyMuPDF being AGPL matters

It's compatible — GPL v3 §13 explicitly permits combining with AGPL v3 — but
the AGPL's own §13 then applies to the combination. **Modify Bookwork and let
people use it over a network, and you owe them source.** For a desktop tool
that has nothing to bite on; it matters if you ever wrap this in a web service.

To avoid the AGPL entirely you'd need a commercial PyMuPDF licence from
Artifex. That's between you and them.

## The rest

**PySide6 (LGPL)** requires that recipients can swap in their own Qt build. A
PyInstaller bundle ships Qt as separate shared objects, which is the usual way
that's satisfied. If you distribute widely, check your bundle meets LGPL §4.

**Dev-only tools** aren't in any binary, so their licences don't constrain
Bookwork's — including PyInstaller's GPL, which carries an explicit exception
for the applications it bundles.

## Checking

```bash
uv run python -c "import importlib.metadata as m; [print(p, m.metadata(p).get('License-Expression') or m.metadata(p).get('License')) for p in ('pymupdf','pyside6','pytest','pyinstaller')]"
```
