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

    def _extract_zip_archive(self):
        archive_url = f"https://github.com/Yancovert/CorridorKey-Studio/archive/refs/heads/{self.branch}.zip"
        self.progress.emit(20, f"Connecting to GitHub ({self.branch})...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "update.zip"

            opener = urllib.request.build_opener()
            opener.addheaders = [("User-Agent", "CorridorKey-Studio/2.1.0")]
            urllib.request.install_opener(opener)

            def _dl_hook(blocks_done: int, block_size: int, total_size: int):
                if total_size > 0:
                    downloaded = blocks_done * block_size
                    pct = int(20 + min(1.0, downloaded / total_size) * 50)
                    cur_mb = downloaded / (1024 * 1024)
                    tot_mb = total_size / (1024 * 1024)
                    self.progress.emit(min(pct, 70), f"Downloading update ({cur_mb:.1f} / {tot_mb:.1f} MB)...")
                else:
                    self.progress.emit(35, f"Downloading update package for {self.branch}...")

            urllib.request.urlretrieve(archive_url, zip_path, reporthook=_dl_hook)

            self.progress.emit(72, "Extracting updated source files...")
            with zipfile.ZipFile(zip_path, "r") as z:
                members = z.infolist()
                total_files = len(members)
                for idx, member in enumerate(members):
                    z.extract(member, tmp_dir)
                    if total_files > 0 and (idx % max(1, total_files // 10) == 0 or idx == total_files - 1):
                        ext_pct = int(72 + ((idx + 1) / total_files) * 14)
                        self.progress.emit(ext_pct, f"Extracting files ({idx + 1}/{total_files})...")

            extracted_dirs = [d for d in Path(tmp_dir).iterdir() if d.is_dir() and d.name.startswith("CorridorKey-Studio")]
            if not extracted_dirs:
                raise RuntimeError("Failed to locate extracted update directory.")

            source_dir = extracted_dirs[0]
            self.progress.emit(88, "Applying files to application directory...")

            sync_items = ["corridorkey", "gui", "scripts", "infer.py", "run_interactive.py", "launch_gui.sh", "launch_gui.bat", "requirements.txt"]
            for idx, item in enumerate(sync_items):
                src_item = source_dir / item
                dst_item = self.app_root / item
                if src_item.is_dir():
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                elif src_item.is_file():
                    shutil.copy2(src_item, dst_item)
                apply_pct = int(88 + ((idx + 1) / len(sync_items)) * 7)
                self.progress.emit(apply_pct, f"Applying {item}...")

    def run(self):
        try:
            self.progress.emit(10, "Verifying local installation...")
            git_dir = self.app_root / ".git"

            updated_via_git = False
            if git_dir.is_dir():
                try:
                    self.progress.emit(25, f"Syncing latest commits from {self.branch}...")
                    pull_cmd = [
                        "git", "-C", str(self.app_root), "pull", "--no-rebase",
                        "https://github.com/Yancovert/CorridorKey-Studio.git", self.branch
                    ]
                    res = subprocess.run(pull_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                    if res.returncode == 0:
                        updated_via_git = True
                        self.progress.emit(85, "Git sync complete. Finalizing update...")
                    else:
                        self.progress.emit(20, "Git sync conflict, switching to package download...")
                except Exception:
                    pass

            if not updated_via_git:
                self._extract_zip_archive()

            self.progress.emit(96, "Updating version stamp...")
            version_file = self.app_root / ".build_version"
            version_content = f"branch={self.branch}\ncommit={self.remote_commit}\nversion=2.1.0\n"
            version_file.write_text(version_content, encoding="utf-8")

            self.progress.emit(100, f"Successfully updated to {self.branch} ({self.remote_commit[:7]}).")
            self.finished.emit(True, f"Updated to {self.branch} ({self.remote_commit[:7]}). Ready to restart.")

        except Exception as e:
            self.finished.emit(False, str(e))
