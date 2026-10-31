from __future__ import annotations

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QPalette, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QProgressBar,
    QTextEdit, QGroupBox, QMessageBox
)

bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


class InstallWorker(QThread):
    progress_changed = Signal(int, str)
    log_received = Signal(str)
    install_finished = Signal(bool, str)

    def __init__(self, target_dir: Path, weights_dir: Path, shortcut: bool, download_weights: bool, low_vram: bool):
        super().__init__()
        self.target_dir = target_dir
        self.weights_dir = weights_dir
        self.shortcut = shortcut
        self.download_weights = download_weights
        self.low_vram = low_vram

    def run(self):
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
            self.weights_dir.mkdir(parents=True, exist_ok=True)

            # 1. extract or copy application payload
            self.progress_changed.emit(5, "Extracting application files...")
            self.log_received.emit(f"installing files to: {self.target_dir}")

            payload_items = [
                "gui",
                "scripts",
                "corridorkey",
                "third_party",
                "requirements.txt",
                "infer.py",
                "run_interactive.py",
                "launch_gui.sh",
                "launch_gui.bat"
            ]

            for item_name in payload_items:
                src_item = bundle_dir / item_name
                dst_item = self.target_dir / item_name
                if src_item.exists() and src_item.resolve() != dst_item.resolve():
                    if src_item.is_dir():
                        if dst_item.exists():
                            shutil.rmtree(dst_item)
                        shutil.copytree(src_item, dst_item)
                    else:
                        shutil.copy2(src_item, dst_item)
                    self.log_received.emit(f"copied {item_name}")

            # ensure launch script executable
            launcher_sh = self.target_dir / "launch_gui.sh"
            if launcher_sh.exists():
                launcher_sh.chmod(0o755)

            # 2. virtualenv setup
            self.progress_changed.emit(20, "Setting up virtual environment...")
            venv_dir = self.target_dir / "venv"
            self.log_received.emit(f"creating virtual environment in: {venv_dir}")

            py_bin = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
            if not py_bin.exists():
                has_uv = shutil.which("uv") is not None
                if has_uv:
                    cmd = ["uv", "venv", str(venv_dir)]
                else:
                    cmd = [sys.executable, "-m", "venv", str(venv_dir)]
                subprocess.run(cmd, check=True, cwd=str(self.target_dir))

            # 3. pytorch and dependencies
            self.progress_changed.emit(45, "Installing PyTorch CUDA and dependencies...")
            self.log_received.emit("installing pytorch with cuda 12.8 support...")

            has_uv = shutil.which("uv") is not None
            if has_uv:
                subprocess.run([
                    "uv", "pip", "install", "torch", "torchvision",
                    "--index-url", "https://download.pytorch.org/whl/cu128",
                    "--python", str(py_bin)
                ], check=True, cwd=str(self.target_dir))

                self.log_received.emit("installing requirements and pyside6...")
                subprocess.run([
                    "uv", "pip", "install", "-r", str(self.target_dir / "requirements.txt"),
                    "PySide6", "--python", str(py_bin)
                ], check=True, cwd=str(self.target_dir))
            else:
                pip_bin = py_bin.parent / ("pip.exe" if sys.platform == "win32" else "pip")
                subprocess.run([
                    str(pip_bin), "install", "torch", "torchvision",
                    "--index-url", "https://download.pytorch.org/whl/cu128"
                ], check=True, cwd=str(self.target_dir))

                subprocess.run([
                    str(pip_bin), "install", "-r", str(self.target_dir / "requirements.txt"), "PySide6"
                ], check=True, cwd=str(self.target_dir))

            # 4. foundation model weights
            if self.download_weights:
                self.progress_changed.emit(75, "Checking foundation models...")
                self.log_received.emit("verifying weights under weights/ and vfms/...")
                script = self.target_dir / "scripts" / "download_weights.py"
                if script.exists():
                    subprocess.run([str(py_bin), str(script)], check=True, cwd=str(self.target_dir))

            # 5. desktop shortcut
            if self.shortcut:
                self.progress_changed.emit(90, "Creating desktop launcher...")
                if sys.platform.startswith("linux"):
                    desktop_dir = Path.home() / "Desktop"
                    try:
                        res = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True)
                        if res.returncode == 0 and res.stdout.strip():
                            desktop_dir = Path(res.stdout.strip())
                    except Exception:
                        pass

                    apps_dir = Path.home() / ".local" / "share" / "applications"
                    apps_dir.mkdir(parents=True, exist_ok=True)
                    desktop_dir.mkdir(parents=True, exist_ok=True)

                    launcher = self.target_dir / "launch_gui.sh"
                    icon = self.target_dir / "gui" / "icon.png"
                    content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=CorridorKey Studio
GenericName=Chroma Keying Suite
Comment=AI-powered green screen cutout tool for Blender
Exec="{launcher}"
Path={self.target_dir}
Icon={icon}
Terminal=false
Categories=Graphics;Video;AudioVideo;
StartupNotify=true
StartupWMClass=CorridorKey Studio
"""
                    for dest_folder in [desktop_dir, apps_dir]:
                        dest_file = dest_folder / "corridorkey-studio.desktop"
                        with open(dest_file, "w", encoding="utf-8") as f:
                            f.write(content)
                        dest_file.chmod(0o755)
                        if dest_folder == desktop_dir:
                            try:
                                subprocess.run(["gio", "set", str(dest_file), "metadata::trusted", "true"], capture_output=True)
                            except Exception:
                                pass
                    try:
                        subprocess.run(["update-desktop-database", str(apps_dir)], capture_output=True)
                    except Exception:
                        pass
                    self.log_received.emit("created desktop and application menu entries")

            self.progress_changed.emit(100, "Installation Complete!")
            self.install_finished.emit(True, "CorridorKey Studio installed successfully.")

        except Exception as e:
            self.install_finished.emit(False, str(e))


def find_best_drive() -> tuple[Path, float]:
    candidates = [Path.home()]
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].startswith("/dev/") and not parts[1].startswith("/boot"):
                        candidates.append(Path(parts[1]))
        except Exception:
            pass
    elif sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            p = Path(f"{letter}:\\")
            if p.exists():
                candidates.append(p)

    best_path = Path.home()
    best_free_gb = 0.0

    for c in set(candidates):
        try:
            user = os.environ.get("USER", "")
            target = c
            if not os.access(c, os.W_OK):
                if user and (c / user).exists() and os.access(c / user, os.W_OK):
                    target = c / user
                else:
                    continue
            usage = shutil.disk_usage(target)
            free_gb = usage.free / (1024 ** 3)
            if free_gb > best_free_gb:
                best_free_gb = free_gb
                best_path = target
        except Exception:
            pass

    return best_path, best_free_gb


class InstallerWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CorridorKey Studio Setup")
        self.resize(580, 540)
        self.setMinimumSize(520, 500)

        self._setup_ui()
        self._detect_system()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # header
        title = QLabel("CorridorKey Studio Installer")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f0f6fc;")
        layout.addWidget(title)

        self.sys_label = QLabel("Detecting hardware...")
        self.sys_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self.sys_label)

        # directories group
        dir_group = QGroupBox("Target Directories")
        dir_layout = QVBoxLayout(dir_group)

        best_drive, best_free_gb = find_best_drive()
        default_install = best_drive / "CorridorKey-Studio"

        rec_label = QLabel(f"Recommended drive with most space: {best_drive} ({best_free_gb:.1f} GB free)")
        rec_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        dir_layout.addWidget(rec_label)

        dir_layout.addWidget(QLabel("Installation Directory:"))
        install_row = QHBoxLayout()
        self.install_edit = QLineEdit(str(default_install))
        self.install_edit.textChanged.connect(self._update_space)
        install_row.addWidget(self.install_edit)
        browse_inst_btn = QPushButton("Browse...")
        browse_inst_btn.clicked.connect(self._browse_install)
        install_row.addWidget(browse_inst_btn)
        dir_layout.addLayout(install_row)

        self.space_label = QLabel("")
        dir_layout.addWidget(self.space_label)
        self._update_space(str(default_install))

        dir_layout.addWidget(QLabel("Weights & Cache Directory:"))
        weights_row = QHBoxLayout()
        self.weights_edit = QLineEdit(str(default_install / "weights"))
        weights_row.addWidget(self.weights_edit)
        browse_wgt_btn = QPushButton("Browse...")
        browse_wgt_btn.clicked.connect(self._browse_weights)
        weights_row.addWidget(browse_wgt_btn)
        dir_layout.addLayout(weights_row)

        layout.addWidget(dir_group)

        # options group
        opt_group = QGroupBox("Preferences")
        opt_layout = QVBoxLayout(opt_group)

        self.shortcut_check = QCheckBox("Create Desktop & Application Menu Shortcut")
        self.shortcut_check.setChecked(True)
        opt_layout.addWidget(self.shortcut_check)

        self.weights_check = QCheckBox("Pre-download ~5 GB foundation models immediately")
        self.weights_check.setChecked(True)
        opt_layout.addWidget(self.weights_check)

        self.low_vram_check = QCheckBox("Enable 4GB Low-VRAM safety mode by default")
        self.low_vram_check.setChecked(True)
        opt_layout.addWidget(self.low_vram_check)

        layout.addWidget(opt_group)

        # progress and logs
        self.status_label = QLabel("Ready to install.")
        self.status_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(85)
        self.log_text.setStyleSheet("background-color: #161b22; color: #8b949e; font-family: monospace; font-size: 10px;")
        layout.addWidget(self.log_text)

        # buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Exit")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Install CorridorKey Studio")
        self.install_btn.setStyleSheet("background-color: #238636; color: white; font-weight: bold; padding: 6px 14px;")
        self.install_btn.clicked.connect(self._start_install)
        btn_row.addWidget(self.install_btn)

        layout.addLayout(btn_row)
        self._update_build_detection(str(default_install))

    def _detect_system(self):
        sys_str = f"{platform.system()} ({platform.machine()})"
        gpu_str = "No NVIDIA GPU"
        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                res = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    gpu_str = res.stdout.strip()
            except Exception:
                gpu_str = "NVIDIA Device"
        self.sys_label.setText(f"System: {sys_str} | GPU: {gpu_str}")

    def _update_space(self, text: str):
        try:
            p = Path(text).resolve()
            while not p.exists() and p.parent != p:
                p = p.parent
            usage = shutil.disk_usage(p)
            free_gb = usage.free / (1024 ** 3)
            if free_gb >= 10.0:
                self.space_label.setText(f"{free_gb:.1f} GB available on target partition (~5 GB required)")
                self.space_label.setStyleSheet("color: #3dd68c; font-size: 11px; font-weight: bold;")
            else:
                self.space_label.setText(f"{free_gb:.1f} GB available (warning: low disk space, ~5 GB required)")
                self.space_label.setStyleSheet("color: #ffaa00; font-size: 11px; font-weight: bold;")
        except Exception:
            self.space_label.setText("")

    def _update_build_detection(self, text: str):
        target = Path(text)
        is_installed = (target / "launch_gui.sh").exists() and (target / "corridorkey").exists()
        if not is_installed:
            self.install_btn.setText("Install CorridorKey Studio")
            self.status_label.setText("Ready to install.")
            self.status_label.setStyleSheet("color: #8b949e; font-size: 11px;")
            self.is_existing_build = False
            return

        self.is_existing_build = True
        self.install_btn.setText("Update CorridorKey Studio")
        self.status_label.setText("Existing build detected (branch: app-linux). Ready to update.")
        self.status_label.setStyleSheet("color: #3dd68c; font-weight: bold; font-size: 11px;")
        if (target / "weights" / "corridorkey_v2.safetensors").exists():
            self.weights_check.setChecked(False)

    def _browse_install(self):
        d = QFileDialog.getExistingDirectory(self, "Select Install Directory", self.install_edit.text())
        if d:
            self.install_edit.setText(d)
            self._update_space(d)
            self._update_build_detection(d)

    def _browse_weights(self):
        d = QFileDialog.getExistingDirectory(self, "Select Weights Directory", self.weights_edit.text())
        if d:
            self.weights_edit.setText(d)

    def _start_install(self):
        self.install_btn.setEnabled(False)
        self.worker = InstallWorker(
            target_dir=Path(self.install_edit.text()).resolve(),
            weights_dir=Path(self.weights_edit.text()).resolve(),
            shortcut=self.shortcut_check.isChecked(),
            download_weights=self.weights_check.isChecked(),
            low_vram=self.low_vram_check.isChecked()
        )
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.log_received.connect(self._on_log)
        self.worker.install_finished.connect(self._on_finished)
        self.worker.start()

    @Slot(int, str)
    def _on_progress(self, val: int, msg: str):
        self.progress_bar.setValue(val)
        self.status_label.setText(msg)

    @Slot(str)
    def _on_log(self, text: str):
        self.log_text.append(text)

    @Slot(bool, str)
    def _on_finished(self, success: bool, msg: str):
        self.install_btn.setEnabled(True)
        if success:
            self.status_label.setText("Installation Complete!")
            self.status_label.setStyleSheet("color: #3dd68c; font-weight: bold;")
            self.install_btn.setText("Launch CorridorKey Studio")
            self.install_btn.clicked.disconnect()
            self.install_btn.clicked.connect(self._launch_app)
        else:
            self.status_label.setText("Installation Failed")
            self.status_label.setStyleSheet("color: #ff5c5c; font-weight: bold;")
            QMessageBox.critical(self, "Installation Failed", msg)

    def _launch_app(self):
        target = Path(self.install_edit.text()).resolve()
        script = target / "launch_gui.sh"
        subprocess.Popen([str(script)], cwd=str(target))
        self.accept()


def main():
    app = QApplication(sys.argv)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(13, 17, 23))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 246, 252))
    palette.setColor(QPalette.ColorRole.Base, QColor(22, 27, 34))
    palette.setColor(QPalette.ColorRole.Text, QColor(201, 209, 217))
    palette.setColor(QPalette.ColorRole.Button, QColor(33, 38, 45))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(240, 246, 252))
    app.setPalette(palette)

    win = InstallerWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
