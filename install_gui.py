#!/usr/bin/env python3
"""corridorkey studio graphical installer.

lightweight, dependency-free installer using standard library tkinter.
allows selecting directories, configuration options, and running installation with live progress.
"""

from __future__ import annotations

import os
import sys
import shutil
import platform
import threading
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


ROOT_DIR = Path(__file__).resolve().parent


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CorridorKey Studio Installer")
        self.geometry("640x580")
        self.minsize(580, 520)
        self.configure(bg="#0d1117")

        self.install_dir_var = tk.StringVar(value=str(ROOT_DIR))
        self.weights_dir_var = tk.StringVar(value=str(ROOT_DIR / "weights"))
        self.shortcut_var = tk.BooleanVar(value=True)
        self.download_weights_var = tk.BooleanVar(value=True)
        self.low_vram_var = tk.BooleanVar(value=True)

        self.is_installing = False
        self._setup_styles()
        self._build_ui()
        self._detect_environment()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TProgressbar", thickness=10, troughcolor="#161b22", background="#238636")

    def _build_ui(self):
        # 1. header
        header_frame = tk.Frame(self, bg="#161b22", pady=14, padx=18)
        header_frame.pack(fill="x")

        title = tk.Label(header_frame, text="CorridorKey Studio Setup", font=("Helvetica", 15, "bold"), fg="#f0f6fc", bg="#161b22")
        title.pack(anchor="w")

        self.subtitle = tk.Label(header_frame, text="Detecting environment...", font=("Helvetica", 9), fg="#8b949e", bg="#161b22")
        self.subtitle.pack(anchor="w", pady=(2, 0))

        # 2. main settings content
        content = tk.Frame(self, bg="#0d1117", padx=18, pady=12)
        content.pack(fill="both", expand=True)

        # installation directory
        dir_label = tk.Label(content, text="Installation Directory:", font=("Helvetica", 10, "bold"), fg="#c9d1d9", bg="#0d1117")
        dir_label.pack(anchor="w")

        dir_frame = tk.Frame(content, bg="#0d1117")
        dir_frame.pack(fill="x", pady=(4, 10))

        self.dir_entry = tk.Entry(dir_frame, textvariable=self.install_dir_var, bg="#161b22", fg="#f0f6fc", insertbackground="white", relief="flat")
        self.dir_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

        dir_btn = tk.Button(dir_frame, text="Browse...", command=self._browse_install_dir, bg="#21262d", fg="#c9d1d9", relief="flat", padx=10)
        dir_btn.pack(side="right")

        # weights directory
        weights_label = tk.Label(content, text="Model Weights & Cache Directory:", font=("Helvetica", 10, "bold"), fg="#c9d1d9", bg="#0d1117")
        weights_label.pack(anchor="w")

        weights_frame = tk.Frame(content, bg="#0d1117")
        weights_frame.pack(fill="x", pady=(4, 12))

        self.weights_entry = tk.Entry(weights_frame, textvariable=self.weights_dir_var, bg="#161b22", fg="#f0f6fc", insertbackground="white", relief="flat")
        self.weights_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

        weights_btn = tk.Button(weights_frame, text="Browse...", command=self._browse_weights_dir, bg="#21262d", fg="#c9d1d9", relief="flat", padx=10)
        weights_btn.pack(side="right")

        # options frame
        options_frame = tk.LabelFrame(content, text=" Options & Preferences ", font=("Helvetica", 10, "bold"), fg="#8b949e", bg="#0d1117", padx=10, pady=8)
        options_frame.pack(fill="x", pady=(0, 10))

        cb1 = tk.Checkbutton(options_frame, text="Create Desktop / Application Menu Launcher", variable=self.shortcut_var, bg="#0d1117", fg="#c9d1d9", selectcolor="#161b22", activebackground="#0d1117", activeforeground="#f0f6fc")
        cb1.pack(anchor="w", pady=2)

        cb2 = tk.Checkbutton(options_frame, text="Download ~5 GB foundation models immediately (CorridorKey, C-RADIO, MoGe, RVM)", variable=self.download_weights_var, bg="#0d1117", fg="#c9d1d9", selectcolor="#161b22", activebackground="#0d1117", activeforeground="#f0f6fc")
        cb2.pack(anchor="w", pady=2)

        cb3 = tk.Checkbutton(options_frame, text="Enable 4GB Low-VRAM safety mode by default", variable=self.low_vram_var, bg="#0d1117", fg="#c9d1d9", selectcolor="#161b22", activebackground="#0d1117", activeforeground="#f0f6fc")
        cb3.pack(anchor="w", pady=2)

        # log and progress
        self.status_label = tk.Label(content, text="Ready to install.", font=("Helvetica", 9), fg="#8b949e", bg="#0d1117")
        self.status_label.pack(anchor="w", pady=(0, 4))

        self.progress = ttk.Progressbar(content, style="TProgressbar", mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))

        self.log_text = tk.Text(content, height=6, bg="#161b22", fg="#8b949e", insertbackground="white", relief="flat", font=("Consolas", 8))
        self.log_text.pack(fill="both", expand=True, pady=(0, 10))

        # 3. bottom button bar
        footer = tk.Frame(self, bg="#161b22", padx=18, pady=10)
        footer.pack(fill="x", side="bottom")

        self.install_btn = tk.Button(footer, text="Begin Installation", command=self._start_install_thread, font=("Helvetica", 10, "bold"), bg="#238636", fg="white", activebackground="#2ea043", relief="flat", padx=16, pady=6)
        self.install_btn.pack(side="right")

        self.cancel_btn = tk.Button(footer, text="Exit", command=self.destroy, bg="#21262d", fg="#c9d1d9", relief="flat", padx=12, pady=6)
        self.cancel_btn.pack(side="right", padx=(0, 8))

    def _detect_environment(self):
        sys_name = platform.system()
        arch = platform.machine()
        gpu_name = "No NVIDIA GPU found"
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                res = subprocess.run([nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    gpu_name = res.stdout.strip()
            except Exception:
                gpu_name = "NVIDIA Device Detected"

        self.subtitle.config(text=f"Platform: {sys_name} ({arch}) | GPU: {gpu_name}")
        self._log(f"detected environment: {sys_name} ({arch})")
        self._log(f"gpu: {gpu_name}")

    def _browse_install_dir(self):
        d = filedialog.askdirectory(initialdir=self.install_dir_var.get())
        if d:
            self.install_dir_var.set(d)

    def _browse_weights_dir(self):
        d = filedialog.askdirectory(initialdir=self.weights_dir_var.get())
        if d:
            self.weights_dir_var.set(d)

    def _log(self, text: str):
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def _start_install_thread(self):
        if self.is_installing:
            return
        self.is_installing = True
        self.install_btn.config(state="disabled")
        t = threading.Thread(target=self._run_install, daemon=True)
        t.start()

    def _run_install(self):
        try:
            target_dir = Path(self.install_dir_var.get()).resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            venv_dir = target_dir / "venv"

            # 1. venv setup
            self.status_label.config(text="Step 1/4: Setting up virtual environment...")
            self.progress["value"] = 15
            self._log(f"creating venv in {venv_dir}...")

            py_bin = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
            if not py_bin.exists():
                has_uv = shutil.which("uv") is not None
                if has_uv:
                    cmd = ["uv", "venv", str(venv_dir), "--python", f"{sys.version_info.major}.{sys.version_info.minor}"]
                else:
                    cmd = [sys.executable, "-m", "venv", str(venv_dir)]
                subprocess.run(cmd, check=True, cwd=str(target_dir))

            # 2. pytorch & packages
            self.status_label.config(text="Step 2/4: Installing PyTorch CUDA and dependencies...")
            self.progress["value"] = 40
            self._log("installing pytorch with cuda 12.8 support...")

            has_uv = shutil.which("uv") is not None
            if has_uv:
                subprocess.run([
                    "uv", "pip", "install", "torch", "torchvision",
                    "--index-url", "https://download.pytorch.org/whl/cu128",
                    "--python", str(py_bin)
                ], check=True, cwd=str(target_dir))

                self._log("installing application requirements and pyside6...")
                subprocess.run([
                    "uv", "pip", "install", "-r", str(target_dir / "requirements.txt"),
                    "PySide6", "--python", str(py_bin)
                ], check=True, cwd=str(target_dir))
            else:
                pip_bin = py_bin.parent / ("pip.exe" if sys.platform == "win32" else "pip")
                subprocess.run([
                    str(pip_bin), "install", "torch", "torchvision",
                    "--index-url", "https://download.pytorch.org/whl/cu128"
                ], check=True, cwd=str(target_dir))

                subprocess.run([
                    str(pip_bin), "install", "-r", str(target_dir / "requirements.txt"), "PySide6"
                ], check=True, cwd=str(target_dir))

            # 3. foundation model weights
            if self.download_weights_var.get():
                self.status_label.config(text="Step 3/4: Verifying/downloading foundation models...")
                self.progress["value"] = 75
                self._log("checking weights under weights/ and vfms/...")
                download_script = target_dir / "scripts" / "download_weights.py"
                if download_script.exists():
                    subprocess.run([str(py_bin), str(download_script)], check=True, cwd=str(target_dir))
            else:
                self.progress["value"] = 75

            # 4. desktop shortcut
            if self.shortcut_var.get():
                self.status_label.config(text="Step 4/4: Registering application launcher...")
                self.progress["value"] = 90
                icon_path = target_dir / "gui" / "icon.png"
                if sys.platform.startswith("linux"):
                    apps_dir = Path.home() / ".local" / "share" / "applications"
                    apps_dir.mkdir(parents=True, exist_ok=True)
                    desktop_file = apps_dir / "corridorkey-studio.desktop"
                    launcher_sh = target_dir / "launch_gui.sh"
                    desktop_entry = f"""[Desktop Entry]
Type=Application
Name=CorridorKey Studio
Comment=AI-Powered Video Matting and Chroma Keying Suite
Exec={launcher_sh}
Icon={icon_path}
Terminal=false
Categories=Graphics;Video;AudioVideo;
StartupNotify=true
"""
                    with open(desktop_file, "w", encoding="utf-8") as f:
                        f.write(desktop_entry)
                    desktop_file.chmod(0o755)
                    self._log(f"created desktop entry: {desktop_file}")

            self.progress["value"] = 100
            self.status_label.config(text="Installation Complete!", fg="#3dd68c")
            self._log("installation finished successfully!")

            # switch button to launch
            self.install_btn.config(text="Launch CorridorKey Studio", command=self._launch_app, state="normal", bg="#3dd68c", fg="#0d1117")

        except Exception as e:
            self.status_label.config(text="Installation failed", fg="#ff5c5c")
            self._log(f"error: {str(e)}")
            messagebox.showerror("Installation Error", f"Installation encountered an error:\n{str(e)}")
            self.install_btn.config(state="normal")
        finally:
            self.is_installing = False

    def _launch_app(self):
        target_dir = Path(self.install_dir_var.get()).resolve()
        if sys.platform == "win32":
            subprocess.Popen([str(target_dir / "launch_gui.bat")], cwd=str(target_dir), shell=True)
        else:
            subprocess.Popen([str(target_dir / "launch_gui.sh")], cwd=str(target_dir))
        self.destroy()


def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
