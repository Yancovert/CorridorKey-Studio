from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSlider, QCheckBox, QSpinBox,
    QDoubleSpinBox, QFileDialog, QGroupBox, QScrollArea,
    QMessageBox, QInputDialog, QFrame, QApplication
)

from .settings_manager import (
    load_settings, save_settings, list_custom_presets,
    save_custom_preset, load_custom_preset, delete_custom_preset
)
from .gpu_info import (
    GpuProfile, SystemGpuDevice, enumerate_system_gpus, get_gpu_dropdown_options
)


class SettingsDialog(QDialog):
    settings_applied = Signal(dict)

    def __init__(self, parent: QWidget | None, gpu_profile: GpuProfile, app_root: Path, current_state: dict, system_gpus: list[SystemGpuDevice] | None = None):
        super().__init__(parent)
        self.setWindowTitle("CorridorKey Studio - Settings")
        self.resize(720, 740)
        self.setMinimumSize(580, 560)
        self.gpu_profile = gpu_profile
        self.app_root = app_root
        self.current_state = current_state
        self.system_gpus = system_gpus or enumerate_system_gpus()

        self._setup_theme()
        self._setup_ui()
        self._load_initial_values(current_state)

    def _setup_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1d21;
                color: #dce1e7;
                font-family: 'Nunito Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QGroupBox {
                background-color: #21252b;
                border: 1px solid #2e343d;
                border-radius: 5px;
                margin-top: 14px;
                padding: 12px 10px 8px 10px;
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
            QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #171a1e;
                border: 1px solid #333942;
                border-radius: 4px;
                padding: 4px 8px;
                color: #e6eaef;
                font-size: 11.5px;
                min-height: 22px;
            }
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
                border-color: #484f58;
                background-color: #1c212a;
            }
            QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #3b82f6;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #333942;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                background-color: #1a1f26;
            }
            QComboBox::down-arrow {
                width: 0px;
                height: 0px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #6e7681;
                margin-right: 2px;
            }
            QComboBox QAbstractItemView {
                background-color: #171a1e;
                border: 1px solid #333942;
                border-radius: 4px;
                color: #e6eaef;
                selection-background-color: #2b394e;
                selection-color: #ffffff;
                padding: 4px;
            }
            QCheckBox {
                color: #b0bac5;
                font-size: 11.5px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                background-color: #171a1e;
                border: 1px solid #333942;
                border-radius: 3px;
            }
            QCheckBox::indicator:hover {
                border-color: #484f58;
            }
            QCheckBox::indicator:checked {
                background-color: #2b394e;
                border-color: #3b82f6;
            }
            QPushButton {
                background-color: #21252b;
                color: #b0bac5;
                border: 1px solid #333942;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 11.5px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #282d35;
                border-color: #484f58;
                color: #ffffff;
            }
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(16)

        # 1. Preset management bar
        preset_group = QGroupBox("Presets")
        pg_layout = QVBoxLayout(preset_group)
        pg_layout.setSpacing(8)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(220)
        preset_row.addWidget(self.preset_combo, stretch=1)

        self.btn_load_preset = QPushButton("Load")
        self.btn_load_preset.clicked.connect(self._on_load_preset)
        preset_row.addWidget(self.btn_load_preset)

        self.btn_save_preset = QPushButton("Save New...")
        self.btn_save_preset.clicked.connect(self._on_save_new_preset)
        preset_row.addWidget(self.btn_save_preset)

        self.btn_delete_preset = QPushButton("Delete")
        self.btn_delete_preset.clicked.connect(self._on_delete_preset)
        preset_row.addWidget(self.btn_delete_preset)
        self._refresh_presets_combo()
        pg_layout.addLayout(preset_row)
        content_layout.addWidget(preset_group)

        # 2. Hardware and tuning
        hw_group = QGroupBox("Inference")
        hw_layout = QVBoxLayout(hw_group)
        hw_layout.setSpacing(10)

        row_gpu = QHBoxLayout()
        row_gpu.addWidget(QLabel("Compute GPU:"))
        self.combo_gpu = QComboBox()
        self.combo_gpu.setMinimumWidth(260)
        for label, dev_id, is_compat, cuda_idx in get_gpu_dropdown_options(self.system_gpus):
            self.combo_gpu.addItem(label, userData={"id": dev_id, "compat": is_compat, "cuda_idx": cuda_idx})
        self.combo_gpu.currentIndexChanged.connect(self._on_gpu_changed)
        row_gpu.addWidget(self.combo_gpu, stretch=1)
        hw_layout.addLayout(row_gpu)

        self.lbl_gpu_warn = QLabel("")
        self.lbl_gpu_warn.setStyleSheet("color: #f85149; font-size: 11px; padding: 2px 0;")
        self.lbl_gpu_warn.setVisible(False)
        hw_layout.addWidget(self.lbl_gpu_warn)

        self.chk_low_vram = QCheckBox("Low-VRAM Staged Inference")
        hw_layout.addWidget(self.chk_low_vram)

        row_scale = QHBoxLayout()
        row_scale.addWidget(QLabel("Model Scale:"))
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.25, 2.0)
        self.spin_scale.setSingleStep(0.05)
        self.spin_scale.setValue(1.0)
        row_scale.addWidget(self.spin_scale)
        hw_layout.addLayout(row_scale)

        row_chunk = QHBoxLayout()
        row_chunk.addWidget(QLabel("Window Chunk:"))
        self.spin_chunk = QSpinBox()
        self.spin_chunk.setRange(1, 192)
        row_chunk.addWidget(self.spin_chunk)
        hw_layout.addLayout(row_chunk)

        row_stride = QHBoxLayout()
        row_stride.addWidget(QLabel("Window Stride:"))
        self.spin_stride = QSpinBox()
        self.spin_stride.setRange(1, 96)
        row_stride.addWidget(self.spin_stride)
        hw_layout.addLayout(row_stride)

        row_anchor = QHBoxLayout()
        row_anchor.addWidget(QLabel("Anchor:"))
        self.combo_anchor = QComboBox()
        self.combo_anchor.addItems(["begin", "middle", "random_middle"])
        row_anchor.addWidget(self.combo_anchor)
        hw_layout.addLayout(row_anchor)

        content_layout.addWidget(hw_group)

        # 3. Throughput and batch concurrency
        perf_group = QGroupBox("Performance")
        perf_layout = QVBoxLayout(perf_group)
        perf_layout.setSpacing(10)

        row_stage2 = QHBoxLayout()
        row_stage2.addWidget(QLabel("Stage-2 Batch:"))
        self.spin_stage2 = QSpinBox()
        self.spin_stage2.setRange(1, 8)
        row_stage2.addWidget(self.spin_stage2)
        perf_layout.addLayout(row_stage2)

        row_found = QHBoxLayout()
        row_found.addWidget(QLabel("Foundation Chunk:"))
        self.spin_found = QSpinBox()
        self.spin_found.setRange(2, 32)
        row_found.addWidget(self.spin_found)
        perf_layout.addLayout(row_found)

        row_swin = QHBoxLayout()
        row_swin.addWidget(QLabel("Swin Batch:"))
        self.spin_swin = QSpinBox()
        self.spin_swin.setRange(8, 128)
        self.spin_swin.setSingleStep(8)
        row_swin.addWidget(self.spin_swin)
        perf_layout.addLayout(row_swin)

        row_threads = QHBoxLayout()
        row_threads.addWidget(QLabel("Worker Threads (0 = auto):"))
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(0, 32)
        row_threads.addWidget(self.spin_threads)
        perf_layout.addLayout(row_threads)

        content_layout.addWidget(perf_group)

        # 4. Color and Despill defaults
        color_group = QGroupBox("Color")
        color_layout = QVBoxLayout(color_group)
        color_layout.setSpacing(10)

        self.chk_linear = QCheckBox("Linear Color Space Keying")
        self.chk_linear.setChecked(True)
        color_layout.addWidget(self.chk_linear)

        row_despill = QHBoxLayout()
        row_despill.addWidget(QLabel("Despill Strength:"))
        self.spin_despill = QDoubleSpinBox()
        self.spin_despill.setRange(0.0, 1.0)
        self.spin_despill.setSingleStep(0.05)
        self.spin_despill.setValue(0.50)
        row_despill.addWidget(self.spin_despill)
        color_layout.addLayout(row_despill)

        row_contrast = QHBoxLayout()
        row_contrast.addWidget(QLabel("Contrast Multiplier:"))
        self.spin_contrast = QDoubleSpinBox()
        self.spin_contrast.setRange(0.1, 2.0)
        self.spin_contrast.setSingleStep(0.05)
        self.spin_contrast.setValue(1.0)
        row_contrast.addWidget(self.spin_contrast)
        color_layout.addLayout(row_contrast)

        row_bright = QHBoxLayout()
        row_bright.addWidget(QLabel("Brightness Multiplier:"))
        self.spin_bright = QDoubleSpinBox()
        self.spin_bright.setRange(0.1, 2.5)
        self.spin_bright.setSingleStep(0.05)
        self.spin_bright.setValue(1.0)
        row_bright.addWidget(self.spin_bright)
        color_layout.addLayout(row_bright)

        content_layout.addWidget(color_group)

        # 5. Deliverables & Output
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout(export_group)
        export_layout.setSpacing(10)

        row_deliv = QHBoxLayout()
        row_deliv.addWidget(QLabel("Format:"))
        self.combo_deliverable = QComboBox()
        self.combo_deliverable.addItems([
            "ProRes 4444 (RGBA)",
            "PNG Sequence (RGBA)",
            "WebM VP9 (RGBA)",
            "QuickTime RLE (RGBA)",
            "TIFF 16-bit (RGBA)",
            "Matte Pack (Fill + Matte)",
            "OpenEXR 32-bit (RGBA)",
            "Separate Passes (FG + Alpha)",
        ])
        row_deliv.addWidget(self.combo_deliverable)
        export_layout.addLayout(row_deliv)

        self.chk_blender_script = QCheckBox("Generate Blender import script")
        self.chk_blender_script.setChecked(True)
        export_layout.addWidget(self.chk_blender_script)

        row_out = QHBoxLayout()
        row_out.addWidget(QLabel("Output Directory:"))
        self.lbl_outdir = QLabel("./outputs")
        self.lbl_outdir.setStyleSheet("color: #8b949e; font-family: monospace; font-size: 11px;")
        btn_browse_out = QPushButton("Change...")
        btn_browse_out.clicked.connect(self._browse_output_dir)
        row_out.addWidget(self.lbl_outdir, stretch=1)
        row_out.addWidget(btn_browse_out)
        export_layout.addLayout(row_out)

        content_layout.addWidget(export_group)

        # 6. Maintenance & Uninstaller
        maint_group = QGroupBox("Maintenance")
        maint_layout = QVBoxLayout(maint_group)
        maint_layout.setSpacing(8)

        lbl_app_path = QLabel(f"Directory: {self.app_root}")
        lbl_app_path.setStyleSheet("color: #8b949e; font-size: 11px; font-family: monospace;")
        maint_layout.addWidget(lbl_app_path)

        maint_row = QHBoxLayout()
        btn_patchnotes = QPushButton("View Patch Notes...")
        btn_patchnotes.setStyleSheet(
            "QPushButton { background-color: #1c2128; color: #58a6ff; border: 1px solid #30363d; "
            "padding: 5px 14px; font-weight: 500; border-radius: 4px; } "
            "QPushButton:hover { background-color: #262c36; border-color: #58a6ff; color: #f0f6fc; }"
        )
        btn_patchnotes.clicked.connect(self._on_click_view_patchnotes)
        maint_row.addWidget(btn_patchnotes)

        btn_uninstall = QPushButton("Uninstall...")
        btn_uninstall.setStyleSheet(
            "QPushButton { background-color: #1a1616; color: #c98888; border: 1px solid #3d2626; "
            "padding: 5px 14px; font-weight: 500; border-radius: 4px; } "
            "QPushButton:hover { background-color: #281e1e; border-color: #5a3030; color: #f0f6fc; }"
        )
        btn_uninstall.clicked.connect(self._on_click_uninstall)
        maint_row.addWidget(btn_uninstall)
        maint_row.addStretch()
        maint_layout.addLayout(maint_row)

        content_layout.addWidget(maint_group)

        content_layout.addStretch()
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area, stretch=1)

        # Dialog button bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        btn_reset_hw = QPushButton("Reset Defaults")
        btn_reset_hw.clicked.connect(self._on_reset_hardware_defaults)
        btn_bar.addWidget(btn_reset_hw)

        btn_bar.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(btn_cancel)

        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._on_apply_current)
        btn_bar.addWidget(btn_apply)

        btn_save_default = QPushButton("Save Default")
        btn_save_default.setStyleSheet(
            "QPushButton { background-color: #2e4363; color: #ffffff; font-weight: 600; "
            "border: 1px solid #3b82f6; border-radius: 4px; padding: 5px 14px; font-size: 11.5px; } "
            "QPushButton:hover { background-color: #3b547c; border-color: #60a5fa; }"
        )
        btn_save_default.clicked.connect(self._on_save_as_default)
        btn_bar.addWidget(btn_save_default)

        main_layout.addLayout(btn_bar)

    def _refresh_presets_combo(self):
        self.preset_combo.clear()
        presets = list_custom_presets()
        if presets:
            self.preset_combo.addItems(presets)
            self.btn_load_preset.setEnabled(True)
            self.btn_delete_preset.setEnabled(True)
        else:
            self.preset_combo.addItem("No custom presets saved")
            self.btn_load_preset.setEnabled(False)
            self.btn_delete_preset.setEnabled(False)

    def _load_initial_values(self, state: dict):
        if "selected_gpu" in state:
            target_id = str(state["selected_gpu"])
            for i in range(self.combo_gpu.count()):
                d = self.combo_gpu.itemData(i) or {}
                if d.get("id") == target_id:
                    self.combo_gpu.setCurrentIndex(i)
                    break
        self.chk_low_vram.setChecked(state.get("low_vram", self.gpu_profile.recommended_low_vram))
        self.spin_scale.setValue(float(state.get("scale", 1.0)))
        self.spin_chunk.setValue(int(state.get("chunk", self.gpu_profile.recommended_chunk)))
        self.spin_stride.setValue(int(state.get("stride", self.gpu_profile.recommended_stride)))
        anchor_val = str(state.get("start_mode", "begin")).split()[0]
        for i in range(self.combo_anchor.count()):
            if self.combo_anchor.itemText(i) == anchor_val:
                self.combo_anchor.setCurrentIndex(i)
                break

        self.spin_stage2.setValue(int(state.get("stage2_batch", self.gpu_profile.recommended_stage2_batch)))
        self.spin_found.setValue(int(state.get("foundation_chunk", self.gpu_profile.recommended_foundation_chunk)))
        self.spin_swin.setValue(int(state.get("swin_batch", self.gpu_profile.recommended_swin_batch)))
        self.spin_threads.setValue(int(state.get("threads", self.gpu_profile.recommended_ffmpeg_threads)))

        self.chk_linear.setChecked(bool(state.get("linear", True)))
        self.spin_despill.setValue(float(state.get("despill", 0.50)))
        self.spin_contrast.setValue(float(state.get("contrast", 1.0)))
        bright_val = float(state.get("bright", 1.0))
        self.spin_bright.setValue(1.0 if bright_val <= 0.05 else bright_val)

        deliv_val = str(state.get("deliverable", "ProRes 4444 (RGBA)"))
        idx = self.combo_deliverable.findText(deliv_val)
        if idx >= 0:
            self.combo_deliverable.setCurrentIndex(idx)
        else:
            for i in range(self.combo_deliverable.count()):
                if "ProRes" in deliv_val and "ProRes" in self.combo_deliverable.itemText(i):
                    self.combo_deliverable.setCurrentIndex(i)
                    break
        self.chk_blender_script.setChecked(bool(state.get("blender_script", True)))
        self.lbl_outdir.setText(str(state.get("output_dir", "./outputs")))

    def _collect_current_dict(self) -> dict:
        d = dict(self.current_state)
        gpu_id = "auto"
        if hasattr(self, "combo_gpu") and self.combo_gpu.currentData():
            gpu_id = self.combo_gpu.currentData().get("id", "auto")
        d.update({
            "selected_gpu": gpu_id,
            "low_vram": self.chk_low_vram.isChecked(),
            "scale": round(self.spin_scale.value(), 2),
            "chunk": self.spin_chunk.value(),
            "stride": self.spin_stride.value(),
            "start_mode": self.combo_anchor.currentText(),
            "stage2_batch": self.spin_stage2.value(),
            "foundation_chunk": self.spin_found.value(),
            "swin_batch": self.spin_swin.value(),
            "threads": self.spin_threads.value(),
            "linear": self.chk_linear.isChecked(),
            "despill": round(self.spin_despill.value(), 2),
            "contrast": round(self.spin_contrast.value(), 2),
            "bright": round(self.spin_bright.value(), 2),
            "deliverable": self.combo_deliverable.currentText(),
            "blender_script": self.chk_blender_script.isChecked(),
            "output_dir": self.lbl_outdir.text(),
        })
        return d

    def _browse_output_dir(self):
        cur = self.lbl_outdir.text()
        chosen = QFileDialog.getExistingDirectory(self, "Select Default Output Directory", cur)
        if chosen:
            self.lbl_outdir.setText(chosen)

    def _on_gpu_changed(self, index: int):
        data = self.combo_gpu.currentData() or {}
        if not data.get("compat", True):
            self.lbl_gpu_warn.setText("Selected adapter does not support CUDA. Neural network inference will fail.")
            self.lbl_gpu_warn.setVisible(True)
        else:
            self.lbl_gpu_warn.setVisible(False)

    def _on_reset_hardware_defaults(self):
        self.combo_gpu.setCurrentIndex(0)
        self.chk_low_vram.setChecked(self.gpu_profile.recommended_low_vram)
        self.spin_scale.setValue(1.0)
        self.spin_chunk.setValue(self.gpu_profile.recommended_chunk)
        self.spin_stride.setValue(self.gpu_profile.recommended_stride)
        self.combo_anchor.setCurrentIndex(0)
        self.spin_stage2.setValue(self.gpu_profile.recommended_stage2_batch)
        self.spin_found.setValue(self.gpu_profile.recommended_foundation_chunk)
        self.spin_swin.setValue(self.gpu_profile.recommended_swin_batch)
        self.spin_threads.setValue(self.gpu_profile.recommended_ffmpeg_threads)
        self.chk_linear.setChecked(True)
        self.spin_despill.setValue(0.50)
        self.spin_contrast.setValue(1.0)
        self.spin_bright.setValue(1.0)

    def _on_save_new_preset(self):
        name, ok = QInputDialog.getText(self, "Save Custom Preset", "Enter a name for this preset profile:")
        if ok and name.strip():
            data = self._collect_current_dict()
            if save_custom_preset(name.strip(), data):
                self._refresh_presets_combo()
                self.preset_combo.setCurrentText(name.strip())
                QMessageBox.information(self, "Preset Saved", f"Preset '{name.strip()}' saved successfully.")
            else:
                QMessageBox.critical(self, "Error", "Failed to save preset profile.")

    def _on_load_preset(self):
        selected = self.preset_combo.currentText()
        if not selected or selected == "No custom presets saved":
            return
        data = load_custom_preset(selected)
        if data:
            self._load_initial_values(data)
            QMessageBox.information(self, "Preset Loaded", f"Loaded settings from '{selected}'.")

    def _on_delete_preset(self):
        selected = self.preset_combo.currentText()
        if not selected or selected == "No custom presets saved":
            return
        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Are you sure you want to delete preset '{selected}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_custom_preset(selected)
            self._refresh_presets_combo()

    def _on_apply_current(self):
        data = self._collect_current_dict()
        self.settings_applied.emit(data)
        self.accept()

    def _on_save_as_default(self):
        data = self._collect_current_dict()
        if save_settings(data):
            self.settings_applied.emit(data)
            QMessageBox.information(self, "Settings Saved", "Saved as default application settings.")
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Failed to write default settings file.")

    def _on_click_view_patchnotes(self):
        from .patchnotes_dialog import PatchNotesDialog, get_installed_version
        v = get_installed_version(self.app_root)
        dlg = PatchNotesDialog(self, self.app_root, current_version=v)
        dlg.exec()

    def _on_click_uninstall(self):
        reply = QMessageBox.warning(
            self, "Uninstall CorridorKey Studio",
            "Uninstall CorridorKey Studio?\n\n"
            "This removes shortcuts, virtual environment, and application files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.close()
        if self.parent():
            self.parent().close()

        # launch detached uninstaller in new console
        sh_path = self.app_root / "uninstall.sh"
        bat_path = self.app_root / "uninstall.bat"

        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", str(bat_path)],
                    cwd=str(self.app_root),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
                )
            else:
                # launch in terminal if available, otherwise detached bash
                term_cmd = None
                for term in ("konsole", "gnome-terminal", "xterm", "alacritty", "kitty"):
                    term_bin = subprocess.run(["which", term], capture_output=True, text=True).stdout.strip()
                    if term_bin:
                        if term == "gnome-terminal":
                            term_cmd = [term_bin, "--", "bash", str(sh_path)]
                        else:
                            term_cmd = [term_bin, "-e", "bash", str(sh_path)]
                        break

                if term_cmd:
                    subprocess.Popen(term_cmd, cwd=str(self.app_root), start_new_session=True)
                else:
                    subprocess.Popen(["bash", str(sh_path), "-y"], cwd=str(self.app_root), start_new_session=True)

            QApplication.quit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to launch uninstaller:\n{e}")
