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
    QFrame, QMessageBox, QDoubleSpinBox, QScrollArea, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QApplication
)

from .gpu_info import (
    detect_gpu_profile, GpuProfile, estimate_peak_vram_gb,
    enumerate_system_gpus, get_gpu_dropdown_options, SystemGpuDevice
)
from .canvas import PreviewCanvas
from .engine import KeyerEngineWorker
from .updater import UpdateCheckWorker, UpdateInstallWorker
from .settings_manager import load_settings, save_settings


class MainWindow(QMainWindow):
    BUFFER_NAMES = ["original", "cutout", "alpha", "fg", "checker"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CorridorKey Studio")
        self.resize(1180, 780)
        self.setMinimumSize(800, 560)
        self.app_root = Path(__file__).resolve().parents[1]

        icon_path = Path(__file__).resolve().parent / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.system_gpus: list[SystemGpuDevice] = enumerate_system_gpus()
        self.gpu_options = get_gpu_dropdown_options(self.system_gpus)
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

        # batch render queue state
        self.queue_items: list[dict] = []
        self._is_processing_queue: bool = False
        self._queue_current_idx: int = 0

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
        self.output_dir: Path = Path("./outputs").resolve()

        self._setup_theme()
        self._setup_ui()
        self._setup_shortcuts()
        self._apply_gpu_defaults()
        self._load_saved_settings()
        self._check_for_updates()
        self._check_patchnotes_on_launch()

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
        palette.setColor(QPalette.ColorRole.Window, QColor(26, 29, 33))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(230, 234, 240))
        palette.setColor(QPalette.ColorRole.Base, QColor(23, 26, 30))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 34, 39))
        palette.setColor(QPalette.ColorRole.Text, QColor(230, 234, 240))
        palette.setColor(QPalette.ColorRole.Button, QColor(36, 40, 46))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(213, 218, 222))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(43, 85, 128))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

        # clean, cohesive professional studio theme
        self.setStyleSheet("""
            * {
                font-family: 'Nunito Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            }
            QMainWindow, QWidget#centralWidget, QWidget#leftPanel, QWidget#controlsWidget, QScrollArea, QWidget#scrollAreaWidgetContents {
                background-color: #1a1d21;
                color: #dce1e7;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #2f353d;
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3d4550;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QGroupBox {
                background-color: #21252b;
                border: 1px solid #2e343d;
                border-radius: 5px;
                margin-top: 14px;
                padding: 10px 8px 8px 8px;
                font-weight: 600;
                font-size: 11.5px;
                color: #b0bac5;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0px 4px;
                left: 8px;
                top: 1px;
                background-color: #1a1d21;
                color: #7f8a96;
                font-size: 11px;
                font-weight: 600;
            }
            QComboBox {
                background-color: #171a1e;
                border: 1px solid #333942;
                border-radius: 4px;
                padding: 4px 8px;
                color: #e6eaef;
                font-size: 11.5px;
                min-height: 22px;
            }
            QComboBox:hover {
                border-color: #454d58;
                background-color: #1b1f24;
            }
            QComboBox:focus {
                border-color: #3b82f6;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #333942;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                background-color: #1c2025;
            }
            QComboBox::down-arrow {
                width: 0px;
                height: 0px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #717a86;
                margin-right: 2px;
            }
            QComboBox::down-arrow:hover {
                border-top-color: #e6eaef;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1d21;
                border: 1px solid #333942;
                border-radius: 4px;
                color: #e6eaef;
                selection-background-color: #244166;
                selection-color: #ffffff;
                padding: 4px;
            }
            QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #171a1e;
                border: 1px solid #333942;
                border-radius: 4px;
                padding: 4px 6px;
                color: #e6eaef;
                font-size: 11.5px;
                min-height: 22px;
            }
            QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
                border-color: #454d58;
                background-color: #1b1f24;
            }
            QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
                border-color: #3b82f6;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 18px;
                border-left: 1px solid #333942;
                border-bottom: 1px solid #333942;
                background-color: #1c2025;
                border-top-right-radius: 4px;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 18px;
                border-left: 1px solid #333942;
                background-color: #1c2025;
                border-bottom-right-radius: 4px;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #262c33;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                width: 0px;
                height: 0px;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-bottom: 4px solid #717a86;
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                width: 0px;
                height: 0px;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-top: 4px solid #717a86;
            }
            QCheckBox {
                color: #b0bac5;
                font-size: 11.5px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                background-color: #171a1e;
                border: 1px solid #333942;
                border-radius: 3px;
            }
            QCheckBox::indicator:hover {
                border-color: #454d58;
            }
            QCheckBox::indicator:checked {
                background-color: #254d79;
                border-color: #3b82f6;
            }
            QPushButton {
                background-color: #24282e;
                color: #b6c2cf;
                border: 1px solid #333942;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11.5px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2c323a;
                border-color: #444c57;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #1d2126;
            }
            QPushButton:disabled {
                background-color: #16181b;
                color: #4e555e;
                border-color: #24282d;
            }
        """)

    def _setup_shortcuts(self):
        space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        space_shortcut.activated.connect(self._on_toggle_play_pause)

        step_prev = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        step_prev.activated.connect(self._on_step_prev)

        step_next = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        step_next.activated.connect(self._on_step_next)

        swap_shortcut = QShortcut(QKeySequence(Qt.Key.Key_X), self)
        swap_shortcut.activated.connect(self._on_toggle_swap_buffers)

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
        header_bar.setSpacing(6)

        title_label = QLabel("CorridorKey Studio")
        title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #f0f6fc; letter-spacing: 0.3px;")
        header_bar.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # unified footage metadata chip
        self.chip_footage = QLabel("No Footage Loaded")
        self.chip_footage.setStyleSheet(
            "background-color: #21252b; border: 1px solid #2e343d; border-radius: 4px; "
            "padding: 3px 8px; color: #7f8a96; font-size: 11px; font-weight: 600;"
        )
        header_bar.addWidget(self.chip_footage, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.chip_res = self.chip_footage
        self.chip_fps = QLabel("")
        self.chip_fps.setVisible(False)
        self.chip_duration = QLabel("")
        self.chip_duration.setVisible(False)

        header_bar.addStretch()

        vram_text = f"{self.gpu_profile.total_vram_gb} GB" if self.gpu_profile.is_cuda_available else "N/A"
        short_gpu = self.gpu_profile.short_name
        self.gpu_badge = QLabel(f"{short_gpu} ({vram_text})")
        self.gpu_badge.setToolTip(f"GPU: {self.gpu_profile.name}\nTier: {self.gpu_profile.tier_name}\nVRAM: {vram_text}")
        self.gpu_badge.setStyleSheet(
            "background-color: #21252b; border: 1px solid #2e343d; border-radius: 4px; "
            "padding: 3px 10px; color: #b0bac5; font-size: 11px; font-weight: 600;"
        )
        header_bar.addWidget(self.gpu_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.open_output_btn = QPushButton("Output Folder")
        self.open_output_btn.setFixedHeight(26)
        self.open_output_btn.setToolTip("Open folder containing exported keying outputs")
        self.open_output_btn.clicked.connect(self._open_output_dir)
        header_bar.addWidget(self.open_output_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.btn_queue_toggle = QPushButton("Batch Queue (0)")
        self.btn_queue_toggle.setFixedHeight(26)
        self.btn_queue_toggle.setCheckable(True)
        self.btn_queue_toggle.setChecked(False)
        self.btn_queue_toggle.setToolTip("Toggle batch render queue panel")
        self.btn_queue_toggle.clicked.connect(self._on_toggle_queue_drawer)
        header_bar.addWidget(self.btn_queue_toggle, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setFixedHeight(26)
        self.settings_btn.setToolTip("Configure engine defaults, custom presets, and maintenance")
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        header_bar.addWidget(self.settings_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.whats_new_btn = QPushButton("What's New")
        self.whats_new_btn.setFixedHeight(26)
        self.whats_new_btn.setToolTip("View recent update highlights and release notes")
        self.whats_new_btn.clicked.connect(lambda: self._open_patchnotes_dialog())
        header_bar.addWidget(self.whats_new_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        header_widget = QWidget()
        header_widget.setLayout(header_bar)
        header_widget.setFixedHeight(32)
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

        left_panel = QWidget()
        left_panel.setObjectName("leftPanel")
        left_panel.setMinimumWidth(330)
        left_panel.setMaximumWidth(460)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # left scrollable panel
        scroll_area = QScrollArea()
        scroll_area.setObjectName("scrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        controls_widget = QWidget()
        controls_widget.setObjectName("controlsWidget")
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 4, 0)
        controls_layout.setSpacing(8)

        # footage input box
        input_group = QGroupBox("Input Video")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(5)
        self.drop_area = QPushButton("Drop Video or Click to Browse")
        self.drop_area.setFixedHeight(40)
        self.drop_area.setStyleSheet(
            "QPushButton { border: 1px dashed #3a414c; border-radius: 4px; "
            "background-color: #171a1e; color: #c4ccd6; font-size: 11.5px; font-weight: 500; } "
            "QPushButton:hover { border-color: #4f5866; background-color: #1c2025; color: #ffffff; }"
        )
        self.drop_area.clicked.connect(self._browse_input)
        input_layout.addWidget(self.drop_area)

        self.input_label = QLabel("No file selected")
        self.input_label.setStyleSheet("color: #7f8a96; font-size: 11px;")
        self.input_label.setWordWrap(True)
        input_layout.addWidget(self.input_label)

        self.companion_hint_label = QLabel("")
        self.companion_hint_label.setVisible(False)
        self.companion_hint_label.setStyleSheet("color: #7f8a96; font-size: 11px; font-weight: 500;")
        self.companion_hint_label.setWordWrap(True)
        input_layout.addWidget(self.companion_hint_label)

        self.vram_warning = QLabel("")
        self.vram_warning.setWordWrap(True)
        self.vram_warning.setVisible(False)
        self.vram_warning.setStyleSheet(
            "background-color: #272115; border: 1px solid #4a3a18; border-radius: 4px; "
            "padding: 4px 8px; color: #e5b642; font-size: 11px; font-weight: 500;"
        )
        input_layout.addWidget(self.vram_warning)

        controls_layout.addWidget(input_group)

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
        guidance_layout.setSpacing(6)

        screen_row = QHBoxLayout()
        lbl_screen = QLabel("Screen Color:")
        lbl_screen.setStyleSheet("color: #9aa4b0; font-size: 11.5px; font-weight: 500;")
        self.screen_color_combo = QComboBox()
        self.screen_color_combo.addItems([
            "Auto Detect",
            "Green Screen",
            "Blue Screen",
        ])
        screen_row.addWidget(lbl_screen)
        screen_row.addWidget(self.screen_color_combo, stretch=1)
        guidance_layout.addLayout(screen_row)

        mode_row = QHBoxLayout()
        lbl_mode = QLabel("Guidance:")
        lbl_mode.setStyleSheet("color: #9aa4b0; font-size: 11.5px; font-weight: 500;")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Auto",
            "First Frame Mask",
            "Video Mask Sequence",
        ])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(lbl_mode)
        mode_row.addWidget(self.mode_combo, stretch=1)
        guidance_layout.addLayout(mode_row)

        self.hint_btn = QPushButton("Select Mask File...")
        self.hint_btn.setVisible(False)
        self.hint_btn.clicked.connect(self._browse_hint)
        guidance_layout.addWidget(self.hint_btn)

        self.hint_label = QLabel("")
        self.hint_label.setVisible(False)
        self.hint_label.setStyleSheet("color: #7f8a96; font-size: 11px;")
        guidance_layout.addWidget(self.hint_label)

        # alpha hint parameter controls
        self.hint_controls_widget = QWidget()
        hc_layout = QVBoxLayout(self.hint_controls_widget)
        hc_layout.setContentsMargins(0, 0, 0, 0)
        hc_layout.setSpacing(4)

        ref_row = QHBoxLayout()
        lbl_ref = QLabel("Ref Frame:")
        lbl_ref.setStyleSheet("color: #9aa4b0; font-size: 11.5px; font-weight: 500;")
        self.ref_frame_spin = QSpinBox()
        self.ref_frame_spin.setRange(0, 50000)
        self.ref_frame_spin.setValue(0)
        self.btn_set_ref_frame = QPushButton("Set Current")
        self.btn_set_ref_frame.setFixedHeight(22)
        self.btn_set_ref_frame.setToolTip("Set active playhead position as hint reference frame")
        self.btn_set_ref_frame.clicked.connect(self._set_current_as_ref_frame)
        ref_row.addWidget(lbl_ref)
        ref_row.addWidget(self.ref_frame_spin, stretch=1)
        ref_row.addWidget(self.btn_set_ref_frame)
        hc_layout.addLayout(ref_row)

        self.hint_quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.hint_quality_slider.setRange(0, 100)
        self.hint_quality_slider.setValue(75)
        self.hint_quality_spin = QDoubleSpinBox()
        self.hint_quality_spin.setRange(0.0, 1.0)
        self.hint_quality_spin.setSingleStep(0.05)
        self.hint_quality_spin.setValue(0.75)
        self.hint_quality_spin.setFixedWidth(56)
        self._sync_float_slider(self.hint_quality_slider, self.hint_quality_spin, 100.0)
        hc_layout.addWidget(self._create_slider_param_row("Hint Strength:", self.hint_quality_slider, self.hint_quality_spin, ""))

        self.carry_quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.carry_quality_slider.setRange(0, 100)
        self.carry_quality_slider.setValue(95)
        self.carry_quality_spin = QDoubleSpinBox()
        self.carry_quality_spin.setRange(0.0, 1.0)
        self.carry_quality_spin.setSingleStep(0.05)
        self.carry_quality_spin.setValue(0.95)
        self.carry_quality_spin.setFixedWidth(56)
        self._sync_float_slider(self.carry_quality_slider, self.carry_quality_spin, 100.0)
        hc_layout.addWidget(self._create_slider_param_row("Internal Memory:", self.carry_quality_slider, self.carry_quality_spin, ""))

        self.carry_hint_check = QCheckBox("Propagate Memory Across Shots")
        self.carry_hint_check.setChecked(True)
        hc_layout.addWidget(self.carry_hint_check)

        self.hint_controls_widget.setVisible(False)
        guidance_layout.addWidget(self.hint_controls_widget)

        # despill slider + spinbox
        self.despill_slider = QSlider(Qt.Orientation.Horizontal)
        self.despill_slider.setRange(0, 100)
        self.despill_slider.setValue(50)
        self.despill_spin = QDoubleSpinBox()
        self.despill_spin.setRange(0.0, 1.0)
        self.despill_spin.setSingleStep(0.05)
        self.despill_spin.setValue(0.50)
        self.despill_spin.setFixedWidth(56)
        self._sync_float_slider(self.despill_slider, self.despill_spin, 100.0)
        guidance_layout.addWidget(self._create_slider_param_row(
            "Despill Strength:", self.despill_slider, self.despill_spin, ""
        ))

        controls_layout.addWidget(guidance_group)

        # post-processing and quality refinements (1:1 with CorridorKey Workbench 2.0)
        quality_group = QGroupBox("Quality Refinements")
        quality_layout = QVBoxLayout(quality_group)
        quality_layout.setSpacing(6)

        self.keep_solid_check = QCheckBox("Keep Original in Solid Core")
        self.keep_solid_check.setToolTip("Preserves pristine camera textures in high-confidence core regions (alpha > 0.95)")
        self.keep_solid_check.setChecked(False)
        self.keep_solid_check.toggled.connect(self._on_toggle_keep_solid)
        quality_layout.addWidget(self.keep_solid_check)

        self.solid_options_widget = QWidget()
        solid_options_layout = QVBoxLayout(self.solid_options_widget)
        solid_options_layout.setContentsMargins(14, 0, 0, 0)
        solid_options_layout.setSpacing(4)

        erode_row = QHBoxLayout()
        erode_lbl = QLabel("Erosion (px):")
        erode_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.solid_erode_spin = QSpinBox()
        self.solid_erode_spin.setRange(0, 32)
        self.solid_erode_spin.setValue(4)
        erode_row.addWidget(erode_lbl)
        erode_row.addStretch()
        erode_row.addWidget(self.solid_erode_spin)
        solid_options_layout.addLayout(erode_row)

        blur_row = QHBoxLayout()
        blur_lbl = QLabel("Transition Blur (px):")
        blur_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.solid_blur_spin = QSpinBox()
        self.solid_blur_spin.setRange(0, 32)
        self.solid_blur_spin.setValue(4)
        blur_row.addWidget(blur_lbl)
        blur_row.addStretch()
        blur_row.addWidget(self.solid_blur_spin)
        solid_options_layout.addLayout(blur_row)

        self.solid_options_widget.setVisible(False)
        quality_layout.addWidget(self.solid_options_widget)

        self.despeckle_check = QCheckBox("Despeckle Noise Cleanup")
        self.despeckle_check.setToolTip("Removes isolated floating sensor noise and green screen artifacts via connected components")
        self.despeckle_check.setChecked(False)
        self.despeckle_check.toggled.connect(self._on_toggle_despeckle)
        quality_layout.addWidget(self.despeckle_check)

        self.despeckle_options_widget = QWidget()
        despeckle_options_layout = QVBoxLayout(self.despeckle_options_widget)
        despeckle_options_layout.setContentsMargins(14, 0, 0, 0)
        despeckle_options_layout.setSpacing(4)

        thresh_row = QHBoxLayout()
        thresh_lbl = QLabel("Min Area (px):")
        thresh_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.despeckle_thresh_spin = QSpinBox()
        self.despeckle_thresh_spin.setRange(10, 5000)
        self.despeckle_thresh_spin.setSingleStep(25)
        self.despeckle_thresh_spin.setValue(250)
        thresh_row.addWidget(thresh_lbl)
        thresh_row.addStretch()
        thresh_row.addWidget(self.despeckle_thresh_spin)
        despeckle_options_layout.addLayout(thresh_row)

        dil_row = QHBoxLayout()
        dil_lbl = QLabel("Dilation (px):")
        dil_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.despeckle_dil_spin = QSpinBox()
        self.despeckle_dil_spin.setRange(0, 16)
        self.despeckle_dil_spin.setValue(4)
        dil_row.addWidget(dil_lbl)
        dil_row.addStretch()
        dil_row.addWidget(self.despeckle_dil_spin)
        despeckle_options_layout.addLayout(dil_row)

        dblur_row = QHBoxLayout()
        dblur_lbl = QLabel("Edge Blur (px):")
        dblur_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.despeckle_blur_spin = QSpinBox()
        self.despeckle_blur_spin.setRange(0, 16)
        self.despeckle_blur_spin.setValue(4)
        dblur_row.addWidget(dblur_lbl)
        dblur_row.addStretch()
        dblur_row.addWidget(self.despeckle_blur_spin)
        despeckle_options_layout.addLayout(dblur_row)

        self.despeckle_options_widget.setVisible(False)
        quality_layout.addWidget(self.despeckle_options_widget)

        controls_layout.addWidget(quality_group)

        # export deliverables
        export_group = QGroupBox("Output")
        export_layout = QVBoxLayout(export_group)
        export_layout.setSpacing(6)

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
        self.outdir_label = QLabel("Folder: ./outputs")
        self.outdir_label.setStyleSheet("color: #7f8a96; font-size: 11px; font-family: monospace;")
        self.outdir_label.setToolTip(str(self.output_dir))
        out_btn = QPushButton("Browse...")
        out_btn.setFixedHeight(24)
        out_btn.clicked.connect(self._browse_output_dir)
        out_row.addWidget(self.outdir_label, stretch=1)
        out_row.addWidget(out_btn)
        export_layout.addLayout(out_row)

        controls_layout.addWidget(export_group)

        # advanced engine tuning
        self.advanced_toggle_btn = QPushButton("▸ Advanced Settings")
        self.advanced_toggle_btn.setCheckable(True)
        self.advanced_toggle_btn.setChecked(False)
        self.advanced_toggle_btn.setStyleSheet(
            "QPushButton { background-color: #21252b; border: 1px solid #2e343d; border-radius: 4px; "
            "padding: 6px 10px; font-weight: 500; color: #88929e; text-align: left; } "
            "QPushButton:hover { background-color: #282d35; color: #dce1e7; } "
            "QPushButton:checked { background-color: #242930; border-color: #3b82f6; color: #ffffff; }"
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

        # GPU Device Selector
        gpu_row = QHBoxLayout()
        gpu_row.setContentsMargins(0, 2, 0, 2)
        gpu_label = QLabel("Compute GPU:")
        gpu_label.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: 500;")
        gpu_row.addWidget(gpu_label)

        self.gpu_combo = QComboBox()
        self.gpu_combo.setFixedHeight(26)
        self.gpu_combo.setStyleSheet(
            "QComboBox { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 2px 8px; font-size: 11px; } "
            "QComboBox:hover { border-color: #484f58; } "
            "QComboBox::drop-down { border: none; } "
            "QComboBox QAbstractItemView { background-color: #161b22; color: #c9d1d9; selection-background-color: #1f6feb; }"
        )
        for label, dev_id, is_compat, cuda_idx in self.gpu_options:
            self.gpu_combo.addItem(label, userData={"id": dev_id, "compat": is_compat, "cuda_idx": cuda_idx})
        self.gpu_combo.currentIndexChanged.connect(self._on_gpu_selection_changed)
        gpu_row.addWidget(self.gpu_combo, stretch=1)
        advanced_layout.addLayout(gpu_row)

        self.gpu_warning_label = QLabel("")
        self.gpu_warning_label.setStyleSheet("color: #f85149; font-size: 11px; padding: 0 4px 4px 4px;")
        self.gpu_warning_label.setVisible(False)
        advanced_layout.addWidget(self.gpu_warning_label)

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
        self.bright_slider.setRange(10, 250)
        self.bright_slider.setValue(100)
        self.bright_spin = QDoubleSpinBox()
        self.bright_spin.setRange(0.1, 2.5)
        self.bright_spin.setSingleStep(0.05)
        self.bright_spin.setValue(1.0)
        self._sync_float_slider(self.bright_slider, self.bright_spin, 100.0)
        color_layout.addWidget(self._create_slider_param_row("Brightness Multiplier:", self.bright_slider, self.bright_spin, ""))

        advanced_layout.addWidget(color_group)

        # hidden compatibility controls
        self.seed_spin = QSpinBox()
        self.seed_spin.setValue(0)
        self.hint_quality_spin = QDoubleSpinBox()
        self.hint_quality_spin.setValue(0.95)
        self.carry_quality_spin = QDoubleSpinBox()
        self.carry_quality_spin.setValue(0.95)
        self.contrast_pivot_spin = QDoubleSpinBox()
        self.contrast_pivot_spin.setValue(0.18)
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
        btn_layout.setContentsMargins(4, 4, 4, 0)
        btn_layout.setSpacing(6)
        self.start_btn = QPushButton("Start Keying")
        self.start_btn.setFixedHeight(34)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b5580;
                color: #ffffff;
                font-weight: 600;
                padding: 6px 14px;
                border: 1px solid #386ca3;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #336699;
                border-color: #4682c4;
            }
            QPushButton:pressed {
                background-color: #224466;
            }
            QPushButton:disabled {
                background-color: #1a1d21;
                color: #4e555e;
                border: 1px solid #282d34;
            }
        """)
        self.start_btn.clicked.connect(self._start_keying)
        btn_layout.addWidget(self.start_btn, stretch=3)

        self.add_queue_btn = QPushButton("+ Queue")
        self.add_queue_btn.setFixedHeight(34)
        self.add_queue_btn.setToolTip("Add current video and settings to Batch Queue")
        self.add_queue_btn.setStyleSheet("""
            QPushButton {
                background-color: #21252b;
                color: #b0bac5;
                font-weight: 600;
                padding: 6px 10px;
                border: 1px solid #333942;
                border-radius: 4px;
                font-size: 11.5px;
            }
            QPushButton:hover {
                background-color: #2c323a;
                border-color: #454d58;
                color: #ffffff;
            }
        """)
        self.add_queue_btn.clicked.connect(self._add_current_to_queue)
        btn_layout.addWidget(self.add_queue_btn, stretch=1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(34)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #261f21;
                color: #b88686;
                font-weight: 500;
                padding: 6px 12px;
                border: 1px solid #3d2a2d;
                border-radius: 4px;
                font-size: 11.5px;
            }
            QPushButton:hover {
                background-color: #352528;
                color: #e6a8a8;
                border-color: #52383c;
            }
            QPushButton:disabled {
                background-color: #18191b;
                color: #4e555e;
                border-color: #24282d;
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

        # view comparison toolbar (1:1 with CorridorKey Workbench 2.0)
        view_bar = QHBoxLayout()
        view_bar.setContentsMargins(0, 0, 0, 0)
        view_bar.setSpacing(6)

        lbl_mode = QLabel("Mode:")
        lbl_mode.setStyleSheet("font-size: 11px; font-weight: 600; color: #8b949e;")
        view_bar.addWidget(lbl_mode)

        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems([
            "Vertical Wipe",
            "Horizontal Wipe",
            "Difference Blend",
            "Overlay Crossfade",
            "Single View",
        ])
        self.view_mode_combo.currentIndexChanged.connect(self._on_comparison_mode_changed)
        view_bar.addWidget(self.view_mode_combo)

        lbl_buf_a = QLabel("A:")
        lbl_buf_a.setStyleSheet("font-size: 11.5px; font-weight: 700; color: #3b82f6;")
        view_bar.addWidget(lbl_buf_a)

        self.buf_a_combo = QComboBox()
        self.buf_a_combo.addItems([
            "Original Footage",
            "Cutout (RGBA)",
            "Alpha Matte",
            "Despilled RGB",
            "Checkerboard Composite",
        ])
        self.buf_a_combo.setCurrentIndex(0)
        self.buf_a_combo.currentIndexChanged.connect(self._on_buffer_a_changed)
        view_bar.addWidget(self.buf_a_combo)

        self.btn_swap_buffers = QPushButton("⇄")
        self.btn_swap_buffers.setToolTip("Swap Buffer A and Buffer B (Shortcut: X)")
        self.btn_swap_buffers.setFixedSize(26, 24)
        self.btn_swap_buffers.setStyleSheet(
            "QPushButton { background-color: #21252b; border: 1px solid #333942; border-radius: 4px; font-size: 13px; font-weight: bold; color: #b6c2cf; padding: 0px; } "
            "QPushButton:hover { background-color: #2c323a; color: #ffffff; border-color: #3b82f6; }"
        )
        self.btn_swap_buffers.clicked.connect(self._on_toggle_swap_buffers)
        view_bar.addWidget(self.btn_swap_buffers)

        lbl_buf_b = QLabel("B:")
        lbl_buf_b.setStyleSheet("font-size: 11.5px; font-weight: 700; color: #10b981;")
        view_bar.addWidget(lbl_buf_b)

        self.buf_b_combo = QComboBox()
        self.buf_b_combo.addItems([
            "Original Footage",
            "Cutout (RGBA)",
            "Alpha Matte",
            "Despilled RGB",
            "Checkerboard Composite",
        ])
        self.buf_b_combo.setCurrentIndex(1)
        self.buf_b_combo.currentIndexChanged.connect(self._on_buffer_b_changed)
        view_bar.addWidget(self.buf_b_combo)

        # overlay opacity slider (visible when Overlay Crossfade is chosen)
        self.overlay_slider_widget = QWidget()
        overlay_layout = QHBoxLayout(self.overlay_slider_widget)
        overlay_layout.setContentsMargins(4, 0, 0, 0)
        overlay_layout.setSpacing(4)
        lbl_op = QLabel("Opacity:")
        lbl_op.setStyleSheet("color: #7f8a96; font-size: 11px;")
        overlay_layout.addWidget(lbl_op)
        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(0, 100)
        self.overlay_opacity_slider.setValue(50)
        self.overlay_opacity_slider.setFixedWidth(70)
        self.overlay_opacity_slider.valueChanged.connect(lambda val: self.canvas.set_overlay_opacity(val / 100.0))
        overlay_layout.addWidget(self.overlay_opacity_slider)
        self.overlay_slider_widget.setVisible(False)
        view_bar.addWidget(self.overlay_slider_widget)

        # zoom presets
        view_bar.addSpacing(6)
        lbl_zoom = QLabel("Zoom:")
        lbl_zoom.setStyleSheet("font-size: 11px; font-weight: 600; color: #8b949e;")
        view_bar.addWidget(lbl_zoom)
        btn_zoom_fit = QPushButton("Fit")
        btn_zoom_fit.setFixedHeight(26)
        btn_zoom_fit.setMinimumWidth(38)
        btn_zoom_fit.clicked.connect(lambda: self.canvas.set_zoom_mode("fit"))
        view_bar.addWidget(btn_zoom_fit)

        btn_zoom_100 = QPushButton("100%")
        btn_zoom_100.setFixedHeight(26)
        btn_zoom_100.setMinimumWidth(46)
        btn_zoom_100.clicked.connect(lambda: self.canvas.set_zoom_mode("100%"))
        view_bar.addWidget(btn_zoom_100)

        btn_zoom_200 = QPushButton("200%")
        btn_zoom_200.setFixedHeight(26)
        btn_zoom_200.setMinimumWidth(46)
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
            "QFrame { background-color: #21252b; border: 1px solid #2e343d; border-radius: 5px; padding: 4px 8px; }"
        )
        pb_layout = QVBoxLayout(playback_frame)
        pb_layout.setContentsMargins(4, 3, 4, 3)
        pb_layout.setSpacing(4)

        # timeline scrubbing slider
        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setRange(0, 0)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.setFixedHeight(16)
        self.timeline_slider.sliderMoved.connect(self._on_timeline_scrubbed)
        self.timeline_slider.valueChanged.connect(self._on_timeline_scrubbed)
        pb_layout.addWidget(self.timeline_slider)

        # transport controls
        transport_layout = QHBoxLayout()
        transport_layout.setContentsMargins(0, 0, 0, 0)
        transport_layout.setSpacing(5)

        self.btn_step_prev = QPushButton("◀◀")
        self.btn_step_prev.setFixedSize(30, 24)
        self.btn_step_prev.setEnabled(False)
        self.btn_step_prev.clicked.connect(self._on_step_prev)
        transport_layout.addWidget(self.btn_step_prev)

        self.btn_play_pause = QPushButton("▶")
        self.btn_play_pause.setFixedSize(36, 24)
        self.btn_play_pause.setEnabled(False)
        self.btn_play_pause.setStyleSheet(
            "QPushButton { background-color: #2b3036; border: 1px solid #3c444f; color: #f0f6fc; font-weight: 600; font-size: 11.5px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #353c44; border-color: #4e5765; } "
            "QPushButton:disabled { background-color: #1a1d21; color: #4e555e; border-color: #24282d; }"
        )
        self.btn_play_pause.clicked.connect(self._on_toggle_play_pause)
        transport_layout.addWidget(self.btn_play_pause)

        self.btn_step_next = QPushButton("▶▶")
        self.btn_step_next.setFixedSize(30, 24)
        self.btn_step_next.setEnabled(False)
        self.btn_step_next.clicked.connect(self._on_step_next)
        transport_layout.addWidget(self.btn_step_next)

        self.btn_loop = QPushButton("Loop")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setChecked(True)
        self.btn_loop.setFixedSize(44, 24)
        self.btn_loop.setStyleSheet(
            "QPushButton { background-color: #1e2227; color: #88929e; border: 1px solid #333942; padding: 2px 6px; font-size: 11px; font-weight: 600; } "
            "QPushButton:checked { background-color: #2b3036; color: #f0f6fc; border-color: #3b82f6; }"
        )
        transport_layout.addWidget(self.btn_loop)

        self.timecode_label = QLabel("00:00.00 / 00:00.00 (0/0)")
        self.timecode_label.setStyleSheet("color: #7f8a96; font-family: monospace; font-size: 11px; font-weight: 500; margin-left: 6px;")
        transport_layout.addWidget(self.timecode_label)

        transport_layout.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #7f8a96; font-size: 11px;")
        transport_layout.addWidget(self.status_label)

        self.btn_toggle_log = QPushButton("Log")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setFixedSize(40, 24)
        self.btn_toggle_log.setStyleSheet(
            "QPushButton { background-color: #1e2227; color: #88929e; border: 1px solid #333942; font-size: 11px; font-weight: 600; } "
            "QPushButton:checked { background-color: #2b3036; color: #f0f6fc; border-color: #3b82f6; }"
        )
        self.btn_toggle_log.toggled.connect(self._on_toggle_log)
        transport_layout.addWidget(self.btn_toggle_log)

        pb_layout.addLayout(transport_layout)
        right_layout.addWidget(playback_frame)

        # batch render queue drawer
        self.queue_container = QWidget()
        self.queue_container.setVisible(False)
        self.queue_container.setStyleSheet(
            "QWidget#queueContainer { background-color: #21252b; border: 1px solid #2e343d; border-radius: 5px; }"
        )
        self.queue_container.setObjectName("queueContainer")
        qc_layout = QVBoxLayout(self.queue_container)
        qc_layout.setContentsMargins(8, 6, 8, 8)
        qc_layout.setSpacing(6)

        q_hdr = QHBoxLayout()
        q_hdr.setSpacing(8)
        lbl_q_title = QLabel("Batch Render Queue")
        lbl_q_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #f0f6fc;")
        q_hdr.addWidget(lbl_q_title)

        self.lbl_queue_count = QLabel("0 items")
        self.lbl_queue_count.setStyleSheet("color: #7f8a96; font-size: 11px;")
        q_hdr.addWidget(self.lbl_queue_count)

        q_hdr.addStretch()

        btn_q_add = QPushButton("+ Add Videos...")
        btn_q_add.setFixedHeight(24)
        btn_q_add.clicked.connect(self._browse_add_queue_files)
        q_hdr.addWidget(btn_q_add)

        btn_q_remove = QPushButton("Remove")
        btn_q_remove.setFixedHeight(24)
        btn_q_remove.clicked.connect(self._remove_selected_queue_item)
        q_hdr.addWidget(btn_q_remove)

        btn_q_clear = QPushButton("Clear")
        btn_q_clear.setFixedHeight(24)
        btn_q_clear.clicked.connect(self._clear_queue)
        q_hdr.addWidget(btn_q_clear)

        self.btn_q_render = QPushButton("Render Queue")
        self.btn_q_render.setFixedHeight(24)
        self.btn_q_render.setStyleSheet(
            "QPushButton { background-color: #2b5580; color: #ffffff; font-weight: 600; padding: 2px 10px; border: 1px solid #386ca3; border-radius: 4px; font-size: 11px; } "
            "QPushButton:hover { background-color: #336699; } "
            "QPushButton:disabled { background-color: #1a1d21; color: #4e555e; border-color: #282d34; }"
        )
        self.btn_q_render.clicked.connect(self._start_batch_queue)
        q_hdr.addWidget(self.btn_q_render)

        qc_layout.addLayout(q_hdr)

        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setHorizontalHeaderLabels(["Input File", "Resolution", "Frames", "Format", "Status"])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setFixedHeight(120)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setStyleSheet("""
            QTableWidget {
                background-color: #171a1e;
                border: 1px solid #2e343d;
                border-radius: 4px;
                color: #e6eaef;
                font-size: 11px;
                gridline-color: transparent;
            }
            QTableWidget::item {
                padding: 3px 6px;
                border-bottom: 1px solid #21252b;
            }
            QTableWidget::item:selected {
                background-color: #244166;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #1f2329;
                color: #8b949e;
                font-size: 11px;
                font-weight: 600;
                padding: 4px;
                border: none;
                border-bottom: 1px solid #2e343d;
            }
        """)
        self.queue_table.cellDoubleClicked.connect(self._on_queue_table_double_clicked)
        qc_layout.addWidget(self.queue_table)

        right_layout.addWidget(self.queue_container)

        # inline progress bar (visible only during render)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background-color: #171a1e; border: 1px solid #2e343d; border-radius: 3px; }
            QProgressBar::chunk { background-color: #3b82f6; border-radius: 2px; }
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
        self.log_text.setFixedHeight(85)
        self.log_text.setStyleSheet(
            "background-color: #171a1e; color: #88929e; font-family: monospace; font-size: 10.5px; "
            "border: 1px solid #2e343d; border-radius: 4px;"
        )
        lc_layout.addWidget(self.log_text)
        right_layout.addWidget(self.log_container)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([350, 830])

        main_layout.addWidget(splitter, stretch=1)

        self.setAcceptDrops(True)

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
        if hasattr(self, "screen_color_combo"):
            self.screen_color_combo.setCurrentIndex(0)
        if hasattr(self, "keep_solid_check"):
            self.keep_solid_check.setChecked(False)
            self.solid_erode_spin.setValue(4)
            self.solid_blur_spin.setValue(4)
        if hasattr(self, "despeckle_check"):
            self.despeckle_check.setChecked(False)
            self.despeckle_thresh_spin.setValue(250)
            self.despeckle_dil_spin.setValue(4)
            self.despeckle_blur_spin.setValue(4)
        if hasattr(self, "hint_quality_spin"):
            self.hint_quality_spin.setValue(0.75)
        if hasattr(self, "carry_quality_spin"):
            self.carry_quality_spin.setValue(0.95)
        if hasattr(self, "carry_hint_check"):
            self.carry_hint_check.setChecked(True)
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
        if "screen_color" in data and hasattr(self, "screen_color_combo"):
            sc = data["screen_color"]
            if isinstance(sc, int):
                self.screen_color_combo.setCurrentIndex(max(0, min(2, sc)))
            elif str(sc).lower() in ("auto", "0"):
                self.screen_color_combo.setCurrentIndex(0)
            elif str(sc).lower() in ("green", "1"):
                self.screen_color_combo.setCurrentIndex(1)
            elif str(sc).lower() in ("blue", "2"):
                self.screen_color_combo.setCurrentIndex(2)
        if "keep_solid" in data and hasattr(self, "keep_solid_check"):
            self.keep_solid_check.setChecked(bool(data["keep_solid"]))
        if "solid_erode_px" in data and hasattr(self, "solid_erode_spin"):
            self.solid_erode_spin.setValue(int(data["solid_erode_px"]))
        if "solid_blur_px" in data and hasattr(self, "solid_blur_spin"):
            self.solid_blur_spin.setValue(int(data["solid_blur_px"]))
        if "despeckle" in data and hasattr(self, "despeckle_check"):
            self.despeckle_check.setChecked(bool(data["despeckle"]))
        if "despeckle_threshold" in data and hasattr(self, "despeckle_thresh_spin"):
            self.despeckle_thresh_spin.setValue(int(data["despeckle_threshold"]))
        if "despeckle_dilation" in data and hasattr(self, "despeckle_dil_spin"):
            self.despeckle_dil_spin.setValue(int(data["despeckle_dilation"]))
        if "despeckle_blur" in data and hasattr(self, "despeckle_blur_spin"):
            self.despeckle_blur_spin.setValue(int(data["despeckle_blur"]))
        if "hint_quality" in data and hasattr(self, "hint_quality_spin"):
            self.hint_quality_spin.setValue(float(data["hint_quality"]))
        if "carry_quality" in data and hasattr(self, "carry_quality_spin"):
            self.carry_quality_spin.setValue(float(data["carry_quality"]))
        if "carry_hint" in data and hasattr(self, "carry_hint_check"):
            self.carry_hint_check.setChecked(bool(data["carry_hint"]))
        if "contrast" in data:
            self.contrast_spin.setValue(float(data["contrast"]))
        if "bright" in data:
            val = float(data["bright"])
            self.bright_spin.setValue(1.0 if val <= 0.05 else val)
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
        if "selected_gpu" in data:
            target_id = str(data["selected_gpu"])
            for i in range(self.gpu_combo.count()):
                d = self.gpu_combo.itemData(i) or {}
                if d.get("id") == target_id:
                    self.gpu_combo.setCurrentIndex(i)
                    break
        if "output_dir" in data:
            self.output_dir = Path(data["output_dir"]).resolve()
            self.outdir_label.setText(f"Folder: {self.output_dir.name}")
            self.outdir_label.setToolTip(str(self.output_dir))

        self._update_vram_budget()

    def _get_current_settings_dict(self) -> dict:
        gpu_id = "auto"
        if hasattr(self, "gpu_combo") and self.gpu_combo.currentData():
            gpu_id = self.gpu_combo.currentData().get("id", "auto")
        return {
            "selected_gpu": gpu_id,
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
            "screen_color": self.screen_color_combo.currentIndex() if hasattr(self, "screen_color_combo") else 0,
            "keep_solid": self.keep_solid_check.isChecked() if hasattr(self, "keep_solid_check") else False,
            "solid_erode_px": self.solid_erode_spin.value() if hasattr(self, "solid_erode_spin") else 4,
            "solid_blur_px": self.solid_blur_spin.value() if hasattr(self, "solid_blur_spin") else 4,
            "despeckle": self.despeckle_check.isChecked() if hasattr(self, "despeckle_check") else False,
            "despeckle_threshold": self.despeckle_thresh_spin.value() if hasattr(self, "despeckle_thresh_spin") else 250,
            "despeckle_dilation": self.despeckle_dil_spin.value() if hasattr(self, "despeckle_dil_spin") else 4,
            "despeckle_blur": self.despeckle_blur_spin.value() if hasattr(self, "despeckle_blur_spin") else 4,
            "hint_quality": round(self.hint_quality_spin.value(), 2) if hasattr(self, "hint_quality_spin") else 0.75,
            "carry_quality": round(self.carry_quality_spin.value(), 2) if hasattr(self, "carry_quality_spin") else 0.95,
            "carry_hint": self.carry_hint_check.isChecked() if hasattr(self, "carry_hint_check") else True,
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
        dlg = SettingsDialog(self, self.gpu_profile, self.app_root, current_data, system_gpus=self.system_gpus)
        dlg.settings_applied.connect(self._apply_settings_dict)
        dlg.exec()

    def _open_patchnotes_dialog(self, since_version: str | None = None):
        from .patchnotes_dialog import PatchNotesDialog, get_installed_version
        current_version = get_installed_version(self.app_root)
        dlg = PatchNotesDialog(self, self.app_root, since_version=since_version, current_version=current_version)
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            dlg.show()
        else:
            dlg.exec()
        saved = load_settings()
        if saved.get("last_seen_version") != current_version:
            saved["last_seen_version"] = current_version
            save_settings(saved)

    def _check_patchnotes_on_launch(self):
        from .patchnotes_dialog import get_installed_version, parse_semver
        saved = load_settings()
        last_seen = saved.get("last_seen_version")
        current_version = get_installed_version(self.app_root)
        if last_seen is None or parse_semver(last_seen) < parse_semver(current_version):
            # open catchup dialog after UI initializes
            QTimer.singleShot(400, lambda: self._open_patchnotes_dialog(since_version=last_seen))


    def _on_toggle_advanced(self, checked: bool):
        self.advanced_container.setVisible(checked)
        self.advanced_toggle_btn.setText("▾ Advanced Settings" if checked else "▸ Advanced Settings")

    def _on_toggle_log(self, checked: bool):
        self.log_container.setVisible(checked)

    def _on_gpu_selection_changed(self, index: int):
        data = self.gpu_combo.currentData()
        if not data:
            return
        is_compat = data.get("compat", True)
        dev_id = data.get("id", "auto")
        cuda_idx = data.get("cuda_idx")

        if not is_compat:
            self.gpu_warning_label.setText("Selected adapter does not support CUDA. Inference requires NVIDIA GPU.")
            self.gpu_warning_label.setVisible(True)
            self.gpu_badge.setText("GPU Incompatible")
            self.gpu_badge.setToolTip("Selected display adapter lacks CUDA support. Neural network inference will fail.")
            self.gpu_badge.setStyleSheet(
                "background-color: #3b181a; border: 1px solid #da3633; border-radius: 4px; "
                "padding: 3px 10px; color: #f85149; font-size: 11px; font-weight: 600;"
            )
        else:
            self.gpu_warning_label.setVisible(False)
            profile = detect_gpu_profile(cuda_index=cuda_idx)
            self.gpu_profile = profile
            is_hybrid = dev_id == "auto" and any(d.is_integrated for d in self.system_gpus)
            tier_badge = "Hybrid" if is_hybrid else profile.short_name
            self.gpu_badge.setText(f"{profile.short_name} ({profile.total_vram_gb:.1f} GB) | {tier_badge}")
            self.gpu_badge.setToolTip(f"GPU: {profile.name}\nTier: {profile.tier_name}\nVRAM: {profile.total_vram_gb:.1f} GB")
            self.gpu_badge.setStyleSheet(
                "background-color: #21252b; border: 1px solid #2e343d; border-radius: 4px; "
                "padding: 3px 10px; color: #b0bac5; font-size: 11px; font-weight: 600;"
            )
            self._update_vram_budget()

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
            if hasattr(self, "keep_solid_check"):
                self.keep_solid_check.setChecked(True)
                self.solid_erode_spin.setValue(4)
                self.solid_blur_spin.setValue(4)
            if hasattr(self, "despeckle_check"):
                self.despeckle_check.setChecked(True)
                self.despeckle_thresh_spin.setValue(250)
        elif index == 2:  # High-Performance Workstation (24GB+ / Multi-Batch)
            if hasattr(self, "keep_solid_check"):
                self.keep_solid_check.setChecked(False)
            if hasattr(self, "despeckle_check"):
                self.despeckle_check.setChecked(False)
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
            if hasattr(self, "keep_solid_check"):
                self.keep_solid_check.setChecked(False)
            if hasattr(self, "despeckle_check"):
                self.despeckle_check.setChecked(False)
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
            if hasattr(self, "keep_solid_check"):
                self.keep_solid_check.setChecked(False)
            if hasattr(self, "despeckle_check"):
                self.despeckle_check.setChecked(False)
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

        short_gpu = self.gpu_profile.short_name
        vram_text = f"{avail:.1f} GB" if self.gpu_profile.is_cuda_available else "N/A"
        if self.gpu_profile.is_cuda_available and self.selected_input is not None:
            self.gpu_badge.setText(f"{short_gpu} ({vram_text}) · Fits in VRAM: ~{peak_est:.1f} GB")
        else:
            self.gpu_badge.setText(f"{short_gpu} ({vram_text})")

        if self.selected_input is not None and not is_safe and not self.low_vram_check.isChecked():
            self.vram_warning.setText(f"Warning: High VRAM load (~{peak_est:.1f} GB / {avail:.1f} GB). Low-VRAM mode recommended.")
            self.vram_warning.setVisible(True)
        else:
            self.vram_warning.setVisible(False)

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
            paths = [u.toLocalFile() for u in urls if u.toLocalFile()]
            if len(paths) == 1:
                self._set_input_path(paths[0])
            elif len(paths) > 1:
                for p in paths:
                    self._add_to_queue(p)
                self._set_input_path(paths[0])
                self._on_toggle_queue_drawer(True)

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
        self.chip_footage.setText(f"{self.clip_width}x{self.clip_height} · {self.clip_fps:.2f} fps · {dur_sec}s ({self.clip_frames}f)")
        self.chip_footage.setStyleSheet(
            "background-color: #1e2630; border: 1px solid #314a6d; border-radius: 4px; "
            "padding: 3px 8px; color: #d0dbe6; font-size: 11px; font-weight: 600;"
        )

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
            f"{cur_str} / {tot_str} ({self.current_frame_idx + 1}/{self.clip_frames})"
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
        if hasattr(self, "hint_controls_widget"):
            self.hint_controls_widget.setVisible(has_hint)
        if index == 1:
            self.hint_btn.setText("Select First-Frame Mask...")
        elif index == 2:
            self.hint_btn.setText("Select Mask Video...")

    def _on_view_mode_changed(self, index: int):
        modes = ["split_v", "checker", "alpha", "fg", "original"]
        if 0 <= index < len(modes):
            self.canvas.set_view_mode(modes[index])

    def _on_comparison_mode_changed(self, index: int):
        modes = ["split_v", "split_h", "difference", "overlay", "single"]
        mode = modes[index] if 0 <= index < len(modes) else "split_v"
        self.canvas.set_view_mode(mode)
        if hasattr(self, "overlay_slider_widget"):
            self.overlay_slider_widget.setVisible(mode == "overlay")

    def _on_buffer_a_changed(self, index: int):
        if 0 <= index < len(self.BUFFER_NAMES):
            self.canvas.set_buffer_a(self.BUFFER_NAMES[index])

    def _on_buffer_b_changed(self, index: int):
        if 0 <= index < len(self.BUFFER_NAMES):
            self.canvas.set_buffer_b(self.BUFFER_NAMES[index])

    def _on_toggle_swap_buffers(self):
        self.canvas.toggle_swap()
        is_swapped = self.canvas.is_swapped()
        self.btn_swap_buffers.setStyleSheet(
            "QPushButton { background-color: #2b5580; border: 1px solid #3b82f6; border-radius: 4px; font-size: 13px; font-weight: bold; color: #ffffff; padding: 0px; }"
            if is_swapped else
            "QPushButton { background-color: #21252b; border: 1px solid #333942; border-radius: 4px; font-size: 13px; font-weight: bold; color: #b6c2cf; padding: 0px; } "
            "QPushButton:hover { background-color: #2c323a; color: #ffffff; border-color: #3b82f6; }"
        )
        self.status_label.setText("Buffer A ⇄ B Swapped" if is_swapped else "Buffer A ⇄ B Normal")

    def _on_toggle_keep_solid(self, checked: bool):
        if hasattr(self, "solid_options_widget"):
            self.solid_options_widget.setVisible(checked)

    def _on_toggle_despeckle(self, checked: bool):
        if hasattr(self, "despeckle_options_widget"):
            self.despeckle_options_widget.setVisible(checked)

    def _set_current_as_ref_frame(self):
        if hasattr(self, "ref_frame_spin"):
            self.ref_frame_spin.setValue(self.current_frame_idx)
            self.status_label.setText(f"Reference frame set to frame {self.current_frame_idx}")

    def _on_toggle_queue_drawer(self, checked: bool | None = None):
        if checked is None or isinstance(checked, int):
            new_state = not self.queue_container.isVisible()
        else:
            new_state = bool(checked)
        self.queue_container.setVisible(new_state)
        self.btn_queue_toggle.setChecked(new_state)

    def _add_to_queue(self, file_path: str):
        p = Path(file_path)
        if not p.is_file():
            return
        cap = cv2.VideoCapture(str(p))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        cap.release()

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
        chosen_fmt = formats[self.deliverable_combo.currentIndex()]

        item = {
            "path": str(p),
            "name": p.name,
            "res": f"{w}x{h}" if w and h else "Unknown",
            "frames": frames,
            "format": chosen_fmt,
            "status": "Ready",
        }
        self.queue_items.append(item)

        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        self.queue_table.setItem(row, 0, QTableWidgetItem(p.name))
        self.queue_table.setItem(row, 1, QTableWidgetItem(item["res"]))
        self.queue_table.setItem(row, 2, QTableWidgetItem(str(frames)))
        self.queue_table.setItem(row, 3, QTableWidgetItem(self.deliverable_combo.currentText().split()[0]))
        st_item = QTableWidgetItem("Ready")
        st_item.setForeground(QColor("#7f8a96"))
        self.queue_table.setItem(row, 4, st_item)

        count = len(self.queue_items)
        self.lbl_queue_count.setText(f"{count} items")
        self.btn_queue_toggle.setText(f"Batch Queue ({count})")

    def _add_current_to_queue(self):
        if not self.selected_input or not Path(self.selected_input).exists():
            QMessageBox.warning(self, "No Video Loaded", "Please select an input video first.")
            return
        self._add_to_queue(self.selected_input)
        self._on_toggle_queue_drawer(True)

    def _browse_add_queue_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Video Files to Queue", "",
            "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)"
        )
        if files:
            for f in files:
                self._add_to_queue(f)
            self._on_toggle_queue_drawer(True)

    def _remove_selected_queue_item(self):
        if self._is_processing_queue:
            return
        row = self.queue_table.currentRow()
        if 0 <= row < len(self.queue_items):
            self.queue_items.pop(row)
            self.queue_table.removeRow(row)
            count = len(self.queue_items)
            self.lbl_queue_count.setText(f"{count} items")
            self.btn_queue_toggle.setText(f"Batch Queue ({count})")

    def _clear_queue(self):
        if self._is_processing_queue:
            return
        self.queue_items.clear()
        self.queue_table.setRowCount(0)
        self.lbl_queue_count.setText("0 items")
        self.btn_queue_toggle.setText("Batch Queue (0)")

    def _on_queue_table_double_clicked(self, row: int, col: int):
        if 0 <= row < len(self.queue_items):
            self._set_input_path(self.queue_items[row]["path"])

    def _start_batch_queue(self):
        if not self.queue_items:
            QMessageBox.information(self, "Queue Empty", "No video files in the batch queue.")
            return

        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Busy", "Inference is already running.")
            return

        first_ready = next((i for i, it in enumerate(self.queue_items) if it["status"] == "Ready"), None)
        if first_ready is None:
            for i, it in enumerate(self.queue_items):
                it["status"] = "Ready"
                st = self.queue_table.item(i, 4)
                if st:
                    st.setText("Ready")
                    st.setForeground(QColor("#7f8a96"))
            first_ready = 0

        self._is_processing_queue = True
        self._queue_current_idx = first_ready
        self.btn_q_render.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._process_queue_item(first_ready)

    def _process_queue_item(self, idx: int):
        item = self.queue_items[idx]
        item["status"] = "Processing"
        st = self.queue_table.item(idx, 4)
        if st:
            st.setText("Processing")
            st.setForeground(QColor("#3b82f6"))

        self.selected_input = item["path"]
        self._set_input_path(item["path"])

        total_q = len(self.queue_items)
        self.status_label.setText(f"Queue [{idx + 1}/{total_q}]: Processing {item['name']}...")
        self.log_text.append(f"\n--- Batch Queue [{idx + 1}/{total_q}]: {item['name']} ---")

        self._launch_worker_for_path(item["path"], item.get("format", "prores4444"))

    def _launch_worker_for_path(self, input_path: str, chosen_format: str):
        gpu_data = self.gpu_combo.currentData() or {}
        cuda_idx = gpu_data.get("cuda_idx")

        color_map = {0: "auto", 1: "green", 2: "blue"}
        chosen_color = color_map.get(self.screen_color_combo.currentIndex() if hasattr(self, "screen_color_combo") else 0, "auto")

        repo_root = Path(__file__).resolve().parents[1]
        self.worker = KeyerEngineWorker(
            repo_root=repo_root,
            input_path=input_path,
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
            carry_hint=self.carry_hint_check.isChecked() if hasattr(self, "carry_hint_check") else True,
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
            cuda_device_index=cuda_idx,
            screen_color=chosen_color,
            keep_solid=self.keep_solid_check.isChecked() if hasattr(self, "keep_solid_check") else False,
            solid_erode_px=self.solid_erode_spin.value() if hasattr(self, "solid_erode_spin") else 4,
            solid_blur_px=self.solid_blur_spin.value() if hasattr(self, "solid_blur_spin") else 4,
            despeckle=self.despeckle_check.isChecked() if hasattr(self, "despeckle_check") else False,
            despeckle_threshold=self.despeckle_thresh_spin.value() if hasattr(self, "despeckle_thresh_spin") else 250,
            despeckle_dilation=self.despeckle_dil_spin.value() if hasattr(self, "despeckle_dil_spin") else 4,
            despeckle_blur=self.despeckle_blur_spin.value() if hasattr(self, "despeckle_blur_spin") else 4,
        )

        self.worker.progress_update.connect(self._on_progress)
        self.worker.log_output.connect(self._on_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

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

        gpu_data = self.gpu_combo.currentData() or {}
        is_compat = gpu_data.get("compat", True)
        dev_id = gpu_data.get("id", "auto")

        if not is_compat:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("Incompatible GPU Selected")
            box.setText(
                "The selected display adapter cannot execute CorridorKey v2 neural network inference.\n\n"
                f"Selected: {self.gpu_combo.currentText()}\n\n"
                "Reason: Neural network inference requires a CUDA-capable NVIDIA GPU.\n\n"
                "Please switch the GPU selector in Advanced Settings to 'Auto (Hybrid Offload)' or select a compatible NVIDIA GPU."
            )
            box.setStyleSheet(
                "QMessageBox { background-color: #1a1d21; color: #dce1e7; } "
                "QPushButton { background-color: #21252b; color: #dce1e7; border: 1px solid #333942; padding: 6px 14px; border-radius: 4px; } "
                "QPushButton:hover { background-color: #282d35; }"
            )
            box.exec()
            return

        if dev_id == "auto" and not any(d.is_cuda for d in self.system_gpus):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("No CUDA GPU Available")
            box.setText(
                "No CUDA-capable NVIDIA GPU was detected on this system.\n\n"
                "CorridorKey v2 requires an NVIDIA GPU with CUDA support and at least 4 GB VRAM to run."
            )
            box.setStyleSheet(
                "QMessageBox { background-color: #1a1d21; color: #dce1e7; } "
                "QPushButton { background-color: #21252b; color: #dce1e7; border: 1px solid #333942; padding: 6px 14px; border-radius: 4px; } "
                "QPushButton:hover { background-color: #282d35; }"
            )
            box.exec()
            return

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting CorridorKey inference...")
        self.log_text.clear()

        if not self.btn_toggle_log.isChecked():
            self.btn_toggle_log.setChecked(True)
        self.log_container.setVisible(True)
        self.log_text.append(f"Starting inference on: {Path(self.selected_input).name}")
        self.log_text.append(f"Output directory: {self.output_dir}")

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
        self._launch_worker_for_path(self.selected_input, chosen_format)

    def _cancel_keying(self):
        if self._is_processing_queue:
            self._is_processing_queue = False
            self.btn_q_render.setEnabled(True)
            if 0 <= self._queue_current_idx < len(self.queue_items):
                self.queue_items[self._queue_current_idx]["status"] = "Cancelled"
                st = self.queue_table.item(self._queue_current_idx, 4)
                if st:
                    st.setText("Cancelled")
                    st.setForeground(QColor("#e5b642"))

        if self.worker and self.worker.isRunning():
            self.status_label.setText("Cancelling inference...")
            self.cancel_btn.setEnabled(False)
            self._on_log("Cancelling inference process...")
            self.worker.cancel()
        elif self.worker:
            self.worker.cancel()
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.status_label.setText("Ready")

    @Slot(int, str)
    def _on_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    @Slot(str)
    def _on_log(self, text: str):
        self.log_text.append(text)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    @Slot(bool, str, dict)
    def _on_finished(self, success: bool, message: str, outputs: dict):
        if self._is_processing_queue and 0 <= self._queue_current_idx < len(self.queue_items):
            cur_item = self.queue_items[self._queue_current_idx]
            cur_item["status"] = "Done" if success else "Error"
            st = self.queue_table.item(self._queue_current_idx, 4)
            if st:
                st.setText("Done" if success else "Error")
                st.setForeground(QColor("#10b981" if success else "#ef4444"))

            next_idx = None
            for i in range(self._queue_current_idx + 1, len(self.queue_items)):
                if self.queue_items[i]["status"] == "Ready":
                    next_idx = i
                    break

            if next_idx is not None:
                self._queue_current_idx = next_idx
                self._process_queue_item(next_idx)
                return
            else:
                self._is_processing_queue = False
                self.btn_q_render.setEnabled(True)
                self.start_btn.setEnabled(True)
                self.cancel_btn.setEnabled(False)
                self.progress_bar.setVisible(False)
                self.status_label.setText("Batch queue rendering complete.")
                QMessageBox.information(
                    self, "Batch Queue Complete",
                    f"Finished processing {len(self.queue_items)} queued clips."
                )
                return

        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)

        if success:
            if self.selected_input:
                self._try_load_existing_results(Path(self.selected_input).stem, None)
                self._display_frame_at(self.current_frame_idx)

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
                "QMessageBox { background-color: #1a1d21; color: #dce1e7; } "
                "QPushButton { background-color: #21252b; color: #dce1e7; border: 1px solid #333942; padding: 6px 14px; border-radius: 4px; } "
                "QPushButton:hover { background-color: #282d35; }"
            )
            box.exec()
            if box.clickedButton() == open_folder_btn:
                self._open_output_dir()
        elif "cancel" in message.lower():
            self.status_label.setText("Keying cancelled.")
            self._on_log("Keying process was cancelled by user.")
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
            self.update_label.setText("Update installed. Restarting...")
            self.btn_update_now.setText("Restarting...")
            self.btn_update_now.setEnabled(True)
            try:
                self.btn_update_now.clicked.disconnect()
            except Exception:
                pass
            self.btn_update_now.clicked.connect(self._restart_app)
            self.btn_update_dismiss.setText("Later")
            self.btn_update_dismiss.setEnabled(True)
            QTimer.singleShot(1500, self._restart_app)
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
