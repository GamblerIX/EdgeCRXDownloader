#!/usr/bin/env python3
"""Entry point for Edge CRX Downloader (QFluentWidgets version)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
