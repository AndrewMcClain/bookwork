# Bookwork — a PDF imposition tool for home book binding
# Copyright (C) 2026  Andrew McClain
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared test fixtures.

Tests avoid depending on any real-world PDF asset: `make_pdf` builds a
minimal in-memory-generated PDF on disk with `fitz` itself, with a page
count and page size we control.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest
from PySide6.QtCore import QSettings


@pytest.fixture
def make_pdf(tmp_path: Path):
    def _make(num_pages: int = 3, page_size: tuple[float, float] = (612, 792)) -> Path:
        doc = fitz.open()
        for i in range(num_pages):
            page = doc.new_page(width=page_size[0], height=page_size[1])
            page.insert_text((72, 72), f"Page {i + 1}")
        out_path = tmp_path / "test.pdf"
        doc.save(out_path)
        doc.close()
        return out_path

    return _make


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path, monkeypatch):
    """Never let any test read or write the real, persistent user settings
    store (where saved presets live) — redirect `ImpositionPanel`'s default
    to an isolated ini file per test instead. Applies automatically; no test
    needs to request it, and code that explicitly passes its own `settings=`
    (see tests/test_presets.py) is unaffected.
    """
    settings_path = str(tmp_path / "bookwork_test_settings.ini")
    monkeypatch.setattr(
        "bookwork.widgets.imposition_panel.default_settings",
        lambda: QSettings(settings_path, QSettings.Format.IniFormat),
    )


@pytest.fixture(autouse=True)
def instant_page_turns(monkeypatch):
    """Run page-turn animations instantly in tests.

    `PageTurnView` reads its duration at construction, so patching the
    constant here means every widget a test builds lands on its final state
    synchronously. Without this, tests assert against a widget mid-animation
    and can tear it down while a QPropertyAnimation is still driving it.
    Tests that specifically exercise the animation set a duration explicitly.
    """
    monkeypatch.setattr("bookwork.widgets.page_turn_view.TURN_DURATION_MS", 0)
