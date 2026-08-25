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
