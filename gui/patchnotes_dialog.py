from __future__ import annotations

import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QSizePolicy
)


def parse_semver(v_str: str | None) -> tuple[int, ...]:
    if not v_str:
        return (0, 0, 0)
    cleaned = v_str.lstrip("v").strip()
    parts = []
    for part in cleaned.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def load_patchnotes(json_path: Path) -> list[dict]:
    if not json_path.is_file():
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def get_installed_version(app_root: Path) -> str:
    build_file = app_root / ".build_version"
    if build_file.is_file():
        try:
            for line in build_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("version="):
                    v = line.split("=", 1)[1].strip()
                    if v:
                        return v
        except Exception:
            pass
    notes = load_patchnotes(app_root / "gui" / "patchnotes.json")
    if notes and "version" in notes[0]:
        return notes[0]["version"]
    return "2.2.0"


class PatchNotesDialog(QDialog):
    def __init__(self, parent: QWidget | None, app_root: Path,
                 since_version: str | None = None,
                 current_version: str | None = None):
        super().__init__(parent)
        self.app_root = app_root
        self.since_version = since_version
        self.current_version = current_version or get_installed_version(app_root)
        self.show_all_history = False

        self.patchnotes_file = self.app_root / "gui" / "patchnotes.json"
        self.all_notes = load_patchnotes(self.patchnotes_file)

        self.setWindowTitle("What's New - CorridorKey Studio")
        self.resize(700, 640)
        self.setMinimumSize(540, 480)

        self._setup_theme()
        self._setup_ui()

    def _setup_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #16181b;
                color: #dce1e7;
                font-family: 'Nunito Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #16181b;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background-color: #2b3038;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #3b424d;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)

        # header title and subtitle
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        title_lbl = QLabel("What's New in CorridorKey Studio")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #f0f6fc;")
        header_layout.addWidget(title_lbl)

        self.sub_lbl = QLabel()
        self.sub_lbl.setStyleSheet("font-size: 12px; color: #8b949e;")
        header_layout.addWidget(self.sub_lbl)

        layout.addLayout(header_layout)

        # scrollable card feed
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.feed_widget = QWidget()
        self.feed_layout = QVBoxLayout(self.feed_widget)
        self.feed_layout.setContentsMargins(0, 0, 8, 0)
        self.feed_layout.setSpacing(14)
        self.feed_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.feed_widget)
        layout.addWidget(self.scroll_area, stretch=1)

        # bottom actions bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)

        self.toggle_history_btn = QPushButton("Show Complete Release History")
        self.toggle_history_btn.setStyleSheet("""
            QPushButton {
                background-color: #21252b;
                color: #8b949e;
                border: 1px solid #333942;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 11.5px;
            }
            QPushButton:hover {
                background-color: #2b3038;
                color: #dce1e7;
                border-color: #484f58;
            }
        """)
        self.toggle_history_btn.clicked.connect(self._on_toggle_history)
        bottom_bar.addWidget(self.toggle_history_btn)

        bottom_bar.addStretch()

        close_btn = QPushButton("Got it")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #3b82f6;
                border-radius: 4px;
                padding: 6px 22px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
                border-color: #60a5fa;
            }
        """)
        close_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(close_btn)

        layout.addLayout(bottom_bar)

        self._render_notes()

    def _render_notes(self):
        # clear existing cards
        while self.feed_layout.count():
            item = self.feed_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        since_tuple = parse_semver(self.since_version)
        current_tuple = parse_semver(self.current_version)

        # filter unviewed entries if since_version is present and not showing full history
        filtered = []
        for note in self.all_notes:
            v_tuple = parse_semver(note.get("version", ""))
            if self.show_all_history:
                filtered.append(note)
            elif self.since_version and since_tuple < current_tuple:
                # include updates newer than since_version
                if v_tuple > since_tuple:
                    filtered.append(note)
            else:
                # first launch or latest viewed: display latest release by default
                filtered.append(note)

        # fallback to all notes if filter returned empty
        display_notes = filtered if filtered else self.all_notes

        # update subtitle context
        if self.show_all_history:
            self.sub_lbl.setText("Complete version history across all updates.")
            self.toggle_history_btn.setText("Show Recent Changes Only")
            self.toggle_history_btn.setVisible(bool(self.since_version and since_tuple < current_tuple))
        elif self.since_version and since_tuple < current_tuple:
            count = len(display_notes)
            plural = "updates" if count != 1 else "update"
            self.sub_lbl.setText(
                f"You lagged behind {count} {plural}. Here is everything that changed (v{self.since_version} -> v{self.current_version}):"
            )
            self.toggle_history_btn.setText("Show Complete Release History")
            self.toggle_history_btn.setVisible(True)
        else:
            self.sub_lbl.setText(f"Release highlights for CorridorKey Studio v{self.current_version}")
            self.toggle_history_btn.setText("Show Complete Release History")
            self.toggle_history_btn.setVisible(True)

        for note in display_notes:
            card = self._create_release_card(note)
            self.feed_layout.addWidget(card)

    def _create_release_card(self, note: dict) -> QWidget:
        card = QFrame()
        card.setObjectName("releaseCard")
        card.setStyleSheet("""
            QFrame#releaseCard {
                background-color: #20242a;
                border: 1px solid #2e343d;
                border-radius: 6px;
            }
            QLabel {
                border: none;
                background-color: transparent;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # top row: badge, title, date
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        version = note.get("version", "Update")
        badge = QLabel(f"v{version}")
        badge.setStyleSheet("""
            QLabel {
                background-color: #1d4ed8;
                color: #ffffff;
                font-size: 11px;
                font-weight: 700;
                padding: 3px 8px;
                border-radius: 4px;
                border: none;
            }
        """)
        top_row.addWidget(badge)

        title = note.get("title", "")
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 13.5px; font-weight: 700; color: #f0f6fc;")
        top_row.addWidget(title_lbl)

        top_row.addStretch()

        date_str = note.get("date", "")
        if date_str:
            date_lbl = QLabel(date_str)
            date_lbl.setStyleSheet("font-size: 11px; color: #8b949e;")
            top_row.addWidget(date_lbl)

        layout.addLayout(top_row)

        # highlights summary
        highlights = note.get("highlights", "")
        if highlights:
            high_lbl = QLabel(highlights)
            high_lbl.setWordWrap(True)
            high_lbl.setStyleSheet("font-size: 12px; color: #c9d1d9; line-height: 1.4;")
            layout.addWidget(high_lbl)

        # sections: features, improvements, fixes
        sections = [
            ("Features", note.get("features", []), "#34d399"),
            ("Improvements", note.get("improvements", []), "#60a5fa"),
            ("Fixes", note.get("fixes", []), "#fbbf24")
        ]

        for sec_name, items, accent_color in sections:
            if not items:
                continue

            sec_header = QLabel(sec_name.upper())
            sec_header.setStyleSheet(
                f"font-size: 10.5px; font-weight: 700; color: {accent_color}; "
                "letter-spacing: 0.5px; margin-top: 4px;"
            )
            layout.addWidget(sec_header)

            for itm in items:
                bullet_row = QHBoxLayout()
                bullet_row.setSpacing(6)
                bullet_row.setContentsMargins(6, 0, 0, 0)

                dot_lbl = QLabel("-")
                dot_lbl.setStyleSheet(f"color: {accent_color}; font-weight: 700; font-size: 12px;")
                dot_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                bullet_row.addWidget(dot_lbl, alignment=Qt.AlignmentFlag.AlignTop)

                text_lbl = QLabel(itm)
                text_lbl.setWordWrap(True)
                text_lbl.setStyleSheet("font-size: 11.5px; color: #dce1e7; line-height: 1.3;")
                bullet_row.addWidget(text_lbl, stretch=1)

                layout.addLayout(bullet_row)

        return card

    def _on_toggle_history(self):
        self.show_all_history = not self.show_all_history
        self._render_notes()
