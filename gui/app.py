from __future__ import annotations

from pathlib import Path
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def apply_dark_theme(app: QApplication):
    # register bundled nunito sans fonts
    fonts_dir = Path(__file__).resolve().parent / "fonts"
    if fonts_dir.is_dir():
        for font_path in sorted(fonts_dir.glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(font_path))

    global_font = QFont("Nunito Sans", 10)
    global_font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(global_font)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(10, 10, 10))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(16, 16, 16))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(20, 20, 20))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Text, QColor(210, 210, 210))
    palette.setColor(QPalette.ColorRole.Button, QColor(18, 18, 18))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(140, 140, 140))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(36, 36, 36))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CorridorKey Studio")
    app.setDesktopFileName("corridorkey-studio")
    apply_dark_theme(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
