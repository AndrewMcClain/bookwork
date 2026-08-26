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

from PySide6.QtCore import Qt

from bookwork.widgets.thumbnail_list import ThumbnailList


def test_not_editable_by_default(qtbot):
    widget = ThumbnailList()
    qtbot.addWidget(widget)
    assert widget.contextMenuPolicy() == Qt.ContextMenuPolicy.DefaultContextMenu


def test_set_editable_enables_custom_context_menu(qtbot):
    widget = ThumbnailList()
    qtbot.addWidget(widget)

    widget.set_editable(True)
    assert widget.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    widget.set_editable(False)
    assert widget.contextMenuPolicy() == Qt.ContextMenuPolicy.DefaultContextMenu


def test_set_editable_can_be_toggled_repeatedly_without_error(qtbot):
    widget = ThumbnailList()
    qtbot.addWidget(widget)
    # Guards against double-connect/double-disconnect errors.
    widget.set_editable(True)
    widget.set_editable(True)
    widget.set_editable(False)
    widget.set_editable(False)
