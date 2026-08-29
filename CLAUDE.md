# Bookwork

Cross-platform PDF imposition tool for booklet/signature printing. PySide6 GUI over PyMuPDF,
Python 3.12+, `uv` for dependencies and running. GPL-3.0-or-later.

Layout is `src/bookwork/` — `imposition.py` (page-ordering maths), `pdf_document.py` (PyMuPDF
wrapper), `printing.py`, `presets.py`, `main_window.py`, and `widgets/` for the Qt panes.

## Verification

All three gate CI (`.github/workflows/ci.yml`), so run all three before calling work done:

```
uv run ruff check src tests
uv run ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

`QT_QPA_PLATFORM=offscreen` is required — there is no display on any CI runner, and the suite
synthesises Qt input events directly rather than needing one. Tests also run on `windows-latest`
and `macos-latest`; macOS has never been driven by hand, so treat platform-specific claims about
it as unverified.

## Conventions

- **Qt overrides keep their camelCase and carry `# noqa: N802 (Qt override)`.** pep8-naming is
  enabled on purpose so that genuinely misnamed helpers are still caught; renaming an override
  means Qt silently stops calling it. See the comment above `extend-select` in `pyproject.toml`.
- **Line length is 110**, not ruff's default 88 — the code was written around it.
- **Line endings are LF**, pinned by `[tool.ruff.format]` and `.gitattributes`. A CRLF conversion
  turns a small change into a whole-file diff; that is what happened in #7.
- **Conventional Commits**, validated by commitizen. `.githooks/commit-msg` enforces it locally
  but is opt-in (`git config core.hooksPath .githooks`).
- Comment the *why* behind non-obvious decisions, in full sentences, naming the concrete failure
  the decision prevents. `pyproject.toml` and `ci.yml` are the reference for that voice — match
  the density of the surrounding code rather than adding to it.
