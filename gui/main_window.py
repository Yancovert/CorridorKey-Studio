from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import cv2

from PySide6.QtCore import Qt, QUrl, Slot, QTimer, QPointF
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QFontDatabase, QImage, QPixmap, QKeySequence, QShortcut, QPalette, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QSlider, QCheckBox,
    QProgressBar, QTextEdit, QGroupBox, QSpinBox, QSplitter,
    QFrame, QMessageBox, QDoubleSpinBox, QScrollArea, QLineEdit
)

from .gpu_info import detect_gpu_profile, GpuProfile, estimate_peak_vram_gb
from .canvas import PreviewCanvas
from .engine import KeyerEngineWorker
from .updater import UpdateCheckWorker, UpdateInstallWorker
from .settings_manager import load_settings, save_settings


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CorridorKey Studio")
        self.resize(1360, 920)
        self.setMinimumSize(1020, 680)
        self.app_root = Path(__file__).resolve().parents[1]

        icon_path = Path(__file__).resolve().parent / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.gpu_profile: GpuProfile = detect_gpu_profile()
        self.worker: KeyerEngineWorker | None = None
        self.update_checker: UpdateCheckWorker | None = None
        self.update_installer: UpdateInstallWorker | None = None
        self.pending_update_branch: str | None = None
        self.pending_update_commit: str | None = None

        self.selected_input: str | None = None
        self.hint_path: str | None = None
        self.clip_width: int = 1920
        self.clip_height: int = 1080
        self.clip_frames: int = 100
        self.clip_fps: float = 24.0

        # video playback engine state
        self.cap_orig: cv2.VideoCapture | None = None
        self.cap_cutout: cv2.VideoCapture | None = None
        self.cap_alpha: cv2.VideoCapture | None = None
        self.cap_checker: cv2.VideoCapture | None = None
        self.cap_fg: cv2.VideoCapture | None = None
        self.current_frame_idx: int = 0
        self.is_playing: bool = False
        self.playback_timer: QTimer = QTimer(self)
        self.playback_timer.timeout.connect(self._on_playback_tick)

        self._setup_theme()
        self._setup_ui()
        self._setup_shortcuts()
        self._apply_gpu_defaults()
        self._load_saved_settings()
        self._check_for_updates()

    def _setup_theme(self):
        # register bundled nunito sans fonts
        fonts_dir = Path(__file__).resolve().parent / "fonts"
        if fonts_dir.is_dir():
            for font_path in sorted(fonts_dir.glob("*.ttf")):
                QFontDatabase.addApplicationFont(str(font_path))

        global_font = QFont("Nunito Sans", 11)
        global_font.setStyleHint(QFont.StyleHint.SansSerif)
        self.setFont(global_font)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(11, 14, 20))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 246, 252))
        palette.setColor(QPalette.ColorRole.Base, QColor(22, 27, 34))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(13, 17, 23))
        palette.setColor(QPalette.ColorRole.Text, QColor(240, 246, 252))
        palette.setColor(QPalette.ColorRole.Button, QColor(22, 27, 34))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(240, 246, 252))
        self.setPalette(palette)

        # sleek high-contrast dark card theme with global nunito sans typography
        self.setStyleSheet("""
            * {
                font-family: 'Nunito Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            }
            QMainWindow, QWidget#centralWidget, QWidget#leftPanel, QWidget#controlsWidget, QScrollArea, QWidget#scrollAreaWidgetContents {
                background-color: #0b0e14;
                color: #e6edf3;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #0b0e14;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #21262d;
                min-height: 28px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #30363d;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QGroupBox {
                background-color: #12151a;
                border: 1px solid #21262d;
                border-radius: 5px;
                margin-top: 16px;
                padding: 14px 10px 10px 10px;
                font-weight: 600;
                font-size: 11.5px;
                color: #c9d1d9;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0px 6px;
                left: 8px;
                top: 2px;
                background-color: #0b0e14;
                color: #8b949e;
                font-size: 11px;
                font-weight: 600;
            }
            QComboBox {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 5px 10px;
                color: #f0f6fc;
                font-size: 12px;
                min-height: 22px;
            }
            QComboBox:hover {
                border-color: #484f58;
                background-color: #1c212a;
            }
            QComboBox:focus {
                border-color: #385175;
                background-color: #161b22;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #30363d;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                background-color: #1b212a;
            }
            QComboBox::down-arrow {
                width: 0px;
                height: 0px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #6e7681;
                margin-right: 2px;
            }
            QComboBox::down-arrow:hover {
                border-top-color: #f0f6fc;
            }
            QComboBox QAbstractItemView {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 4px;
                color: #f0f6fc;
                selection-background-color: #26354a;
                selection-color: #ffffff;
                padding: 4px;
            }
            QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 5px 10px;
                color: #f0f6fc;
                font-size: 12px;
                min-height: 22px;
            }
            QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
                border-color: #484f58;
                background-color: #1b212a;
            }
            QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
                border-color: #385175;
                background-color: #161b22;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #30363d;
                border-bottom: 1px solid #30363d;
                background-color: #1b212a;
                border-top-right-radius: 4px;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 20px;
                border-left: 1px solid #30363d;
                background-color: #1b212a;
                border-bottom-right-radius: 4px;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #242c38;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                width: 0px;
                height: 0px;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-bottom: 4px solid #8b949e;
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                width: 0px;
                height: 0px;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-top: 4px solid #8b949e;
            }
            QCheckBox {
                color: #c9d1d9;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 3px;
            }
            QCheckBox::indicator:hover {
                border-color: #484f58;
            }
            QCheckBox::indicator:checked {
                background-color: #27384e;
                border-color: #3e5677;
            }
            QPushButton {
                background-color: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #21262d;
                border-color: #484f58;
                color: #f0f6fc;
            }
            QPushButton:pressed {
                background-color: #1b212a;
            }
            QPushButton:disabled {
                background-color: #0d1117;
                color: #484f58;
                border-color: #21262d;
            }
        """)

    def _setup_shortcuts(self):
        space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        space_shortcut.activated.connect(self._on_toggle_play_pause)

        step_prev = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        step_prev.activated.connect(self._on_step_prev)

        step_next = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        step_next.activated.connect(self._on_step_next)

    def _setup_ui(self):
        main_widget = QWidget()
        main_widget.setObjectName("centralWidget")
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # 1. header bar (clean and professional)
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(0, 0, 0, 0)
        header_bar.setSpacing(8)

        title_label = QLabel("CorridorKey Studio")
        title_label.setStyleSheet("font-size: 17px; font-weight: 700; color: #f0f6fc; letter-spacing: 0.5px;")
        header_bar.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # footage metadata chips
        self.chip_res = QLabel("No Footage Loaded")
        self.chip_res.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; "
            "padding: 4px 10px; color: #8b949e; font-size: 11px; font-weight: 600;"
        )
        header_bar.addWidget(self.chip_res, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.chip_fps = QLabel("")
        self.chip_fps.setVisible(False)
        self.chip_fps.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; "
            "padding: 4px 10px; color: #8b949e; font-size: 11px; font-weight: 600;"
        )
        header_bar.addWidget(self.chip_fps, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.chip_duration = QLabel("")
        self.chip_duration.setVisible(False)
        self.chip_duration.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; "
            "padding: 4px 10px; color: #8b949e; font-size: 11px; font-weight: 600;"
        )
        header_bar.addWidget(self.chip_duration, alignment=Qt.AlignmentFlag.AlignVCenter)

        header_bar.addStretch()

        vram_text = f"{self.gpu_profile.total_vram_gb} GB" if self.gpu_profile.is_cuda_available else "N/A"
        self.gpu_badge = QLabel(f"GPU: {self.gpu_profile.name} ({vram_text})")
        self.gpu_badge.setToolTip(f"Hardware Tier: {self.gpu_profile.tier_name}\nVRAM: {vram_text}")
        self.gpu_badge.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; "
            "padding: 4px 12px; color: #c9d1d9; font-size: 11.5px; font-weight: 600;"
        )
        header_bar.addWidget(self.gpu_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.open_output_btn = QPushButton("Output Folder")
        self.open_output_btn.setFixedHeight(28)
        self.open_output_btn.setToolTip("Open folder containing exported keying outputs")
        self.open_output_btn.setStyleSheet(
            "QPushButton { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; "
            "padding: 3px 12px; border-radius: 4px; font-size: 11.5px; font-weight: 500; } "
            "QPushButton:hover { background-color: #21262d; border-color: #484f58; color: #ffffff; }"
        )
        self.open_output_btn.clicked.connect(self._open_output_dir)
        header_bar.addWidget(self.open_output_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setFixedHeight(28)
        self.settings_btn.setToolTip("Configure engine defaults, custom presets, and maintenance")
        self.settings_btn.setStyleSheet(
            "QPushButton { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; "
            "padding: 3px 12px; border-radius: 4px; font-size: 11.5px; font-weight: 500; } "
            "QPushButton:hover { background-color: #21262d; border-color: #484f58; color: #ffffff; }"
        )
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        header_bar.addWidget(self.settings_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        header_widget = QWidget()
        header_widget.setLayout(header_bar)
        header_widget.setFixedHeight(34)
        main_layout.addWidget(header_widget)

        # update notification banner
        self.update_banner = QFrame()
        self.update_banner.setObjectName("updateBanner")
        self.update_banner.setVisible(False)
        self.update_banner.setStyleSheet("""
            QFrame#updateBanner {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 5px;
                margin: 2px 0px 4px 0px;
                padding: 6px 12px;
            }
        """)
        ub_layout = QHBoxLayout(self.update_banner)
        ub_layout.setContentsMargins(4, 2, 4, 2)
        ub_layout.setSpacing(10)

        self.update_badge = QLabel("UPDATE")
        self.update_badge.setStyleSheet(
            "background-color: #21262d; color: #8b949e; font-size: 10.5px; font-weight: 700; "
            "padding: 2px 6px; border-radius: 3px; border: 1px solid #30363d;"
        )
        ub_layout.addWidget(self.update_badge)

        self.update_label = QLabel("Update Available")
        self.update_label.setStyleSheet("color: #c9d1d9; font-size: 12px; font-weight: 500; border: none; background: transparent;")
        ub_layout.addWidget(self.update_label)

        self.update_progress_bar = QProgressBar()
        self.update_progress_bar.setRange(0, 100)
        self.update_progress_bar.setValue(0)
        self.update_progress_bar.setMinimumWidth(240)
        self.update_progress_bar.setMaximumWidth(400)
        self.update_progress_bar.setFixedHeight(16)
        self.update_progress_bar.setTextVisible(True)
        self.update_progress_bar.setFormat("%p%")
        self.update_progress_bar.setVisible(False)
        self.update_progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 3px;
                text-align: center;
                color: #c9d1d9;
                font-size: 10.5px;
                font-weight: 600;
            }
            QProgressBar::chunk {
                background-color: #364152;
                border-radius: 2px;
            }
        """)
        ub_layout.addWidget(self.update_progress_bar)

        ub_layout.addStretch()

        self.btn_update_now = QPushButton("Update Now")
        self.btn_update_now.setFixedHeight(26)
        self.btn_update_now.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                color: #f0f6fc;
                font-weight: 600;
                border: 1px solid #363d48;
                border-radius: 4px;
                padding: 3px 12px;
                font-size: 11.5px;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #484f58;
            }
            QPushButton:disabled {
                background-color: #12151a;
                color: #484f58;
                border-color: #21262d;
            }
        """)
        self.btn_update_now.clicked.connect(self._on_click_update_now)
        ub_layout.addWidget(self.btn_update_now)

        self.btn_update_dismiss = QPushButton("Dismiss")
        self.btn_update_dismiss.setFixedHeight(26)
        self.btn_update_dismiss.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #8b949e;
                border: none;
                padding: 3px 8px;
                font-size: 11.5px;
            }
            QPushButton:hover {
                color: #f0f6fc;
            }
        """)
        self.btn_update_dismiss.clicked.connect(lambda: self.update_banner.setVisible(False))
        ub_layout.addWidget(self.btn_update_dismiss)
        main_layout.addWidget(self.update_banner)

        # 2. main body splitter (Left: Settings | Right: Viewer)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #161b22; width: 3px; }")

        # left panel container
        left_panel = QWidget()
        left_panel.setObjectName("leftPanel")
        left_panel.setFixedWidth(420)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # left scrollable panel
        scroll_area = QScrollArea()
        scroll_area.setObjectName("scrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        controls_widget = QWidget()
        controls_widget.setObjectName("controlsWidget")
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 8, 0)
        controls_layout.setSpacing(12)

        # footage input box
        input_group = QGroupBox("Input")
        input_layout = QVBoxLayout(input_group)
        self.drop_area = QPushButton("Drop Video or Click to Browse")
        self.drop_area.setFixedHeight(50)
        self.drop_area.setStyleSheet(
            "QPushButton { border: 1px dashed #30363d; border-radius: 4px; "
            "background-color: #161b22; color: #c9d1d9; font-size: 12px; font-weight: 500; } "
            "QPushButton:hover { border-color: #484f58; background-color: #1c2128; color: #f0f6fc; }"
        )
        self.drop_area.clicked.connect(self._browse_input)
        input_layout.addWidget(self.drop_area)

        self.input_label = QLabel("No file selected")
        self.input_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.input_label.setWordWrap(True)
        input_layout.addWidget(self.input_label)

        self.companion_hint_label = QLabel("")
        self.companion_hint_label.setVisible(False)
        self.companion_hint_label.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: 500;")
        self.companion_hint_label.setWordWrap(True)
        input_layout.addWidget(self.companion_hint_label)

        controls_layout.addWidget(input_group)

        # live resource budget banner
        self.vram_banner = QFrame()
        self.vram_banner.setStyleSheet(
            "background-color: #12151a; border: 1px solid #21262d; border-radius: 4px; padding: 6px 10px;"
        )
        vram_box = QVBoxLayout(self.vram_banner)
        vram_box.setContentsMargins(0, 0, 0, 0)
        vram_box.setSpacing(2)
        self.vram_title = QLabel("VRAM: Calculating...")
        self.vram_title.setWordWrap(True)
        self.vram_title.setStyleSheet("font-weight: 500; color: #8b949e; font-size: 11.5px;")
        self.vram_detail = QLabel("")
        self.vram_detail.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.vram_detail.setWordWrap(True)
        self.vram_detail.setVisible(False)
        vram_box.addWidget(self.vram_title)
        vram_box.addWidget(self.vram_detail)
        controls_layout.addWidget(self.vram_banner)

        # workflow presets
        preset_group = QGroupBox("Preset")
        preset_layout = QVBoxLayout(preset_group)
        self.workflow_combo = QComboBox()
        self.workflow_combo.addItems([
            "Balanced",
            "Quality",
            "High Throughput",
            "Fast Preview",
            "Low Memory",
            "Custom",
        ])
        self.workflow_combo.currentIndexChanged.connect(self._on_workflow_preset_changed)
        preset_layout.addWidget(self.workflow_combo)
        controls_layout.addWidget(preset_group)

        # guidance and despill
        guidance_group = QGroupBox("Keying and Despill")
        guidance_layout = QVBoxLayout(guidance_group)

        guidance_layout.addWidget(QLabel("Guidance:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Auto",
            "First Frame Mask",
            "Video Mask Sequence",
        ])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        guidance_layout.addWidget(self.mode_combo)

        self.hint_btn = QPushButton("Select Mask File...")
        self.hint_btn.setVisible(False)
        self.hint_btn.clicked.connect(self._browse_hint)
        guidance_layout.addWidget(self.hint_btn)

        self.hint_label = QLabel("")
        self.hint_label.setVisible(False)
        self.hint_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        guidance_layout.addWidget(self.hint_label)

        # despill slider + spinbox
        self.despill_slider = QSlider(Qt.Orientation.Horizontal)
        self.despill_slider.setRange(0, 100)
        self.despill_slider.setValue(50)
        self.despill_spin = QDoubleSpinBox()
        self.despill_spin.setRange(0.0, 1.0)
        self.despill_spin.setSingleStep(0.05)
        self.despill_spin.setValue(0.50)
        self._sync_float_slider(self.despill_slider, self.despill_spin, 100.0)
        guidance_layout.addWidget(self._create_slider_param_row(
            "Despill Strength:", self.despill_slider, self.despill_spin, ""
        ))

        controls_layout.addWidget(guidance_group)

        # export deliverables
        export_group = QGroupBox("Output")
        export_layout = QVBoxLayout(export_group)

        self.deliverable_combo = QComboBox()
        self.deliverable_combo.addItems([
            "ProRes 4444 (RGBA)",
            "PNG Sequence (RGBA)",
            "WebM VP9 (RGBA)",
            "QuickTime RLE (RGBA)",
            "TIFF 16-bit (RGBA)",
            "Matte Pack (Fill + Matte)",
            "OpenEXR 32-bit (RGBA)",
            "Separate Passes (FG + Alpha)",
        ])
        export_layout.addWidget(self.deliverable_combo)

        self.blender_script_check = QCheckBox("Generate Blender import script")
        self.blender_script_check.setChecked(True)
        export_layout.addWidget(self.blender_script_check)

        out_row = QHBoxLayout()
        self.outdir_label = QLabel("Output: ./outputs")
        self.outdir_label.setStyleSheet("color: #8b949e; font-size: 11px; font-family: monospace;")
        out_btn = QPushButton("Change...")
        out_btn.setFixedHeight(24)
        out_btn.clicked.connect(self._browse_output_dir)
        row_out_btn = QHBoxLayout()
        out_row.addWidget(self.outdir_label, stretch=1)
        out_row.addWidget(out_btn)
        export_layout.addLayout(out_row)

        controls_layout.addWidget(export_group)

        # advanced engine tuning
        self.advanced_toggle_btn = QPushButton("▸ Advanced Settings")
        self.advanced_toggle_btn.setCheckable(True)
        self.advanced_toggle_btn.setChecked(False)
        self.advanced_toggle_btn.setStyleSheet(
            "QPushButton { background-color: #12151a; border: 1px solid #21262d; border-radius: 4px; "
            "padding: 8px 12px; font-weight: 500; color: #8b949e; text-align: left; } "
            "QPushButton:hover { background-color: #161b22; border-color: #30363d; color: #c9d1d9; } "
            "QPushButton:checked { background-color: #161b22; border-color: #364152; color: #f0f6fc; }"
        )
        self.advanced_toggle_btn.toggled.connect(self._on_toggle_advanced)
        controls_layout.addWidget(self.advanced_toggle_btn)

        self.advanced_container = QWidget()
        self.advanced_container.setVisible(False)
        advanced_layout = QVBoxLayout(self.advanced_container)
        advanced_layout.setContentsMargins(0, 4, 0, 4)
        advanced_layout.setSpacing(10)

        # quick settings bar for advanced settings with saves
        settings_bar = QHBoxLayout()
        settings_bar.setContentsMargins(0, 0, 0, 4)
        settings_bar.setSpacing(6)

        btn_save_defaults = QPushButton("Save Default")
        btn_save_defaults.setFixedHeight(26)
        btn_save_defaults.setToolTip("Save current parameters as default application startup configuration")
        btn_save_defaults.setStyleSheet(
            "QPushButton { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 2px 10px; font-size: 11px; font-weight: 500; } "
            "QPushButton:hover { background-color: #21262d; color: #ffffff; border-color: #484f58; }"
        )
        btn_save_defaults.clicked.connect(self._save_current_as_default)
        settings_bar.addWidget(btn_save_defaults)

        btn_reset_defaults = QPushButton("Reset Auto")
        btn_reset_defaults.setFixedHeight(26)
        btn_reset_defaults.setToolTip("Reset all advanced parameters to GPU hardware optimal values")
        btn_reset_defaults.setStyleSheet(
            "QPushButton { background-color: #161b22; color: #8b949e; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 500; } "
            "QPushButton:hover { background-color: #21262d; color: #f0f6fc; border-color: #484f58; }"
        )
        btn_reset_defaults.clicked.connect(self._apply_gpu_defaults)
        settings_bar.addWidget(btn_reset_defaults)

        settings_bar.addStretch()

        btn_more_settings = QPushButton("Presets...")
        btn_more_settings.setFixedHeight(26)
        btn_more_settings.setToolTip("Open full settings dialog to manage custom profiles and presets")
        btn_more_settings.setStyleSheet(
            "QPushButton { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 500; } "
            "QPushButton:hover { background-color: #21262d; color: #ffffff; border-color: #484f58; }"
        )
        btn_more_settings.clicked.connect(self._open_settings_dialog)
        settings_bar.addWidget(btn_more_settings)

        advanced_layout.addLayout(settings_bar)

        # 1. sampling and temporal windows
        sampling_group = QGroupBox("Temporal Windows")
        sampling_layout = QVBoxLayout(sampling_group)

        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(25, 200)
        self.scale_slider.setValue(100)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.25, 2.0)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setValue(1.0)
        self._sync_float_slider(self.scale_slider, self.scale_spin, 100.0)
        sampling_layout.addWidget(self._create_slider_param_row(
            "Model Scale:", self.scale_slider, self.scale_spin, ""
        ))

        self.start_mode_combo = QComboBox()
        self.start_mode_combo.addItems(["begin", "middle", "random_middle"])
        sampling_layout.addWidget(self._create_param_row(
            "Anchor:", self.start_mode_combo, ""
        ))

        self.chunk_slider = QSlider(Qt.Orientation.Horizontal)
        self.chunk_slider.setRange(1, 192)
        self.chunk_slider.setValue(self.gpu_profile.recommended_chunk)
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(1, 192)
        self.chunk_spin.setValue(self.gpu_profile.recommended_chunk)
        self._sync_int_slider(self.chunk_slider, self.chunk_spin)
        sampling_layout.addWidget(self._create_slider_param_row(
            "Window Chunk:", self.chunk_slider, self.chunk_spin, ""
        ))

        self.stride_slider = QSlider(Qt.Orientation.Horizontal)
        self.stride_slider.setRange(1, 96)
        self.stride_slider.setValue(self.gpu_profile.recommended_stride)
        self.stride_spin = QSpinBox()
        self.stride_spin.setRange(1, 96)
        self.stride_spin.setValue(self.gpu_profile.recommended_stride)
        self._sync_int_slider(self.stride_slider, self.stride_spin)
        sampling_layout.addWidget(self._create_slider_param_row(
            "Window Stride:", self.stride_slider, self.stride_spin, ""
        ))

        self.num_frames_spin = QSpinBox()
        self.num_frames_spin.setRange(-1, 50000)
        self.num_frames_spin.setValue(-1)
        sampling_layout.addWidget(self._create_param_row(
            "Limit Frames:", self.num_frames_spin, ""
        ))

        advanced_layout.addWidget(sampling_group)

        # 2. memory management
        memory_group = QGroupBox("Memory")
        memory_layout = QVBoxLayout(memory_group)

        self.low_vram_check = QCheckBox("Low-VRAM Staged Inference")
        self.low_vram_check.setChecked(self.gpu_profile.recommended_low_vram)
        self.low_vram_check.stateChanged.connect(self._on_param_changed)
        memory_layout.addWidget(self.low_vram_check)

        advanced_layout.addWidget(memory_group)

        # 3. hardware concurrency and throughput
        perf_group = QGroupBox("Performance")
        perf_layout = QVBoxLayout(perf_group)

        self.stage2_batch_slider = QSlider(Qt.Orientation.Horizontal)
        self.stage2_batch_slider.setRange(1, 8)
        self.stage2_batch_slider.setValue(self.gpu_profile.recommended_stage2_batch)
        self.stage2_batch_spin = QSpinBox()
        self.stage2_batch_spin.setRange(1, 8)
        self.stage2_batch_spin.setValue(self.gpu_profile.recommended_stage2_batch)
        self._sync_int_slider(self.stage2_batch_slider, self.stage2_batch_spin)
        perf_layout.addWidget(self._create_slider_param_row(
            "Stage-2 Batch:", self.stage2_batch_slider, self.stage2_batch_spin, ""
        ))

        self.foundation_chunk_slider = QSlider(Qt.Orientation.Horizontal)
        self.foundation_chunk_slider.setRange(2, 32)
        self.foundation_chunk_slider.setValue(self.gpu_profile.recommended_foundation_chunk)
        self.foundation_chunk_spin = QSpinBox()
        self.foundation_chunk_spin.setRange(2, 32)
        self.foundation_chunk_spin.setValue(self.gpu_profile.recommended_foundation_chunk)
        self._sync_int_slider(self.foundation_chunk_slider, self.foundation_chunk_spin)
        perf_layout.addWidget(self._create_slider_param_row(
            "Foundation Chunk:", self.foundation_chunk_slider, self.foundation_chunk_spin, ""
        ))

        self.swin_batch_spin = QSpinBox()
        self.swin_batch_spin.setRange(8, 128)
        self.swin_batch_spin.setSingleStep(8)
        self.swin_batch_spin.setValue(self.gpu_profile.recommended_swin_batch)
        perf_layout.addWidget(self._create_param_row(
            "Swin Batch:", self.swin_batch_spin, ""
        ))

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 32)
        self.threads_spin.setValue(self.gpu_profile.recommended_ffmpeg_threads)
        perf_layout.addWidget(self._create_param_row(
            "Worker Threads (0 = auto):", self.threads_spin, ""
        ))

        advanced_layout.addWidget(perf_group)

        # 4. color space and adjustments
        color_group = QGroupBox("Color Adjustments")
        color_layout = QVBoxLayout(color_group)

        self.linear_check = QCheckBox("Linear Color Space Keying")
        self.linear_check.setChecked(True)
        color_layout.addWidget(self.linear_check)

        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(10, 200)
        self.contrast_slider.setValue(100)
        self.contrast_spin = QDoubleSpinBox()
        self.contrast_spin.setRange(0.1, 2.0)
        self.contrast_spin.setSingleStep(0.05)
        self.contrast_spin.setValue(1.0)
        self._sync_float_slider(self.contrast_slider, self.contrast_spin, 100.0)
        color_layout.addWidget(self._create_slider_param_row("Contrast Multiplier:", self.contrast_slider, self.contrast_spin, ""))

        self.bright_slider = QSlider(Qt.Orientation.Horizontal)
        self.bright_slider.setRange(-100, 100)
        self.bright_slider.setValue(0)
        self.bright_spin = QDoubleSpinBox()
        self.bright_spin.setRange(-1.0, 1.0)
        self.bright_spin.setSingleStep(0.05)
        self.bright_spin.setValue(0.0)
        self._sync_float_slider(self.bright_slider, self.bright_spin, 100.0)
        color_layout.addWidget(self._create_slider_param_row("Brightness Offset:", self.bright_slider, self.bright_spin, ""))

        advanced_layout.addWidget(color_group)

        # hidden compatibility controls
        self.seed_spin = QSpinBox()
        self.seed_spin.setValue(0)
        self.hint_quality_spin = QDoubleSpinBox()
        self.hint_quality_spin.setValue(0.95)
        self.carry_quality_spin = QDoubleSpinBox()
        self.carry_quality_spin.setValue(0.95)
        self.contrast_pivot_spin = QDoubleSpinBox()
        self.contrast_pivot_spin.setValue(0.50)
        self.ffmpeg_codec_combo = QComboBox()
        self.ffmpeg_codec_combo.addItems(["libx264", "libx265", "prores_ks", "ffv1"])
        self.ffmpeg_preset_combo = QComboBox()
        self.ffmpeg_preset_combo.addItems(["slow", "medium", "fast"])
        self.crf_spin = QSpinBox()
        self.crf_spin.setValue(14)
        self.mlp_chunk_spin = QSpinBox()
        self.mlp_chunk_spin.setValue(0)
        self.attn_chunk_spin = QSpinBox()
        self.attn_chunk_spin.setValue(0)
        self.frame_dir_fps_spin = QDoubleSpinBox()
        self.frame_dir_fps_spin.setValue(24.0)
        self.frame_dir_linear_check = QCheckBox()
        self.temp_dir_edit = QLineEdit()

        controls_layout.addWidget(self.advanced_container)

        # action buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Keying")
        self.start_btn.setFixedHeight(40)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #26354a;
                color: #f0f6fc;
                font-weight: 600;
                padding: 8px 18px;
                border: 1px solid #385175;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2d3f59;
                border-color: #4a6a99;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #1e2b3c;
                border-color: #26354a;
            }
            QPushButton:disabled {
                background-color: #161b22;
                color: #484f58;
                border: 1px solid #21262d;
            }
        """)
        self.start_btn.clicked.connect(self._start_keying)
        btn_layout.addWidget(self.start_btn, stretch=3)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #161b22;
                color: #8b949e;
                font-weight: 500;
                padding: 8px 16px;
                border: 1px solid #30363d;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #21262d;
                color: #f0f6fc;
                border-color: #484f58;
            }
            QPushButton:disabled {
                background-color: #0d1117;
                color: #484f58;
                border-color: #21262d;
            }
        """)
        self.cancel_btn.clicked.connect(self._cancel_keying)
        btn_layout.addWidget(self.cancel_btn, stretch=1)

        controls_layout.addStretch()
        scroll_area.setWidget(controls_widget)
        left_layout.addWidget(scroll_area, stretch=1)

        # pinned action buttons at bottom of left panel
        left_layout.addLayout(btn_layout)

        splitter.addWidget(left_panel)

        # ---------------------------------------------------------------------
        # RIGHT PANEL: CANVAS & VIDEO TRANSPORT
        # ---------------------------------------------------------------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(6)

        # view toolbar
        view_bar = QHBoxLayout()
        view_bar.setContentsMargins(0, 0, 0, 0)
        view_bar.setSpacing(8)

        lbl_preview = QLabel("Preview:")
        lbl_preview.setStyleSheet("font-size: 12px; font-weight: 600; color: #e6edf3;")
        view_bar.addWidget(lbl_preview)
        self.view_combo = QComboBox()
        self.view_combo.addItems([
            "Split View (Original vs Cutout)",
            "Checkerboard Composite",
            "Alpha Matte",
            "Despilled RGB",
            "Original Footage",
        ])
        self.view_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        view_bar.addWidget(self.view_combo)

        # zoom presets
        view_bar.addSpacing(6)
        lbl_zoom = QLabel("Zoom:")
        lbl_zoom.setStyleSheet("font-size: 12px; font-weight: 600; color: #e6edf3;")
        view_bar.addWidget(lbl_zoom)
        btn_zoom_fit = QPushButton("Fit")
        btn_zoom_fit.setFixedHeight(28)
        btn_zoom_fit.setMinimumWidth(44)
        btn_zoom_fit.clicked.connect(lambda: self.canvas.set_zoom_mode("fit"))
        view_bar.addWidget(btn_zoom_fit)

        btn_zoom_100 = QPushButton("100%")
        btn_zoom_100.setFixedHeight(28)
        btn_zoom_100.setMinimumWidth(52)
        btn_zoom_100.clicked.connect(lambda: self.canvas.set_zoom_mode("100%"))
        view_bar.addWidget(btn_zoom_100)

        btn_zoom_200 = QPushButton("200%")
        btn_zoom_200.setFixedHeight(28)
        btn_zoom_200.setMinimumWidth(52)
        btn_zoom_200.clicked.connect(lambda: self.canvas.set_zoom_mode("200%"))
        view_bar.addWidget(btn_zoom_200)

        view_bar.addStretch()
        right_layout.addLayout(view_bar)

        # expansive preview canvas
        self.canvas = PreviewCanvas()
        right_layout.addWidget(self.canvas, stretch=1)

        # sleek video playback transport bar
        playback_frame = QFrame()
        playback_frame.setStyleSheet(
            "QFrame { background-color: #0d1117; border: 1px solid #21262d; border-radius: 6px; padding: 6px 10px; }"
        )
        pb_layout = QVBoxLayout(playback_frame)
        pb_layout.setContentsMargins(4, 4, 4, 4)
        pb_layout.setSpacing(6)

        # timeline scrubbing slider
        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setRange(0, 0)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #21262d;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #385175;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #8b949e;
                border: 2px solid #0d1117;
                width: 14px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #c9d1d9;
            }
        """)
        self.timeline_slider.sliderMoved.connect(self._on_timeline_scrubbed)
        self.timeline_slider.valueChanged.connect(self._on_timeline_scrubbed)
        pb_layout.addWidget(self.timeline_slider)

        # transport controls
        transport_layout = QHBoxLayout()
        transport_layout.setContentsMargins(0, 0, 0, 0)
        transport_layout.setSpacing(6)

        self.btn_step_prev = QPushButton("◀◀")
        self.btn_step_prev.setFixedHeight(28)
        self.btn_step_prev.setMinimumWidth(38)
        self.btn_step_prev.setEnabled(False)
        self.btn_step_prev.clicked.connect(self._on_step_prev)
        transport_layout.addWidget(self.btn_step_prev)

        self.btn_play_pause = QPushButton("▶")
        self.btn_play_pause.setFixedHeight(28)
        self.btn_play_pause.setMinimumWidth(46)
        self.btn_play_pause.setEnabled(False)
        self.btn_play_pause.setStyleSheet(
            "QPushButton { background-color: #21262d; border: 1px solid #30363d; color: #f0f6fc; font-weight: 600; font-size: 13px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #30363d; color: #ffffff; border-color: #484f58; } "
            "QPushButton:disabled { background-color: #161b22; color: #484f58; border-color: #21262d; }"
        )
        self.btn_play_pause.clicked.connect(self._on_toggle_play_pause)
        transport_layout.addWidget(self.btn_play_pause)

        self.btn_step_next = QPushButton("▶▶")
        self.btn_step_next.setFixedHeight(28)
        self.btn_step_next.setMinimumWidth(38)
        self.btn_step_next.setEnabled(False)
        self.btn_step_next.clicked.connect(self._on_step_next)
        transport_layout.addWidget(self.btn_step_next)

        self.btn_loop = QPushButton("Loop")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setChecked(True)
        self.btn_loop.setFixedHeight(28)
        self.btn_loop.setMinimumWidth(52)
        self.btn_loop.setStyleSheet(
            "QPushButton { background-color: #161b22; color: #8b949e; border: 1px solid #30363d; padding: 2px 8px; font-size: 11px; font-weight: 600; } "
            "QPushButton:checked { background-color: #21262d; color: #f0f6fc; border-color: #385175; }"
        )
        transport_layout.addWidget(self.btn_loop)

        self.timecode_label = QLabel("00:00:00.00 / 00:00:00.00  [Frame 0 / 0]")
        self.timecode_label.setStyleSheet("color: #8b949e; font-family: monospace; font-size: 11.5px; font-weight: 500; margin-left: 8px;")
        transport_layout.addWidget(self.timecode_label)

        transport_layout.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #8b949e; font-size: 11.5px;")
        transport_layout.addWidget(self.status_label)

        self.btn_toggle_log = QPushButton("Log")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setFixedHeight(26)
        self.btn_toggle_log.setMinimumWidth(46)
        self.btn_toggle_log.setStyleSheet(
            "QPushButton { background-color: #161b22; color: #8b949e; border: 1px solid #30363d; font-size: 11px; font-weight: 600; } "
            "QPushButton:checked { background-color: #21262d; color: #f0f6fc; border-color: #385175; }"
        )
        self.btn_toggle_log.toggled.connect(self._on_toggle_log)
        transport_layout.addWidget(self.btn_toggle_log)

        pb_layout.addLayout(transport_layout)
        right_layout.addWidget(playback_frame)

        # inline progress bar (visible only during render)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background-color: #0b0e14; border: 1px solid #21262d; border-radius: 4px; }
            QProgressBar::chunk { background-color: #385175; border-radius: 3px; }
        """)
        right_layout.addWidget(self.progress_bar)

        # collapsible log drawer
        self.log_container = QWidget()
        self.log_container.setVisible(False)
        lc_layout = QVBoxLayout(self.log_container)
        lc_layout.setContentsMargins(0, 2, 0, 0)
        lc_layout.setSpacing(2)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(110)
        self.log_text.setStyleSheet(
            "background-color: #0d1117; color: #8b949e; font-family: monospace; font-size: 11px; "
            "border: 1px solid #21262d; border-radius: 5px;"
        )
        lc_layout.addWidget(self.log_text)
        right_layout.addWidget(self.log_container)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, stretch=1)

        self.setAcceptDrops(True)
        self.output_dir = Path("./outputs").resolve()

    def _sync_float_slider(self, slider: QSlider, spinbox: QDoubleSpinBox, factor: float):
        spinbox.valueChanged.connect(lambda val: slider.setValue(int(round(val * factor))))
        slider.valueChanged.connect(lambda val: spinbox.setValue(val / factor))
        spinbox.valueChanged.connect(self._on_param_changed)

    def _sync_int_slider(self, slider: QSlider, spinbox: QSpinBox):
        spinbox.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(spinbox.setValue)
        spinbox.valueChanged.connect(self._on_param_changed)

    def _create_param_row(self, label_text: str, widget: QWidget, note_text: str) -> QWidget:
        row_widget = QWidget()
        row_layout = QVBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 4)
        row_layout.setSpacing(3)

        top_layout = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #e6edf3; font-weight: 600; font-size: 12px;")
        top_layout.addWidget(lbl)
        top_layout.addWidget(widget)
        row_layout.addLayout(top_layout)

        if note_text:
            note_lbl = QLabel(note_text)
            note_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
            note_lbl.setWordWrap(True)
            row_layout.addWidget(note_lbl)

        return row_widget

    def _create_slider_param_row(self, label_text: str, slider: QSlider, spinbox: QWidget, note_text: str) -> QWidget:
        row_widget = QWidget()
        row_layout = QVBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 4)
        row_layout.setSpacing(3)

        top_layout = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #e6edf3; font-weight: 600; font-size: 12px;")
        top_layout.addWidget(lbl)
        top_layout.addStretch()
        top_layout.addWidget(spinbox)
        row_layout.addLayout(top_layout)

        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #21262d;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #30363d;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #8b949e;
                border: 2px solid #0d1117;
                width: 14px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #c9d1d9;
            }
        """)
        row_layout.addWidget(slider)

        if note_text:
            note_lbl = QLabel(note_text)
            note_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
            note_lbl.setWordWrap(True)
            row_layout.addWidget(note_lbl)

        return row_widget

    def _apply_gpu_defaults(self):
        self.scale_spin.setValue(1.0)
        self.low_vram_check.setChecked(self.gpu_profile.recommended_low_vram)
        self.chunk_spin.setValue(self.gpu_profile.recommended_chunk)
        self.stride_spin.setValue(self.gpu_profile.recommended_stride)
        self.stage2_batch_spin.setValue(self.gpu_profile.recommended_stage2_batch)
        self.foundation_chunk_spin.setValue(self.gpu_profile.recommended_foundation_chunk)
        self.swin_batch_spin.setValue(self.gpu_profile.recommended_swin_batch)
        self.threads_spin.setValue(self.gpu_profile.recommended_ffmpeg_threads)
        self.ffmpeg_preset_combo.setCurrentText("medium")
        self._update_vram_budget()

    def _load_saved_settings(self):
        saved = load_settings()
        if saved:
            self._apply_settings_dict(saved)

    def _apply_settings_dict(self, data: dict):
        if "scale" in data:
            self.scale_spin.setValue(float(data["scale"]))
        if "chunk" in data:
            self.chunk_spin.setValue(int(data["chunk"]))
        if "stride" in data:
            self.stride_spin.setValue(int(data["stride"]))
        if "start_mode" in data:
            raw_mode = data["start_mode"].split()[0]
            idx = self.start_mode_combo.findText(raw_mode)
            if idx >= 0:
                self.start_mode_combo.setCurrentIndex(idx)
        if "low_vram" in data:
            self.low_vram_check.setChecked(bool(data["low_vram"]))
        if "stage2_batch" in data:
            self.stage2_batch_spin.setValue(int(data["stage2_batch"]))
        if "foundation_chunk" in data:
            self.foundation_chunk_spin.setValue(int(data["foundation_chunk"]))
        if "swin_batch" in data:
            self.swin_batch_spin.setValue(int(data["swin_batch"]))
        if "threads" in data:
            self.threads_spin.setValue(int(data["threads"]))
        if "linear" in data:
            self.linear_check.setChecked(bool(data["linear"]))
        if "despill" in data:
            self.despill_spin.setValue(float(data["despill"]))
        if "contrast" in data:
            self.contrast_spin.setValue(float(data["contrast"]))
        if "bright" in data:
            self.bright_spin.setValue(float(data["bright"]))
        if "deliverable" in data:
            deliv_val = data["deliverable"]
            idx = self.deliverable_combo.findText(deliv_val)
            if idx < 0:
                for i in range(self.deliverable_combo.count()):
                    item = self.deliverable_combo.itemText(i)
                    if deliv_val.split()[0] in item or item.split()[0] in deliv_val:
                        idx = i
                        break
            if idx >= 0:
                self.deliverable_combo.setCurrentIndex(idx)
        if "blender_script" in data:
            self.blender_script_check.setChecked(bool(data["blender_script"]))
        if "output_dir" in data:
            self.output_dir = Path(data["output_dir"]).resolve()
            self.outdir_label.setText(f"Output: {self.output_dir}")

        self._update_vram_budget()

    def _get_current_settings_dict(self) -> dict:
        return {
            "low_vram": self.low_vram_check.isChecked(),
            "scale": round(self.scale_spin.value(), 2),
            "chunk": self.chunk_spin.value(),
            "stride": self.stride_spin.value(),
            "start_mode": self.start_mode_combo.currentText(),
            "stage2_batch": self.stage2_batch_spin.value(),
            "foundation_chunk": self.foundation_chunk_spin.value(),
            "swin_batch": self.swin_batch_spin.value(),
            "threads": self.threads_spin.value(),
            "linear": self.linear_check.isChecked(),
            "despill": round(self.despill_spin.value(), 2),
            "contrast": round(self.contrast_spin.value(), 2),
            "bright": round(self.bright_spin.value(), 2),
            "deliverable": self.deliverable_combo.currentText(),
            "blender_script": self.blender_script_check.isChecked(),
            "output_dir": str(self.output_dir),
        }

    def _save_current_as_default(self):
        data = self._get_current_settings_dict()
        if save_settings(data):
            QMessageBox.information(self, "Settings Saved", "Current settings saved as application default.")
        else:
            QMessageBox.critical(self, "Error", "Failed to save default settings.")

    def _open_settings_dialog(self):
        from .settings_dialog import SettingsDialog
        current_data = self._get_current_settings_dict()
        dlg = SettingsDialog(self, self.gpu_profile, self.app_root, current_data)
        dlg.settings_applied.connect(self._apply_settings_dict)
        dlg.exec()

    def _on_toggle_advanced(self, checked: bool):
        self.advanced_container.setVisible(checked)
        self.advanced_toggle_btn.setText("▾ Advanced Settings" if checked else "▸ Advanced Settings")

    def _on_toggle_log(self, checked: bool):
        self.log_container.setVisible(checked)

    def _on_workflow_preset_changed(self, index: int):
        if index == 0:  # Balanced Studio (Hardware Optimized)
            self._apply_gpu_defaults()
        elif index == 1:  # Maximum Quality (Fine Hair & Edges)
            self.scale_spin.setValue(1.0)
            if self.gpu_profile.total_vram_gb >= 20.0:
                self.chunk_spin.setValue(96)
                self.stride_spin.setValue(24)
                self.low_vram_check.setChecked(False)
                self.stage2_batch_spin.setValue(4)
                self.foundation_chunk_spin.setValue(16)
                self.swin_batch_spin.setValue(64)
            elif self.gpu_profile.total_vram_gb >= 11.5:
                self.chunk_spin.setValue(80)
                self.stride_spin.setValue(20)
                self.low_vram_check.setChecked(False)
                self.stage2_batch_spin.setValue(2)
                self.foundation_chunk_spin.setValue(8)
                self.swin_batch_spin.setValue(32)
            elif self.gpu_profile.total_vram_gb >= 7.5:
                self.chunk_spin.setValue(48)
                self.stride_spin.setValue(16)
                self.low_vram_check.setChecked(False)
                self.stage2_batch_spin.setValue(2)
                self.foundation_chunk_spin.setValue(8)
                self.swin_batch_spin.setValue(32)
            else:
                self.chunk_spin.setValue(16)
                self.stride_spin.setValue(4)
                self.low_vram_check.setChecked(True)
                self.stage2_batch_spin.setValue(1)
                self.foundation_chunk_spin.setValue(4)
                self.swin_batch_spin.setValue(16)
            self.ffmpeg_preset_combo.setCurrentText("slow")
        elif index == 2:  # High-Performance Workstation (24GB+ / Multi-Batch)
            self.scale_spin.setValue(1.0)
            self.chunk_spin.setValue(80)
            self.stride_spin.setValue(40)
            self.low_vram_check.setChecked(False)
            self.stage2_batch_spin.setValue(4)
            self.foundation_chunk_spin.setValue(16)
            self.swin_batch_spin.setValue(64)
            self.threads_spin.setValue(min(12, max(4, (os.cpu_count() or 4) // 2)))
            self.ffmpeg_preset_combo.setCurrentText("medium")
        elif index == 3:  # Fast Turnaround (Speed & Quick Preview)
            self.scale_spin.setValue(1.0)
            if self.gpu_profile.total_vram_gb >= 11.5:
                self.chunk_spin.setValue(48)
                self.stride_spin.setValue(32)
                self.low_vram_check.setChecked(False)
                self.stage2_batch_spin.setValue(4)
                self.foundation_chunk_spin.setValue(16)
                self.swin_batch_spin.setValue(64)
            elif self.gpu_profile.total_vram_gb >= 7.5:
                self.chunk_spin.setValue(32)
                self.stride_spin.setValue(24)
                self.low_vram_check.setChecked(False)
                self.stage2_batch_spin.setValue(2)
                self.foundation_chunk_spin.setValue(8)
                self.swin_batch_spin.setValue(32)
            else:
                self.chunk_spin.setValue(8)
                self.stride_spin.setValue(6)
                self.low_vram_check.setChecked(True)
                self.stage2_batch_spin.setValue(1)
                self.foundation_chunk_spin.setValue(4)
                self.swin_batch_spin.setValue(16)
            self.ffmpeg_preset_combo.setCurrentText("fast")
        elif index == 4:  # Low-VRAM Compatibility (4GB - 6GB Staged)
            self.scale_spin.setValue(1.0)
            self.chunk_spin.setValue(8)
            self.stride_spin.setValue(4)
            self.low_vram_check.setChecked(True)
            self.stage2_batch_spin.setValue(1)
            self.foundation_chunk_spin.setValue(4)
            self.swin_batch_spin.setValue(16)
            self.ffmpeg_preset_combo.setCurrentText("medium")
        # index 5: Custom Advanced Tuning - user values preserved

        self._update_vram_budget()

    def _on_param_changed(self):
        self._update_vram_budget()

    def _get_current_vram_estimate(self) -> float:
        return estimate_peak_vram_gb(
            self.clip_width,
            self.clip_height,
            self.scale_spin.value(),
            self.chunk_spin.value(),
            self.low_vram_check.isChecked()
        )

    def _update_vram_budget(self):
        peak_est = self._get_current_vram_estimate()
        avail = self.gpu_profile.total_vram_gb
        is_safe = (avail == 0) or (peak_est <= avail)
        mode_str = "Staged Memory" if self.low_vram_check.isChecked() else "Direct VRAM"

        if is_safe:
            self.vram_banner.setStyleSheet(
                "background-color: #12151a; border: 1px solid #21262d; border-radius: 4px; padding: 6px 10px;"
            )
            self.vram_title.setText(f"VRAM: ~{peak_est} GB / {avail} GB ({mode_str})")
            self.vram_title.setStyleSheet("font-weight: 500; color: #8b949e; font-size: 11.5px;")
            self.vram_detail.setVisible(False)
        else:
            self.vram_banner.setStyleSheet(
                "background-color: #191410; border: 1px solid #3d2d1d; border-radius: 4px; padding: 6px 10px;"
            )
            self.vram_title.setText(f"VRAM: ~{peak_est} GB / {avail} GB (High Load)")
            self.vram_title.setStyleSheet("font-weight: 500; color: #d29922; font-size: 11.5px;")
            self.vram_detail.setText("Exceeds dedicated VRAM. Enable Low-VRAM if needed.")
            self.vram_detail.setStyleSheet("color: #d29922; font-size: 11px;")
            self.vram_detail.setVisible(True)

    def _browse_input(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Green/Blue Screen Video", "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)"
        )
        if file_path:
            self._set_input_path(file_path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self._set_input_path(path)

    def _set_input_path(self, path: str):
        self.selected_input = path
        p = Path(path)
        size_mb = round(p.stat().st_size / (1024 * 1024), 1)

        self.input_label.setText(f"{p.name} ({size_mb} MB)")
        self.drop_area.setText(f"Loaded: {p.name}")
        self.canvas.set_status_text("Loading input preview...")

        if self.cap_orig:
            self.cap_orig.release()
        self.cap_orig = cv2.VideoCapture(path)

        ret, frame = self.cap_orig.read()
        self.clip_width = int(self.cap_orig.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
        self.clip_height = int(self.cap_orig.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
        self.clip_frames = int(self.cap_orig.get(cv2.CAP_PROP_FRAME_COUNT)) or 100
        self.clip_fps = float(self.cap_orig.get(cv2.CAP_PROP_FPS)) or 24.0

        dur_sec = round(self.clip_frames / max(1.0, self.clip_fps), 1)
        self.chip_res.setText(f"{self.clip_width}x{self.clip_height}")
        self.chip_fps.setText(f"{round(self.clip_fps, 2)} fps")
        self.chip_fps.setVisible(True)
        self.chip_duration.setText(f"{dur_sec}s ({self.clip_frames}f)")
        self.chip_duration.setVisible(True)

        self.current_frame_idx = 0
        self.timeline_slider.setRange(0, max(0, self.clip_frames - 1))
        self.timeline_slider.setValue(0)
        self.timeline_slider.setEnabled(True)
        self.btn_play_pause.setEnabled(True)
        self.btn_step_prev.setEnabled(True)
        self.btn_step_next.setEnabled(True)
        self._update_timecode_display()

        pm = None
        if ret:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pm = QPixmap.fromImage(qimg.copy())
            self.canvas.set_frames(pm, None)

        self._detect_companion_hints(p)
        self._try_load_existing_results(p.stem, pm)
        self._update_vram_budget()

    def _detect_companion_hints(self, input_path: Path):
        parent = input_path.parent
        stem = input_path.stem
        frame_candidates = [
            parent / f"{stem}FrameHint.png",
            parent / f"{stem}_FrameHint.png",
            parent / f"{stem}FrameHint.jpg",
            parent / f"{stem}FrameHint.exr",
        ]
        video_candidates = [
            parent / f"{stem}_AlphaHint.mp4",
            parent / f"{stem}AlphaHint.mp4",
            parent / f"{stem}_Hint.mp4",
        ]

        found_frame = next((f for f in frame_candidates if f.exists()), None)
        found_video = next((f for f in video_candidates if f.exists()), None)

        if found_video:
            self.mode_combo.setCurrentIndex(2)
            self.hint_path = str(found_video)
            self.hint_label.setText(found_video.name)
            self.companion_hint_label.setText(f"Auto-detected mask video: {found_video.name}")
            self.companion_hint_label.setVisible(True)
        elif found_frame:
            self.mode_combo.setCurrentIndex(1)
            self.hint_path = str(found_frame)
            self.hint_label.setText(found_frame.name)
            self.companion_hint_label.setText(f"Auto-detected first-frame mask: {found_frame.name}")
            self.companion_hint_label.setVisible(True)
        else:
            self.companion_hint_label.setVisible(False)

    def _try_load_existing_results(self, stem: str, pm_orig: QPixmap | None):
        try:
            alpha_p = self.output_dir / f"{stem}_alpha.mp4"
            cutout_p = self.output_dir / f"{stem}_cutout.mov"
            fg_p = self.output_dir / f"{stem}_fg.mp4"
            checker_candidates = list(self.output_dir.glob(f"{stem}_checker_comp_*.mp4"))
            checker_p = checker_candidates[0] if checker_candidates else None

            if self.cap_checker: self.cap_checker.release()
            if self.cap_alpha: self.cap_alpha.release()
            if self.cap_cutout: self.cap_cutout.release()
            if self.cap_fg: self.cap_fg.release()

            if checker_p and checker_p.exists():
                self.cap_checker = cv2.VideoCapture(str(checker_p))
            if alpha_p and alpha_p.exists():
                self.cap_alpha = cv2.VideoCapture(str(alpha_p))
            if cutout_p and cutout_p.exists():
                self.cap_cutout = cv2.VideoCapture(str(cutout_p))
            if fg_p and fg_p.exists():
                self.cap_fg = cv2.VideoCapture(str(fg_p))

            self._display_frame_at(0)
            self.status_label.setText("Loaded existing deliverables.")
        except Exception:
            pass

    def _display_frame_at(self, frame_idx: int):
        if not self.cap_orig:
            return

        def read_cap_frame(cap: cv2.VideoCapture | None) -> QPixmap | None:
            if not cap:
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                return None
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            return QPixmap.fromImage(qimg.copy())

        pm_orig = read_cap_frame(self.cap_orig)
        pm_checker = read_cap_frame(self.cap_checker)
        pm_alpha = read_cap_frame(self.cap_alpha)
        pm_cutout = read_cap_frame(self.cap_cutout)
        pm_fg = read_cap_frame(self.cap_fg)

        if pm_checker and not pm_cutout:
            pm_cutout = pm_checker

        self.canvas.set_all_pixmaps({
            "original": pm_orig,
            "cutout": pm_cutout,
            "alpha": pm_alpha,
            "fg": pm_fg,
            "checker": pm_checker,
        })
        self._update_timecode_display()

    def _update_timecode_display(self):
        fps = max(1.0, self.clip_fps)
        cur_sec = self.current_frame_idx / fps
        tot_sec = self.clip_frames / fps

        cur_str = f"{int(cur_sec//60):02d}:{int(cur_sec%60):02d}.{int((cur_sec%1)*100):02d}"
        tot_str = f"{int(tot_sec//60):02d}:{int(tot_sec%60):02d}.{int((tot_sec%1)*100):02d}"
        self.timecode_label.setText(
            f"{cur_str} / {tot_str}  [Frame {self.current_frame_idx + 1} / {self.clip_frames}]"
        )

    def _on_toggle_play_pause(self):
        if not self.cap_orig:
            return
        if self.is_playing:
            self._pause_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        self.is_playing = True
        self.btn_play_pause.setText("||")
        interval_ms = int(1000.0 / max(1.0, self.clip_fps))
        self.playback_timer.start(interval_ms)

    def _pause_playback(self):
        self.is_playing = False
        self.btn_play_pause.setText("▶")
        self.playback_timer.stop()

    def _on_playback_tick(self):
        self.current_frame_idx += 1
        if self.current_frame_idx >= self.clip_frames:
            if self.btn_loop.isChecked():
                self.current_frame_idx = 0
            else:
                self._pause_playback()
                return

        self.timeline_slider.blockSignals(True)
        self.timeline_slider.setValue(self.current_frame_idx)
        self.timeline_slider.blockSignals(False)
        self._display_frame_at(self.current_frame_idx)

    def _on_timeline_scrubbed(self, value: int):
        self.current_frame_idx = value
        self._display_frame_at(self.current_frame_idx)

    def _on_step_prev(self):
        if self.is_playing:
            self._pause_playback()
        self.current_frame_idx = max(0, self.current_frame_idx - 1)
        self.timeline_slider.setValue(self.current_frame_idx)
        self._display_frame_at(self.current_frame_idx)

    def _on_step_next(self):
        if self.is_playing:
            self._pause_playback()
        self.current_frame_idx = min(max(0, self.clip_frames - 1), self.current_frame_idx + 1)
        self.timeline_slider.setValue(self.current_frame_idx)
        self._display_frame_at(self.current_frame_idx)

    def _browse_hint(self):
        is_video = self.mode_combo.currentIndex() == 2
        filter_str = "Video (*.mp4 *.mov)" if is_video else "Mask Image (*.png *.jpg *.jpeg *.exr)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Mask Hint", "", f"{filter_str};;All Files (*)")
        if file_path:
            self.hint_path = file_path
            self.hint_label.setText(Path(file_path).name)

    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", str(self.output_dir))
        if dir_path:
            self.output_dir = Path(dir_path)
            self.outdir_label.setText(f"Output: {self.output_dir.name}")

    def _open_output_dir(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(self.output_dir))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(self.output_dir)])
        else:
            subprocess.Popen(["xdg-open", str(self.output_dir)])

    def _on_mode_changed(self, index: int):
        has_hint = index > 0
        self.hint_btn.setVisible(has_hint)
        self.hint_label.setVisible(has_hint)
        if index == 1:
            self.hint_btn.setText("Select First-Frame Mask...")
        elif index == 2:
            self.hint_btn.setText("Select Mask Video...")

    def _on_view_mode_changed(self, index: int):
        modes = ["split", "checker", "alpha", "fg", "original"]
        self.canvas.set_view_mode(modes[index])

    def _start_keying(self):
        if not self.selected_input or not Path(self.selected_input).exists():
            QMessageBox.warning(self, "Missing Input", "Please select a valid input video file first.")
            return

        peak_est = self._get_current_vram_estimate()
        avail = self.gpu_profile.total_vram_gb
        if avail > 0 and peak_est > avail:
            box = QMessageBox(self)
            box.setWindowTitle("Memory Warning")
            box.setText(
                f"Estimated memory (~{peak_est} GB) exceeds dedicated GPU VRAM ({avail} GB).\n\n"
                f"Continue anyway or auto-adapt parameters?"
            )
            proceed_btn = box.addButton("Proceed", QMessageBox.ButtonRole.AcceptRole)
            adapt_btn = box.addButton("Auto-Adapt", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()

            if box.clickedButton() == adapt_btn:
                self.workflow_combo.setCurrentIndex(0)
                return
            elif box.clickedButton() != proceed_btn:
                return

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting CorridorKey inference...")
        self.log_text.clear()

        formats = [
            "prores4444",
            "png_sequence",
            "webm_vp9",
            "qtrle",
            "tiff_sequence",
            "resolve_pack",
            "openexr_sequence",
            "standard_passes",
        ]
        chosen_format = formats[self.deliverable_combo.currentIndex()]

        repo_root = Path(__file__).resolve().parents[1]
        self.worker = KeyerEngineWorker(
            repo_root=repo_root,
            input_path=self.selected_input,
            output_dir=self.output_dir,
            mode=self.mode_combo.currentText(),
            hint_path=self.hint_path,
            despill=self.despill_spin.value(),
            deliverable_format=chosen_format,
            generate_blender_script=self.blender_script_check.isChecked(),
            num_frames=self.num_frames_spin.value(),
            start_mode=self.start_mode_combo.currentText().split()[0],
            seed=self.seed_spin.value(),
            scale=self.scale_spin.value(),
            hann_chunk=self.chunk_spin.value(),
            hann_stride=self.stride_spin.value(),
            hint_quality=self.hint_quality_spin.value(),
            carry_quality=self.carry_quality_spin.value(),
            linear=self.linear_check.isChecked(),
            linear_contrast=self.contrast_spin.value(),
            linear_brightness=self.bright_spin.value(),
            contrast_pivot=self.contrast_pivot_spin.value(),
            low_vram=self.low_vram_check.isChecked(),
            stage2_batch=self.stage2_batch_spin.value(),
            foundation_chunk=self.foundation_chunk_spin.value(),
            swin_batch=self.swin_batch_spin.value(),
            ffmpeg_codec=self.ffmpeg_codec_combo.currentText(),
            preset=self.ffmpeg_preset_combo.currentText(),
            crf=self.crf_spin.value(),
            ffmpeg_threads=self.threads_spin.value(),
            mlp_chunk=self.mlp_chunk_spin.value(),
            attn_chunk=self.attn_chunk_spin.value(),
            frame_dir_fps=self.frame_dir_fps_spin.value(),
            frame_dir_linear=self.frame_dir_linear_check.isChecked(),
            temp_dir=self.temp_dir_edit.text() if self.temp_dir_edit.text() else None,
        )

        self.worker.progress_update.connect(self._on_progress)
        self.worker.log_output.connect(self._on_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _cancel_keying(self):
        if self.worker:
            self.status_label.setText("Cancelling inference...")
            self.worker.cancel()

    @Slot(int, str)
    def _on_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    @Slot(str)
    def _on_log(self, text: str):
        self.log_text.append(text)

    @Slot(bool, str, dict)
    def _on_finished(self, success: bool, message: str, outputs: dict):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)

        if success:
            msg = f"Keying finished successfully!\n\nDeliverables saved to:\n{self.output_dir}"
            if "prores4444" in outputs:
                msg += f"\n- ProRes 4444: {Path(outputs['prores4444']).name}"
            if "blender_script" in outputs:
                msg += f"\n- Blender Setup Script: {Path(outputs['blender_script']).name}"
            if "webm_vp9" in outputs:
                msg += f"\n- WebM VP9: {Path(outputs['webm_vp9']).name}"

            box = QMessageBox(self)
            box.setWindowTitle("Keying Complete")
            box.setText(msg)
            open_folder_btn = box.addButton("Open Output Folder", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            box.setStyleSheet(
                "QMessageBox { background-color: #0c0c0c; color: #dcdcdc; } "
                "QPushButton { background-color: #1a1a1a; color: #e0e0e0; border: 1px solid #333333; padding: 6px 12px; border-radius: 4px; } "
                "QPushButton:hover { background-color: #262626; }"
            )
            box.exec()
            if box.clickedButton() == open_folder_btn:
                self._open_output_dir()
        else:
            self.log_container.setVisible(True)
            self.btn_toggle_log.setChecked(True)
            QMessageBox.critical(self, "Keying Failed", f"Error during keying:\n{message}")

    def _check_for_updates(self):
        repo_root = Path(__file__).resolve().parents[1]
        self.update_checker = UpdateCheckWorker(repo_root)
        self.update_checker.update_available.connect(self._on_update_available)
        self.update_checker.start()

    @Slot(str, str, str, str)
    def _on_update_available(self, branch: str, remote_commit: str, local_commit: str, version: str):
        self.pending_update_branch = branch
        self.pending_update_commit = remote_commit
        self.update_badge.setText("UPDATE")
        self.update_badge.setStyleSheet(
            "background-color: #21262d; color: #8b949e; font-size: 11px; font-weight: 600; "
            "padding: 2px 6px; border-radius: 3px; border: 1px solid #30363d;"
        )
        self.update_label.setText(
            f"Update available: {branch} ({remote_commit[:7]}). Installed: {local_commit[:7]}."
        )
        self.update_banner.setVisible(True)

    def _on_click_update_now(self):
        if not self.pending_update_branch or not self.pending_update_commit:
            return

        self.btn_update_now.setEnabled(False)
        self.btn_update_now.setText("Updating...")
        self.btn_update_dismiss.setEnabled(False)
        self.update_badge.setText("UPDATING")
        self.update_badge.setStyleSheet(
            "background-color: #21262d; color: #8b949e; font-size: 11px; font-weight: 600; "
            "padding: 2px 6px; border-radius: 3px; border: 1px solid #30363d;"
        )
        self.update_label.setText("Starting update...")
        self.update_progress_bar.setVisible(True)
        self.update_progress_bar.setValue(5)
        repo_root = Path(__file__).resolve().parents[1]
        self.update_installer = UpdateInstallWorker(repo_root, self.pending_update_branch, self.pending_update_commit)
        self.update_installer.progress.connect(self._on_update_progress)
        self.update_installer.finished.connect(self._on_update_finished)
        self.update_installer.start()

    @Slot(int, str)
    def _on_update_progress(self, percent: int, message: str):
        self.update_progress_bar.setValue(percent)
        self.update_label.setText(message)

    @Slot(bool, str)
    def _on_update_finished(self, success: bool, message: str):
        if success:
            self.update_progress_bar.setValue(100)
            self.update_progress_bar.setVisible(True)
            self.update_badge.setText("READY")
            self.update_badge.setStyleSheet(
                "background-color: #1b2636; color: #8b949e; font-size: 11px; font-weight: 600; "
                "padding: 2px 6px; border-radius: 3px; border: 1px solid #26354a;"
            )
            self.update_label.setText("Update installed. Restart application.")
            self.btn_update_now.setText("Restart")
            self.btn_update_now.setEnabled(True)
            try:
                self.btn_update_now.clicked.disconnect()
            except Exception:
                pass
            self.btn_update_now.clicked.connect(self._restart_app)
            self.btn_update_dismiss.setText("Later")
            self.btn_update_dismiss.setEnabled(True)
        else:
            self.update_progress_bar.setVisible(False)
            self.update_badge.setText("ERROR")
            self.update_badge.setStyleSheet(
                "background-color: #2a1b1b; color: #f85149; font-size: 11px; font-weight: 600; "
                "padding: 2px 6px; border-radius: 3px; border: 1px solid #3d2323;"
            )
            self.update_label.setText(f"Update failed: {message}")
            self.btn_update_now.setText("Retry")
            self.btn_update_now.setEnabled(True)
            self.btn_update_dismiss.setEnabled(True)

    def _restart_app(self):
        try:
            self.close()
            launch_sh = self.app_root / "launch_gui.sh"
            launch_bat = self.app_root / "launch_gui.bat"

            if sys.platform == "win32":
                if launch_bat.exists():
                    subprocess.Popen(
                        ["cmd.exe", "/c", str(launch_bat)],
                        cwd=str(self.app_root),
                        creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
                    )
                else:
                    subprocess.Popen([sys.executable, "-m", "gui.app"], cwd=str(self.app_root))
            else:
                if launch_sh.exists():
                    subprocess.Popen(["bash", str(launch_sh)], cwd=str(self.app_root), start_new_session=True)
                else:
                    subprocess.Popen([sys.executable, "-m", "gui.app"], cwd=str(self.app_root), start_new_session=True)
            QApplication.quit()
        except Exception:
            QApplication.quit()

    def closeEvent(self, event):
        if self.playback_timer.isActive():
            self.playback_timer.stop()

        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(500)

        if self.update_checker and self.update_checker.isRunning():
            self.update_checker.wait(300)

        if self.update_installer and self.update_installer.isRunning():
            self.update_installer.wait(500)

        super().closeEvent(event)
