from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import cv2

from PySide6.QtCore import Qt, QUrl, Slot, QTimer, QPointF
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QImage, QPixmap, QKeySequence, QShortcut
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Corridorkey Studio")
        self.resize(1360, 920)
        self.setMinimumSize(1020, 680)

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
        self._check_for_updates()

    def _setup_theme(self):
        # oled black theme with subtle dark slate borders
        self.setStyleSheet("""
            QMainWindow, QWidget#centralWidget {
                background-color: #000000;
                color: #dcdcdc;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #000000;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #222222;
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #333333;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QGroupBox {
                background-color: #070707;
                border: 1px solid #1a1a1a;
                border-radius: 4px;
                margin-top: 14px;
                padding: 12px 10px 10px 10px;
                font-weight: 600;
                font-size: 11px;
                color: #888888;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
                left: 8px;
                color: #777777;
            }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #0e0e0e;
                border: 1px solid #222222;
                border-radius: 3px;
                padding: 5px 8px;
                color: #e2e2e2;
                font-size: 11px;
            }
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
                border-color: #333333;
            }
            QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
                border-color: #484848;
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QCheckBox {
                color: #cccccc;
                font-size: 11px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                background-color: #0d0d0d;
                border: 1px solid #282828;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #2b2b2b;
                border-color: #555555;
            }
            QPushButton {
                background-color: #141414;
                color: #d6d6d6;
                border: 1px solid #242424;
                border-radius: 3px;
                padding: 5px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #202020;
                border-color: #3a3a3a;
                color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #111111;
            }
            QPushButton:disabled {
                background-color: #080808;
                color: #3a3a3a;
                border-color: #121212;
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

        title_label = QLabel("Corridorkey Studio")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f2f2f2; letter-spacing: 0.5px;")
        header_bar.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # footage metadata chips
        self.chip_res = QLabel("No Footage Loaded")
        self.chip_res.setStyleSheet(
            "background-color: #0a0a0a; border: 1px solid #1a1a1a; border-radius: 3px; "
            "padding: 3px 8px; color: #777777; font-size: 10px; font-weight: 500;"
        )
        header_bar.addWidget(self.chip_res, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.chip_fps = QLabel("")
        self.chip_fps.setVisible(False)
        self.chip_fps.setStyleSheet(
            "background-color: #0a0a0a; border: 1px solid #1a1a1a; border-radius: 3px; "
            "padding: 3px 8px; color: #777777; font-size: 10px; font-weight: 500;"
        )
        header_bar.addWidget(self.chip_fps, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.chip_duration = QLabel("")
        self.chip_duration.setVisible(False)
        self.chip_duration.setStyleSheet(
            "background-color: #0a0a0a; border: 1px solid #1a1a1a; border-radius: 3px; "
            "padding: 3px 8px; color: #777777; font-size: 10px; font-weight: 500;"
        )
        header_bar.addWidget(self.chip_duration, alignment=Qt.AlignmentFlag.AlignVCenter)

        header_bar.addStretch()

        vram_text = f"{self.gpu_profile.total_vram_gb} GB" if self.gpu_profile.is_cuda_available else "N/A"
        self.gpu_badge = QLabel(f"GPU: {self.gpu_profile.name} ({vram_text})")
        self.gpu_badge.setStyleSheet(
            "background-color: #0a0a0a; border: 1px solid #1e1e1e; border-radius: 4px; "
            "padding: 4px 10px; color: #888888; font-size: 11px;"
        )
        header_bar.addWidget(self.gpu_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.open_output_btn = QPushButton("Open Outputs Folder")
        self.open_output_btn.setFixedHeight(26)
        self.open_output_btn.setStyleSheet(
            "QPushButton { background-color: #121212; color: #bbbbbb; border: 1px solid #222222; "
            "padding: 2px 10px; border-radius: 3px; font-size: 11px; } "
            "QPushButton:hover { background-color: #1c1c1c; border-color: #383838; color: #ffffff; }"
        )
        self.open_output_btn.clicked.connect(self._open_output_dir)
        header_bar.addWidget(self.open_output_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        header_widget = QWidget()
        header_widget.setLayout(header_bar)
        header_widget.setFixedHeight(32)
        main_layout.addWidget(header_widget)

        # update notification banner
        self.update_banner = QFrame()
        self.update_banner.setVisible(False)
        self.update_banner.setStyleSheet(
            "QFrame { background-color: #0c0c0c; border: 1px solid #282828; border-radius: 4px; padding: 3px 8px; }"
        )
        ub_layout = QHBoxLayout(self.update_banner)
        ub_layout.setContentsMargins(6, 2, 6, 2)
        ub_layout.setSpacing(10)

        self.update_label = QLabel("Update Available")
        self.update_label.setStyleSheet("color: #dcdcdc; font-size: 11px;")
        ub_layout.addWidget(self.update_label)

        ub_layout.addStretch()

        self.btn_update_now = QPushButton("Update Now")
        self.btn_update_now.setFixedHeight(22)
        self.btn_update_now.setStyleSheet(
            "QPushButton { background-color: #1b3d26; color: #9be9a8; border: 1px solid #2d6b41; padding: 2px 8px; font-size: 10px; } "
            "QPushButton:hover { background-color: #234f31; }"
        )
        self.btn_update_now.clicked.connect(self._on_click_update_now)
        ub_layout.addWidget(self.btn_update_now)

        self.btn_update_dismiss = QPushButton("Dismiss")
        self.btn_update_dismiss.setFixedHeight(22)
        self.btn_update_dismiss.setStyleSheet(
            "QPushButton { background-color: #141414; color: #777777; border: 1px solid #1e1e1e; padding: 2px 8px; font-size: 10px; } "
            "QPushButton:hover { color: #aaaaaa; border-color: #333333; }"
        )
        self.btn_update_dismiss.clicked.connect(lambda: self.update_banner.setVisible(False))
        ub_layout.addWidget(self.btn_update_dismiss)
        main_layout.addWidget(self.update_banner)

        # 2. main body splitter (Left: Settings | Right: Viewer)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #111111; width: 2px; }")

        # left scrollable panel
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedWidth(380)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 10, 0)
        controls_layout.setSpacing(10)

        # footage input box
        input_group = QGroupBox("Footage Input")
        input_layout = QVBoxLayout(input_group)
        self.drop_area = QPushButton("Drop Video File or Browse...")
        self.drop_area.setFixedHeight(38)
        self.drop_area.setStyleSheet(
            "QPushButton { border: 1px dashed #282828; border-radius: 4px; "
            "background-color: #080808; color: #777777; font-size: 11px; } "
            "QPushButton:hover { border-color: #444444; background-color: #0e0e0e; color: #b0b0b0; }"
        )
        self.drop_area.clicked.connect(self._browse_input)
        input_layout.addWidget(self.drop_area)

        self.input_label = QLabel("No file selected")
        self.input_label.setStyleSheet("color: #666666; font-size: 10px;")
        self.input_label.setWordWrap(True)
        input_layout.addWidget(self.input_label)

        self.companion_hint_label = QLabel("")
        self.companion_hint_label.setVisible(False)
        self.companion_hint_label.setStyleSheet("color: #3dd68c; font-size: 10px; font-weight: 500;")
        self.companion_hint_label.setWordWrap(True)
        input_layout.addWidget(self.companion_hint_label)

        controls_layout.addWidget(input_group)

        # live resource budget banner
        self.vram_banner = QFrame()
        self.vram_banner.setStyleSheet(
            "background-color: #080808; border-left: 3px solid #2e2e2e; border-radius: 3px; padding: 6px 10px;"
        )
        vram_box = QVBoxLayout(self.vram_banner)
        vram_box.setContentsMargins(0, 0, 0, 0)
        vram_box.setSpacing(2)
        self.vram_title = QLabel("VRAM Budget: Normal (~1.6 GB estimated)")
        self.vram_title.setStyleSheet("font-weight: 600; color: #888888; font-size: 11px;")
        self.vram_detail = QLabel("Peak memory usage within hardware budget.")
        self.vram_detail.setStyleSheet("color: #666666; font-size: 10px;")
        self.vram_detail.setWordWrap(True)
        vram_box.addWidget(self.vram_title)
        vram_box.addWidget(self.vram_detail)
        controls_layout.addWidget(self.vram_banner)

        # workflow presets
        preset_group = QGroupBox("Workflow Preset")
        preset_layout = QVBoxLayout(preset_group)
        self.workflow_combo = QComboBox()
        self.workflow_combo.addItems([
            "Balanced Studio (Hardware Optimized)",
            "Maximum Quality (Fine Hair & Edges)",
            "High-Performance Workstation (24GB+ / Multi-Batch)",
            "Fast Turnaround (Speed & Quick Preview)",
            "Low-VRAM Compatibility (4GB - 6GB Staged)",
            "Custom Advanced Tuning",
        ])
        self.workflow_combo.currentIndexChanged.connect(self._on_workflow_preset_changed)
        preset_layout.addWidget(self.workflow_combo)
        controls_layout.addWidget(preset_group)

        # guidance and despill
        guidance_group = QGroupBox("Guidance and Despill")
        guidance_layout = QVBoxLayout(guidance_group)

        guidance_layout.addWidget(QLabel("Guidance Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Automatic (No Hint)",
            "First-Frame Mask Hint",
            "Full Video Mask Hint",
        ])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        guidance_layout.addWidget(self.mode_combo)

        self.hint_btn = QPushButton("Select Mask File...")
        self.hint_btn.setVisible(False)
        self.hint_btn.clicked.connect(self._browse_hint)
        guidance_layout.addWidget(self.hint_btn)

        self.hint_label = QLabel("")
        self.hint_label.setVisible(False)
        self.hint_label.setStyleSheet("color: #666666; font-size: 10px;")
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
            "Despill Strength:", self.despill_slider, self.despill_spin,
            "Suppresses green or blue background bounce on hair, clothing, and skin."
        ))

        controls_layout.addWidget(guidance_group)

        # export deliverables
        export_group = QGroupBox("Export Deliverables")
        export_layout = QVBoxLayout(export_group)

        self.deliverable_combo = QComboBox()
        self.deliverable_combo.addItems([
            "Blender: ProRes 4444 RGBA (Transparent Video)",
            "Blender: PNG Sequence (Transparent Frames)",
            "WebM: VP9 RGBA (Transparent Web Video)",
            "QuickTime: Animation RLE (Lossless RGBA)",
            "TIFF Sequence 16-bit (High Depth Archival)",
            "DaVinci Resolve Matte Pack (Fill + External Matte)",
            "OpenEXR Sequence (Linear 32-bit Float)",
            "Standard Separate Passes (FG + Alpha MP4)",
        ])
        export_layout.addWidget(self.deliverable_combo)

        self.blender_script_check = QCheckBox("Generate Blender Compositor Script (import_to_blender.py)")
        self.blender_script_check.setChecked(True)
        export_layout.addWidget(self.blender_script_check)

        out_row = QHBoxLayout()
        self.outdir_label = QLabel("Output: ./outputs")
        self.outdir_label.setStyleSheet("color: #666666; font-size: 10px; font-family: monospace;")
        out_btn = QPushButton("Change...")
        out_btn.setFixedHeight(22)
        out_btn.clicked.connect(self._browse_output_dir)
        out_row.addWidget(self.outdir_label, stretch=1)
        out_row.addWidget(out_btn)
        export_layout.addLayout(out_row)

        controls_layout.addWidget(export_group)

        # advanced engine tuning (collapsible accordion with brief dev text)
        self.advanced_toggle_btn = QPushButton("▸ Advanced Engine Tuning")
        self.advanced_toggle_btn.setCheckable(True)
        self.advanced_toggle_btn.setChecked(False)
        self.advanced_toggle_btn.setStyleSheet(
            "QPushButton { background-color: #090909; border: 1px solid #1a1a1a; border-radius: 4px; "
            "padding: 8px 12px; font-weight: 600; color: #888888; text-align: left; } "
            "QPushButton:hover { background-color: #111111; border-color: #282828; color: #d0d0d0; } "
            "QPushButton:checked { background-color: #101010; border-color: #303030; color: #ffffff; }"
        )
        self.advanced_toggle_btn.toggled.connect(self._on_toggle_advanced)
        controls_layout.addWidget(self.advanced_toggle_btn)

        self.advanced_container = QWidget()
        self.advanced_container.setVisible(False)
        advanced_layout = QVBoxLayout(self.advanced_container)
        advanced_layout.setContentsMargins(0, 4, 0, 4)
        advanced_layout.setSpacing(10)

        # 1. sampling and temporal windows
        sampling_group = QGroupBox("Sampling and Temporal Windows")
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
            "Model Scale:", self.scale_slider, self.scale_spin,
            "Resolution scale. 1.0 is native; 0.75 cuts memory; 1.25 for sub-pixel hair."
        ))

        self.start_mode_combo = QComboBox()
        self.start_mode_combo.addItems(["begin (Frame 0 -> N)", "middle (Center -> Edges)", "random_middle"])
        sampling_layout.addWidget(self._create_param_row(
            "Processing Anchor:", self.start_mode_combo,
            "Temporal direction. Middle anchors center frames for late subject entrances."
        ))

        self.chunk_slider = QSlider(Qt.Orientation.Horizontal)
        self.chunk_slider.setRange(1, 192)
        self.chunk_slider.setValue(self.gpu_profile.recommended_chunk)
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(1, 192)
        self.chunk_spin.setValue(self.gpu_profile.recommended_chunk)
        self._sync_int_slider(self.chunk_slider, self.chunk_spin)
        sampling_layout.addWidget(self._create_slider_param_row(
            "Hann Chunk:", self.chunk_slider, self.chunk_spin,
            "Temporal analysis window size. Larger preserves continuity, requires more VRAM."
        ))

        self.stride_slider = QSlider(Qt.Orientation.Horizontal)
        self.stride_slider.setRange(1, 96)
        self.stride_slider.setValue(self.gpu_profile.recommended_stride)
        self.stride_spin = QSpinBox()
        self.stride_spin.setRange(1, 96)
        self.stride_spin.setValue(self.gpu_profile.recommended_stride)
        self._sync_int_slider(self.stride_slider, self.stride_spin)
        sampling_layout.addWidget(self._create_slider_param_row(
            "Hann Stride:", self.stride_slider, self.stride_spin,
            "Overlap stride between analysis windows. Smaller reduces popping."
        ))

        self.num_frames_spin = QSpinBox()
        self.num_frames_spin.setRange(-1, 50000)
        self.num_frames_spin.setValue(-1)
        sampling_layout.addWidget(self._create_param_row(
            "Limit Frames:", self.num_frames_spin,
            "Process first N frames only (-1 for full video). Handy for quick tests."
        ))

        advanced_layout.addWidget(sampling_group)

        # 2. memory management
        memory_group = QGroupBox("Memory Management")
        memory_layout = QVBoxLayout(memory_group)

        self.low_vram_check = QCheckBox("Low-VRAM Staged Inference")
        self.low_vram_check.setChecked(self.gpu_profile.recommended_low_vram)
        self.low_vram_check.stateChanged.connect(self._on_param_changed)
        memory_layout.addWidget(self.low_vram_check)

        note_vram = QLabel("Splits computation into disk-backed staging passes for 4GB-6GB GPUs. Uncheck on 12GB+ GPUs for fastest in-memory execution.")
        note_vram.setStyleSheet("color: #666666; font-size: 10px;")
        memory_layout.addWidget(note_vram)

        advanced_layout.addWidget(memory_group)

        # 3. hardware concurrency and throughput
        perf_group = QGroupBox("Hardware Concurrency & Concurrency")
        perf_layout = QVBoxLayout(perf_group)

        self.stage2_batch_slider = QSlider(Qt.Orientation.Horizontal)
        self.stage2_batch_slider.setRange(1, 8)
        self.stage2_batch_slider.setValue(self.gpu_profile.recommended_stage2_batch)
        self.stage2_batch_spin = QSpinBox()
        self.stage2_batch_spin.setRange(1, 8)
        self.stage2_batch_spin.setValue(self.gpu_profile.recommended_stage2_batch)
        self._sync_int_slider(self.stage2_batch_slider, self.stage2_batch_spin)
        perf_layout.addWidget(self._create_slider_param_row(
            "Stage-2 Batch:", self.stage2_batch_slider, self.stage2_batch_spin,
            "Parallel output frames rendered per stage-2 batch. Set to 2-4 on 16GB-24GB GPUs."
        ))

        self.foundation_chunk_slider = QSlider(Qt.Orientation.Horizontal)
        self.foundation_chunk_slider.setRange(2, 32)
        self.foundation_chunk_slider.setValue(self.gpu_profile.recommended_foundation_chunk)
        self.foundation_chunk_spin = QSpinBox()
        self.foundation_chunk_spin.setRange(2, 32)
        self.foundation_chunk_spin.setValue(self.gpu_profile.recommended_foundation_chunk)
        self._sync_int_slider(self.foundation_chunk_slider, self.foundation_chunk_spin)
        perf_layout.addWidget(self._create_slider_param_row(
            "Foundation Chunk:", self.foundation_chunk_slider, self.foundation_chunk_spin,
            "Chunk size for RVM / C-RADIO foundation passes. Set to 8-16 on high-end cards."
        ))

        self.swin_batch_spin = QSpinBox()
        self.swin_batch_spin.setRange(8, 128)
        self.swin_batch_spin.setSingleStep(8)
        self.swin_batch_spin.setValue(self.gpu_profile.recommended_swin_batch)
        perf_layout.addWidget(self._create_param_row(
            "Swin Window Batch:", self.swin_batch_spin,
            "Swin attention batch size. Set to 32 or 64 on 12GB+ GPUs."
        ))

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 32)
        self.threads_spin.setValue(self.gpu_profile.recommended_ffmpeg_threads)
        perf_layout.addWidget(self._create_param_row(
            "FFmpeg Threads:", self.threads_spin,
            "CPU worker threads for video decode and encode pipes (0 = auto)."
        ))

        advanced_layout.addWidget(perf_group)

        # 4. color space and adjustments
        color_group = QGroupBox("Color and Contrast")
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
        color_layout.addWidget(self._create_slider_param_row("Linear Contrast:", self.contrast_slider, self.contrast_spin, "Optical contrast multiplier."))

        self.bright_slider = QSlider(Qt.Orientation.Horizontal)
        self.bright_slider.setRange(-100, 100)
        self.bright_slider.setValue(0)
        self.bright_spin = QDoubleSpinBox()
        self.bright_spin.setRange(-1.0, 1.0)
        self.bright_spin.setSingleStep(0.05)
        self.bright_spin.setValue(0.0)
        self._sync_float_slider(self.bright_slider, self.bright_spin, 100.0)
        color_layout.addWidget(self._create_slider_param_row("Linear Brightness:", self.bright_slider, self.bright_spin, "Optical brightness offset."))

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
        self.start_btn.setFixedHeight(38)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e3a29;
                color: #cce8d6;
                font-weight: bold;
                padding: 8px 16px;
                border: 1px solid #2d6b41;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #274d35;
                color: #ffffff;
                border-color: #388452;
            }
            QPushButton:disabled {
                background-color: #0c0c0c;
                color: #383838;
                border-color: #161616;
            }
        """)
        self.start_btn.clicked.connect(self._start_keying)
        btn_layout.addWidget(self.start_btn, stretch=3)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(38)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #141414;
                color: #888888;
                padding: 8px 16px;
                border: 1px solid #222222;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1c1c1c;
                color: #b0b0b0;
                border-color: #303030;
            }
            QPushButton:disabled {
                background-color: #080808;
                color: #282828;
                border-color: #101010;
            }
        """)
        self.cancel_btn.clicked.connect(self._cancel_keying)
        btn_layout.addWidget(self.cancel_btn, stretch=1)
        controls_layout.addLayout(btn_layout)

        controls_layout.addStretch()
        scroll_area.setWidget(controls_widget)
        splitter.addWidget(scroll_area)

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

        view_bar.addWidget(QLabel("Preview:"))
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
        view_bar.addWidget(QLabel("Zoom:"))
        btn_zoom_fit = QPushButton("Fit")
        btn_zoom_fit.setFixedHeight(24)
        btn_zoom_fit.setMinimumWidth(38)
        btn_zoom_fit.clicked.connect(lambda: self.canvas.set_zoom_mode("fit"))
        view_bar.addWidget(btn_zoom_fit)

        btn_zoom_100 = QPushButton("100%")
        btn_zoom_100.setFixedHeight(24)
        btn_zoom_100.setMinimumWidth(50)
        btn_zoom_100.clicked.connect(lambda: self.canvas.set_zoom_mode("100%"))
        view_bar.addWidget(btn_zoom_100)

        btn_zoom_200 = QPushButton("200%")
        btn_zoom_200.setFixedHeight(24)
        btn_zoom_200.setMinimumWidth(50)
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
            "QFrame { background-color: #080808; border: 1px solid #1a1a1a; border-radius: 4px; padding: 4px 8px; }"
        )
        pb_layout = QVBoxLayout(playback_frame)
        pb_layout.setContentsMargins(4, 3, 4, 4)
        pb_layout.setSpacing(4)

        # timeline scrubbing slider
        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setRange(0, 0)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #181818;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #444444;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #888888;
                border: 1px solid #aaaaaa;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
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
        self.btn_step_prev.setFixedHeight(24)
        self.btn_step_prev.setMinimumWidth(32)
        self.btn_step_prev.setEnabled(False)
        self.btn_step_prev.clicked.connect(self._on_step_prev)
        transport_layout.addWidget(self.btn_step_prev)

        self.btn_play_pause = QPushButton("▶")
        self.btn_play_pause.setFixedHeight(24)
        self.btn_play_pause.setMinimumWidth(38)
        self.btn_play_pause.setEnabled(False)
        self.btn_play_pause.setStyleSheet(
            "QPushButton { background-color: #1c1c1c; font-weight: bold; } "
            "QPushButton:hover { background-color: #282828; color: #ffffff; }"
        )
        self.btn_play_pause.clicked.connect(self._on_toggle_play_pause)
        transport_layout.addWidget(self.btn_play_pause)

        self.btn_step_next = QPushButton("▶▶")
        self.btn_step_next.setFixedHeight(24)
        self.btn_step_next.setMinimumWidth(32)
        self.btn_step_next.setEnabled(False)
        self.btn_step_next.clicked.connect(self._on_step_next)
        transport_layout.addWidget(self.btn_step_next)

        self.btn_loop = QPushButton("Loop")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setChecked(True)
        self.btn_loop.setFixedHeight(24)
        self.btn_loop.setMinimumWidth(48)
        self.btn_loop.setStyleSheet(
            "QPushButton { background-color: #101010; color: #777777; border: 1px solid #202020; padding: 2px 8px; font-size: 10px; } "
            "QPushButton:checked { background-color: #222222; color: #ffffff; border-color: #404040; }"
        )
        transport_layout.addWidget(self.btn_loop)

        self.timecode_label = QLabel("00:00:00.00 / 00:00:00.00  [Frame 0 / 0]")
        self.timecode_label.setStyleSheet("color: #777777; font-family: monospace; font-size: 10px; margin-left: 8px;")
        transport_layout.addWidget(self.timecode_label)

        transport_layout.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #777777; font-size: 10px;")
        transport_layout.addWidget(self.status_label)

        self.btn_toggle_log = QPushButton("Log")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setFixedHeight(22)
        self.btn_toggle_log.setMinimumWidth(42)
        self.btn_toggle_log.setStyleSheet(
            "QPushButton { background-color: #101010; color: #666666; border: 1px solid #1f1f1f; font-size: 10px; } "
            "QPushButton:checked { background-color: #1f1f1f; color: #cccccc; border-color: #333333; }"
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
            QProgressBar { background-color: #0c0c0c; border: 1px solid #1a1a1a; border-radius: 4px; }
            QProgressBar::chunk { background-color: #38a169; border-radius: 3px; }
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
        self.log_text.setFixedHeight(100)
        self.log_text.setStyleSheet(
            "background-color: #070707; color: #888888; font-family: monospace; font-size: 10px; "
            "border: 1px solid #181818; border-radius: 4px;"
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
        row_layout.setContentsMargins(0, 2, 0, 3)
        row_layout.setSpacing(2)

        top_layout = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #cccccc; font-weight: 500; font-size: 11px;")
        top_layout.addWidget(lbl)
        top_layout.addWidget(widget)
        row_layout.addLayout(top_layout)

        if note_text:
            note_lbl = QLabel(note_text)
            note_lbl.setStyleSheet("color: #666666; font-size: 10px;")
            note_lbl.setWordWrap(True)
            row_layout.addWidget(note_lbl)

        return row_widget

    def _create_slider_param_row(self, label_text: str, slider: QSlider, spinbox: QWidget, note_text: str) -> QWidget:
        row_widget = QWidget()
        row_layout = QVBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 3)
        row_layout.setSpacing(2)

        top_layout = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #cccccc; font-weight: 500; font-size: 11px;")
        top_layout.addWidget(lbl)
        top_layout.addStretch()
        top_layout.addWidget(spinbox)
        row_layout.addLayout(top_layout)

        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #181818;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3a3a3a;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #777777;
                border: 1px solid #999999;
                width: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
        """)
        row_layout.addWidget(slider)

        if note_text:
            note_lbl = QLabel(note_text)
            note_lbl.setStyleSheet("color: #666666; font-size: 10px;")
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

    def _on_toggle_advanced(self, checked: bool):
        self.advanced_container.setVisible(checked)
        self.advanced_toggle_btn.setText("▾ Advanced Engine Tuning" if checked else "▸ Advanced Engine Tuning")

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
                "background-color: #080808; border-left: 3px solid #2e2e2e; border-radius: 3px; padding: 6px 10px;"
            )
            self.vram_title.setText(f"Hardware: {self.gpu_profile.name} ({avail} GB) - {self.gpu_profile.tier_name}")
            self.vram_title.setStyleSheet("font-weight: 600; color: #888888; font-size: 11px;")
            self.vram_detail.setText(f"Peak footprint ~{peak_est} GB ({mode_str}). Fits comfortably inside dedicated VRAM.")
        else:
            self.vram_banner.setStyleSheet(
                "background-color: #120904; border-left: 3px solid #e67e22; border-radius: 3px; padding: 6px 10px;"
            )
            self.vram_title.setText(f"Hardware: {self.gpu_profile.name} ({avail} GB) - Memory Pressure")
            self.vram_title.setStyleSheet("font-weight: 600; color: #e67e22; font-size: 11px;")
            self.vram_detail.setText(
                f"Peak footprint ~{peak_est} GB ({mode_str}) exceeds {avail} GB dedicated VRAM. System may use shared memory or encounter OOM."
            )

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
        self.btn_play_pause.setText("❚❚")
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
            box.setWindowTitle("Resource Notification")
            box.setText(
                f"Estimated peak memory (~{peak_est} GB) exceeds detected dedicated GPU VRAM ({avail} GB).\n\n"
                f"On workstation GPUs with unified memory or sufficient swap, you can proceed directly.\n\n"
                f"To optimize automatically for your hardware tier ({self.gpu_profile.tier_name}), click 'Auto-Adapt to Hardware'."
            )
            proceed_btn = box.addButton("Proceed Anyway", QMessageBox.ButtonRole.AcceptRole)
            adapt_btn = box.addButton("Auto-Adapt to Hardware", QMessageBox.ButtonRole.ActionRole)
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
        self.update_label.setText(
            f"Update Available: New build on {branch} ({remote_commit}). Current: {local_commit}."
        )
        self.update_banner.setVisible(True)

    def _on_click_update_now(self):
        if not self.pending_update_branch or not self.pending_update_commit:
            return

        self.btn_update_now.setEnabled(False)
        self.btn_update_now.setText("Updating...")
        repo_root = Path(__file__).resolve().parents[1]
        self.update_installer = UpdateInstallWorker(repo_root, self.pending_update_branch, self.pending_update_commit)
        self.update_installer.install_progress.connect(self._on_update_progress)
        self.update_installer.install_finished.connect(self._on_update_finished)
        self.update_installer.start()

    @Slot(str)
    def _on_update_progress(self, message: str):
        self.update_label.setText(message)

    @Slot(bool, str)
    def _on_update_finished(self, success: bool, message: str):
        if success:
            self.update_label.setText(message)
            self.btn_update_now.setText("Restart Now")
            self.btn_update_now.setEnabled(True)
            self.btn_update_now.clicked.disconnect()
            self.btn_update_now.clicked.connect(self._restart_app)
        else:
            self.update_label.setText(f"Update failed: {message}")
            self.btn_update_now.setText("Retry")
            self.btn_update_now.setEnabled(True)

    def _restart_app(self):
        python = sys.executable
        os.execl(python, python, *sys.argv)

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
