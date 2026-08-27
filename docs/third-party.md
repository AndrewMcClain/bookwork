# Third-party licences

Bookwork is GPL v3-or-later (see [`COPYING`](../COPYING)). Its dependencies
are not all under the same terms, and one of them carries an obligation worth
understanding before you redistribute a build.

## Runtime dependencies — shipped in every binary

| Package | Licence | Notes |
|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) | **AGPL v3**, or a commercial licence from Artifex | See below. |
| [PySide6](https://doc.qt.io/qtforpython/) (with `shiboken6`) | LGPL v3 | Also available under commercial Qt terms. |

## PyMuPDF is AGPL, and that reaches the whole build

PyMuPDF is dual-licensed: AGPL v3, or a paid commercial licence from Artifex.
Bookwork uses the AGPL side, which is compatible with GPL v3 — GPL v3 §13
explicitly permits combining a GPL v3 work with an AGPL v3 one.

What comes with that permission: **the AGPL's own §13 applies to the
combination.** If you modify Bookwork and let people interact with it over a
network, you have to offer those users the corresponding source. For a desktop
tool that nobody notices — you run it locally, and the clause has nothing to
bite on. It matters if you ever wrap this in a web service.

If you need to avoid the AGPL entirely, the route is a commercial PyMuPDF
licence from Artifex; that is a matter between you and them, not something
Bookwork's own licence can grant.

## PySide6 is LGPL

LGPL v3 requires that recipients be able to replace the Qt libraries with their
own build. A PyInstaller bundle ships Qt as separate shared objects rather than
statically linked, which is the usual way this is satisfied in Python
applications. If you distribute builds widely, satisfy yourself that your
bundle meets LGPL §4 — for instance by also offering the object code or the
unbundled application.

## Development-only dependencies — not shipped

| Package | Licence |
|---|---|
| pytest | MIT |
| pytest-qt | MIT |
| PyInstaller | GPL v2-or-later, with an explicit exception permitting bundling of applications under any licence |

These are build and test tooling. They are not present in a distributed
binary, which is why their permissive terms place no constraint on Bookwork's
own licence — and why PyInstaller's GPL does not force anything either, given
its bundling exception.

## Keeping this current

Regenerate the picture with:

```bash
uv run python -c "import importlib.metadata as m; [print(f\"{p}: {m.metadata(p).get('License-Expression') or m.metadata(p).get('License')}\") for p in ('pymupdf','pyside6','shiboken6','pytest','pytest-qt','pyinstaller')]"
```
