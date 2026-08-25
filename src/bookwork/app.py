"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from bookwork.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("Bookwork")

    window = MainWindow()
    window.show()

    # Optional: `bookwork some.pdf` opens it directly.
    if len(argv) > 1:
        window.open_pdf(argv[1])

    return app.exec()
