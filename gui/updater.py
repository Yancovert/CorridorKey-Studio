from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from PySide6.QtCore import QThread, Signal


class UpdateCheckWorker(QThread):
    update_available = Signal(str, str, str, str)  # branch, remote_commit, local_commit, version
    up_to_date = Signal()
    check_failed = Signal(str)

    def __init__(self, app_root: Path):
        super().__init__()
        self.app_root = app_root

    def _read_local_version(self) -> tuple[str, str, str]:
        # strictly target platform branch: linux -> app-linux, windows -> app-win
        target_branch = "app-win" if sys.platform == "win32" else "app-linux"
        commit = "unknown"
        version = "2.1.0"
        build_file = self.app_root / ".build_version"
        if build_file.exists():
            try:
                for line in build_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("branch="):
                        b = line.split("=", 1)[1].strip()
                        if b in ("app-linux", "app-win"):
                            target_branch = b
                    elif line.startswith("commit="):
                        commit = line.split("=", 1)[1].strip()
                    elif line.startswith("version="):
                        version = line.split("=", 1)[1].strip()
            except Exception:
                pass
        return target_branch, commit, version

    def run(self):
        try:
            target_branch, local_commit, version = self._read_local_version()
            remote_repo = "https://github.com/Yancovert/CorridorKey-Studio.git"

            # query remote refs strictly for the platform branch
            cmd = ["git", "ls-remote", remote_repo, f"refs/heads/{target_branch}"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4.0)
            remote_commit = None

            if res.returncode == 0 and res.stdout.strip():
                parts = res.stdout.strip().split()
                if parts:
                    remote_commit = parts[0][:7]

            if not remote_commit:
                self.check_failed.emit(f"could not resolve remote {target_branch} branch commit")
                return

            local_short = local_commit[:7] if local_commit != "unknown" else ""
            if local_short and remote_commit == local_short:
                self.up_to_date.emit()
            else:
                self.update_available.emit(target_branch, remote_commit, local_short or "unknown", version)

        except Exception as e:
            self.check_failed.emit(str(e))


class UpdateInstallWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, app_root: Path, branch: str, remote_commit: str):
        super().__init__()
        self.app_root = app_root
        self.branch = branch
        self.remote_commit = remote_commit

    def run(self):
        try:
            self.progress.emit(10, "Checking local installation...")
            git_dir = self.app_root / ".git"

            if git_dir.is_dir():
                # git repository in-place pull strictly for platform branch
                self.progress.emit(30, f"Pulling latest commits from origin/{self.branch}...")
                pull_cmd = ["git", "-C", str(self.app_root), "pull", "origin", self.branch]
                res = subprocess.run(pull_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                if res.returncode != 0:
                    self.finished.emit(False, f"git pull from {self.branch} failed: {res.stderr.strip()}")
                    return
            else:
                # extracted directory update via zip archive strictly from platform branch
                self.progress.emit(25, f"Downloading update archive for {self.branch}...")
                archive_url = f"https://github.com/Yancovert/CorridorKey-Studio/archive/refs/heads/{self.branch}.zip"
                with tempfile.TemporaryDirectory() as tmp_dir:
                    zip_path = Path(tmp_dir) / "update.zip"
                    urllib.request.urlretrieve(archive_url, zip_path)

                    self.progress.emit(60, "Extracting updated source code...")
                    with zipfile.ZipFile(zip_path, "r") as z:
                        z.extractall(tmp_dir)

                    extracted_dirs = [d for d in Path(tmp_dir).iterdir() if d.is_dir() and d.name.startswith("CorridorKey-Studio")]
                    if not extracted_dirs:
                        self.finished.emit(False, "Failed to locate extracted update directory.")
                        return

                    source_dir = extracted_dirs[0]
                    self.progress.emit(80, "Applying code updates...")

                    # copy core application directories and files
                    sync_items = ["corridorkey", "gui", "scripts", "infer.py", "run_interactive.py", "launch_gui.sh", "launch_gui.bat", "requirements.txt"]
                    for item in sync_items:
                        src_item = source_dir / item
                        dst_item = self.app_root / item
                        if src_item.is_dir():
                            shutil.copytree(src_item, dst_item, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                        elif src_item.is_file():
                            shutil.copy2(src_item, dst_item)

            # update .build_version
            self.progress.emit(95, "Finalizing update version metadata...")
            version_file = self.app_root / ".build_version"
            version_content = f"branch={self.branch}\ncommit={self.remote_commit}\nversion=2.1.0\n"
            version_file.write_text(version_content, encoding="utf-8")

            self.progress.emit(100, "Update complete!")
            self.finished.emit(True, f"Successfully updated to {self.branch} ({self.remote_commit[:7]}).")

        except Exception as e:
            self.finished.emit(False, f"Update failed: {str(e)}")
