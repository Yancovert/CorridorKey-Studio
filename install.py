#!/usr/bin/env python3
"""corridorkey studio installer.

auto-detects operating system, verifies nvidia cuda environment,
sets up virtual environment, installs dependencies, and creates desktop launchers.
"""

from __future__ import annotations

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / "venv"


def log(step: str, msg: str):
    print(f"[{step}] {msg}")


def check_python_version():
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        print(f"error: python 3.10 or newer is required (detected {major}.{minor}).")
        sys.exit(1)


def check_hardware():
    log("1/5", "detecting hardware and system environment...")
    system = platform.system()
    print(f"  os: {system} {platform.release()} ({platform.machine()})")

    if system not in ("Linux", "Windows"):
        print("  warning: corridorkey 2.0 is tested on linux and windows.")

    # check nvidia gpu
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        print("  warning: nvidia-smi not found. an nvidia rtx gpu with cuda is required for inference.")
    else:
        try:
            res = subprocess.run([nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, check=True)
            gpu_info = res.stdout.strip()
            print(f"  gpu: {gpu_info}")
        except Exception:
            print("  gpu: nvidia device detected")

    # check ffmpeg
    if not shutil.which("ffmpeg"):
        print("  warning: ffmpeg not found on path. ffmpeg is required for video decoding and prores export.")
    else:
        print("  ffmpeg: available on path")


def setup_venv() -> Path:
    log("2/5", "configuring python virtual environment...")
    py_bin = VENV_DIR / ("Scripts" if sys.platform == "win32" else "bin") / "python"

    if VENV_DIR.exists() and py_bin.exists():
        print(f"  venv already exists at {VENV_DIR.name}")
        return py_bin

    has_uv = shutil.which("uv") is not None
    if has_uv:
        # use uv for fast virtualenv creation
        cmd = ["uv", "venv", str(VENV_DIR), "--python", f"{sys.version_info.major}.{sys.version_info.minor}"]
    else:
        cmd = [sys.executable, "-m", "venv", str(VENV_DIR)]

    subprocess.run(cmd, check=True, cwd=str(ROOT_DIR))
    return py_bin


def install_dependencies(py_bin: Path):
    log("3/5", "installing pytorch cuda and application packages...")
    has_uv = shutil.which("uv") is not None

    if has_uv:
        # install torch cuda first
        print("  installing pytorch with cuda 12.8 support via uv...")
        cmd_torch = [
            "uv", "pip", "install",
            "torch", "torchvision",
            "--index-url", "https://download.pytorch.org/whl/cu128",
            "--python", str(py_bin)
        ]
        subprocess.run(cmd_torch, check=True, cwd=str(ROOT_DIR))

        # install requirements and pyside6
        print("  installing application requirements and pyside6...")
        cmd_reqs = [
            "uv", "pip", "install",
            "-r", "requirements.txt",
            "PySide6",
            "--python", str(py_bin)
        ]
        subprocess.run(cmd_reqs, check=True, cwd=str(ROOT_DIR))
    else:
        print("  installing pytorch with cuda 12.8 support via pip...")
        pip_bin = py_bin.parent / ("pip.exe" if sys.platform == "win32" else "pip")
        cmd_torch = [
            str(pip_bin), "install",
            "torch", "torchvision",
            "--index-url", "https://download.pytorch.org/whl/cu128"
        ]
        subprocess.run(cmd_torch, check=True, cwd=str(ROOT_DIR))

        print("  installing application requirements and pyside6...")
        cmd_reqs = [
            str(pip_bin), "install",
            "-r", "requirements.txt",
            "PySide6"
        ]
        subprocess.run(cmd_reqs, check=True, cwd=str(ROOT_DIR))


def verify_weights(py_bin: Path):
    log("4/5", "verifying foundation model weights...")
    weights_file = ROOT_DIR / "weights" / "corridorkey_v2.safetensors"
    cradio_dir = ROOT_DIR / "vfms" / "cradio" / "C-RADIOv4-SO400M"

    if weights_file.exists() and cradio_dir.exists():
        print("  model weights already present and verified.")
        return

    print("  weights missing or incomplete. running weight downloader (~5 gb)...")
    download_script = ROOT_DIR / "scripts" / "download_weights.py"
    subprocess.run([str(py_bin), str(download_script)], check=True, cwd=str(ROOT_DIR))


def setup_desktop_launcher(py_bin: Path):
    log("5/5", "setting up desktop launcher...")
    system = platform.system()
    icon_path = ROOT_DIR / "gui" / "icon.png"

    if system == "Linux":
        apps_dir = Path.home() / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = apps_dir / "corridorkey-studio.desktop"

        launcher_sh = ROOT_DIR / "launch_gui.sh"
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
        print(f"  created desktop entry: {desktop_file}")

    elif system == "Windows":
        # create windows desktop batch shortcut
        desktop_dir = Path.home() / "Desktop"
        if desktop_dir.exists():
            shortcut_bat = desktop_dir / "CorridorKey-Studio.bat"
            with open(shortcut_bat, "w", encoding="utf-8") as f:
                f.write(f'@echo off\ncall "{ROOT_DIR / "launch_gui.bat"}"\n')
            print(f"  created desktop shortcut: {shortcut_bat}")

    print("\ninstallation complete! run with: ./launch_gui.sh")


def main():
    print("========================================")
    print("      CorridorKey Studio Installer      ")
    print("========================================")
    check_python_version()
    check_hardware()
    py_bin = setup_venv()
    install_dependencies(py_bin)
    verify_weights(py_bin)
    setup_desktop_launcher(py_bin)


if __name__ == "__main__":
    main()
