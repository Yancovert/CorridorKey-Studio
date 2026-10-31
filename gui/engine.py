from __future__ import annotations

import os
import re
import sys
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage, QPixmap
import cv2


class KeyerEngineWorker(QThread):
    progress_changed = Signal(int, int, str) # current, total, status
    log_received = Signal(str)
    frame_preview_ready = Signal(object, object) # original, keyed
    preview_bundle_ready = Signal(dict) # dict containing all preview modes
    finished = Signal(bool, str, dict) # success, message, outputs

    def __init__(
        self,
        input_path: str,
        output_dir: str,
        low_vram: bool = True,
        hann_chunk: int = 8,
        hann_stride: int = 4,
        hint_first_frame: str | None = None,
        hint_video: str | None = None,
        despill_strength: float = 0.5,
        blender_preset: str = "prores4444", # "prores4444", "png_seq", "exr_seq", "standard"
        generate_blender_script: bool = True,
        model_scale: float = 1.0,
        start_mode: str = "begin",
        stage2_batch: int = 1,
        low_vram_foundation_chunk: int = 4,
        low_vram_swin_window_batch: int = 16,
        carry_hint: bool = True,
        hint_quality: float = 0.95,
        cutout_linear: bool = False,
        linear_contrast: float = 1.0,
        linear_contrast_pivot: float = 0.18,
        output_format: str = "video",
        exr_dtype: str = "half",
        crf: int = 12,
        pix_fmt: str = "yuv444p10le",
        num_frames: int = -1,
        seed: int = 0,
        carry_hint_quality: float = 0.95,
        linear_brightness: float = 1.0,
        frame_dir_fps: float = 24.0,
        frame_dir_linear: bool = False,
        temp_dir: str | None = None,
        low_vram_enc_frame_chunk: int = 1,
        low_vram_mlp_chunk_tokens: int = 65536,
        low_vram_full_attn_query_chunk_tokens: int = 2048,
        ffmpeg_codec: str = "libx264",
        preset: str = "medium",
        bitrate: str | None = None,
        ffmpeg_threads: int = 2,
        parent=None,
    ):
        super().__init__(parent)
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.low_vram = low_vram
        self.hann_chunk = hann_chunk
        self.hann_stride = hann_stride
        self.hint_first_frame = hint_first_frame
        self.hint_video = hint_video
        self.despill_strength = despill_strength
        self.blender_preset = blender_preset
        self.generate_blender_script = generate_blender_script
        self.model_scale = model_scale
        self.start_mode = start_mode
        self.stage2_batch = stage2_batch
        self.low_vram_foundation_chunk = low_vram_foundation_chunk
        self.low_vram_swin_window_batch = low_vram_swin_window_batch
        self.carry_hint = carry_hint
        self.hint_quality = hint_quality
        self.cutout_linear = cutout_linear
        self.linear_contrast = linear_contrast
        self.linear_contrast_pivot = linear_contrast_pivot
        self.output_format = output_format
        self.exr_dtype = exr_dtype
        self.crf = crf
        self.pix_fmt = pix_fmt
        self.num_frames = num_frames
        self.seed = seed
        self.carry_hint_quality = carry_hint_quality
        self.linear_brightness = linear_brightness
        self.frame_dir_fps = frame_dir_fps
        self.frame_dir_linear = frame_dir_linear
        self.temp_dir = temp_dir
        self.low_vram_enc_frame_chunk = low_vram_enc_frame_chunk
        self.low_vram_mlp_chunk_tokens = low_vram_mlp_chunk_tokens
        self.low_vram_full_attn_query_chunk_tokens = low_vram_full_attn_query_chunk_tokens
        self.ffmpeg_codec = ffmpeg_codec
        self.preset = preset
        self.bitrate = bitrate
        self.ffmpeg_threads = ffmpeg_threads

        self._process: subprocess.Popen | None = None
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        if self._process and self._process.poll() is None:
            # terminate child process and all ffmpeg pipes
            try:
                self._process.terminate()
            except Exception:
                pass

    def run(self):
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.log_received.emit(f"initializing keying for: {self.input_path.name}")
            self.progress_changed.emit(0, 100, "Preparing inference...")

            repo_root = Path(__file__).resolve().parents[1]
            infer_script = repo_root / "infer.py"

            # craft inference command
            cmd = [
                sys.executable,
                str(infer_script),
                "--input", str(self.input_path),
                "--output_dir", str(self.output_dir),
                "--outputs", "alpha", "fg", "checker", "cutout",
                "--despill_strength", str(self.despill_strength),
            ]

            if self.model_scale != 1.0:
                cmd.extend(["--model_scale", str(self.model_scale)])

            if self.start_mode and self.start_mode != "begin":
                cmd.extend(["--start_mode", str(self.start_mode)])

            if self.stage2_batch and self.stage2_batch != 1:
                cmd.extend(["--stage2_batch", str(self.stage2_batch)])

            if not self.carry_hint:
                cmd.append("--no_carry_hint")

            if abs(self.hint_quality - 0.95) > 1e-4:
                cmd.extend(["--hint_quality", str(self.hint_quality)])

            if self.cutout_linear or self.blender_preset == "exr_seq":
                cmd.append("--cutout_linear")

            if abs(self.linear_contrast - 1.0) > 1e-4:
                cmd.extend(["--linear_contrast", str(self.linear_contrast)])

            if abs(self.linear_contrast_pivot - 0.18) > 1e-4:
                cmd.extend(["--linear_contrast_pivot", str(self.linear_contrast_pivot)])

            effective_format = "exr" if self.blender_preset == "exr_seq" else self.output_format
            if effective_format == "exr":
                cmd.extend(["--output_format", "exr", "--exr_dtype", self.exr_dtype])

            if self.pix_fmt and self.pix_fmt != "yuv444p10le":
                cmd.extend(["--pix_fmt", self.pix_fmt])

            if self.crf != 12:
                cmd.extend(["--crf", str(self.crf)])

            if self.low_vram:
                cmd.append("--low_vram")
                if self.low_vram_foundation_chunk != 4:
                    cmd.extend(["--low_vram_foundation_chunk", str(self.low_vram_foundation_chunk)])
                if self.low_vram_swin_window_batch != 16:
                    cmd.extend(["--low_vram_swin_window_batch", str(self.low_vram_swin_window_batch)])

            if self.hann_chunk:
                cmd.extend(["--hann_chunk", str(self.hann_chunk)])
            if self.hann_stride:
                cmd.extend(["--hann_stride", str(self.hann_stride)])

            if self.hint_first_frame:
                cmd.extend(["--hint_first_frame", str(self.hint_first_frame)])
            elif self.hint_video:
                cmd.extend(["--hint_video", str(self.hint_video)])

            if self.num_frames > 0:
                cmd.extend(["--num_frames", str(self.num_frames)])
            if self.seed != 0:
                cmd.extend(["--seed", str(self.seed)])
            if abs(self.carry_hint_quality - 0.95) > 1e-4:
                cmd.extend(["--carry_hint_quality", str(self.carry_hint_quality)])
            if abs(self.linear_brightness - 1.0) > 1e-4:
                cmd.extend(["--linear_brightness", str(self.linear_brightness)])
            if self.frame_dir_fps != 24.0:
                cmd.extend(["--frame_dir_fps", str(self.frame_dir_fps)])
            if self.frame_dir_linear:
                cmd.append("--frame_dir_linear")
            if self.temp_dir:
                cmd.extend(["--temp_dir", str(self.temp_dir)])

            if self.low_vram:
                if self.low_vram_enc_frame_chunk != 1:
                    cmd.extend(["--low_vram_enc_frame_chunk", str(self.low_vram_enc_frame_chunk)])
                if self.low_vram_mlp_chunk_tokens != 65536:
                    cmd.extend(["--low_vram_mlp_chunk_tokens", str(self.low_vram_mlp_chunk_tokens)])
                if self.low_vram_full_attn_query_chunk_tokens != 2048:
                    cmd.extend(["--low_vram_full_attn_query_chunk_tokens", str(self.low_vram_full_attn_query_chunk_tokens)])

            if self.ffmpeg_codec and self.ffmpeg_codec != "libx264":
                cmd.extend(["--ffmpeg_codec", self.ffmpeg_codec])
            if self.preset and self.preset != "medium":
                cmd.extend(["--preset", self.preset])
            if self.bitrate:
                cmd.extend(["--bitrate", self.bitrate])
            if self.ffmpeg_threads != 2:
                cmd.extend(["--ffmpeg_threads", str(self.ffmpeg_threads)])

            self.log_received.emit("executing: " + " ".join(cmd))

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(repo_root),
                env=env,
            )

            current_frame = 0
            total_frames = 100
            tqdm_pattern = re.compile(r"(\d+)/(\d+)")

            for line in self._process.stdout:
                if self._is_cancelled:
                    break
                clean_line = line.strip()
                if not clean_line:
                    continue
                self.log_received.emit(clean_line)

                # parse stage progress and sliding window progress
                if "Loading CorridorKey v2 runtime weights" in clean_line:
                    self.progress_changed.emit(5, 100, "Loading foundation weights into VRAM (~5 GB)...")
                elif "RVM continuous prepass" in clean_line:
                    self.progress_changed.emit(15, 100, "Stage 1/3: RVM recurrent temporal prepass...")
                elif "frozen VFM prepass" in clean_line:
                    self.progress_changed.emit(35, 100, "Stage 2/3: Extracting C-RADIO & MoGe geometry features...")
                elif "Hann stage1" in clean_line:
                    self.progress_changed.emit(50, 100, "Stage 3/3: Running temporal transformer attention...")
                elif "window" in clean_line and match:
                    try:
                        cur = int(match.group(1))
                        tot = int(match.group(2))
                        if tot > 0:
                            pct = 50 + int((cur / tot) * 45)
                            self.progress_changed.emit(pct, 100, f"Processing window {cur}/{tot} ({int(cur/tot*100)}%)")
                    except ValueError:
                        pass
                elif "wrote" in clean_line and "output video" in clean_line:
                    self.progress_changed.emit(95, 100, "Finalizing outputs and encoding containers...")
                elif match:
                    try:
                        cur = int(match.group(1))
                        tot = int(match.group(2))
                        if tot > 0:
                            self.progress_changed.emit(cur, tot, f"Processing {cur}/{tot}")
                    except ValueError:
                        pass

            self._process.wait()

            if self._is_cancelled:
                self.finished.emit(False, "Process cancelled by user.", {})
                return

            if self._process.returncode != 0:
                self.finished.emit(False, f"Inference failed with code {self._process.returncode}", {})
                return

            self.progress_changed.emit(total_frames, total_frames, "Finalizing outputs...")

            # find generated preview videos
            stem = self.input_path.stem
            alpha_path = self.output_dir / f"{stem}_alpha.mp4"
            fg_path = self.output_dir / f"{stem}_fg.mp4"
            cutout_path = self.output_dir / f"{stem}_cutout.mov"
            if not cutout_path.exists():
                alt_cutout = self.output_dir / f"{stem}_cutout.mp4"
                if alt_cutout.exists():
                    cutout_path = alt_cutout

            # generate deliverables if selected
            from .blender_export import (
                export_prores4444_rgba, export_png_rgba_sequence,
                export_webm_vp9_rgba, export_qtrle_rgba,
                export_tiff_rgba_sequence, export_davinci_pack,
                generate_blender_import_script
            )

            output_summary = {
                "alpha": str(alpha_path) if alpha_path.exists() else None,
                "fg": str(fg_path) if fg_path.exists() else None,
                "cutout": str(cutout_path) if cutout_path.exists() else None,
            }

            if self.blender_preset == "prores4444" and fg_path.exists() and alpha_path.exists():
                self.log_received.emit("encoding blender prores 4444 rgba container...")
                prores_file = self.output_dir / f"{stem}_keyed_prores4444.mov"
                if export_prores4444_rgba(fg_path, alpha_path, prores_file):
                    output_summary["prores4444"] = str(prores_file)
                    self.log_received.emit(f"created: {prores_file.name}")
                    if self.generate_blender_script:
                        script_path = self.output_dir / "import_to_blender.py"
                        generate_blender_import_script(prores_file, script_path, is_sequence=False)
                        output_summary["blender_script"] = str(script_path)

            elif self.blender_preset == "png_seq" and fg_path.exists() and alpha_path.exists():
                self.log_received.emit("exporting blender transparent png sequence...")
                png_seq_dir = self.output_dir / f"{stem}_png_sequence"
                if export_png_rgba_sequence(fg_path, alpha_path, png_seq_dir):
                    output_summary["png_sequence"] = str(png_seq_dir)
                    self.log_received.emit(f"created png sequence in: {png_seq_dir.name}")
                    if self.generate_blender_script:
                        script_path = self.output_dir / "import_to_blender.py"
                        generate_blender_import_script(png_seq_dir / "frame_00001.png", script_path, is_sequence=True)
                        output_summary["blender_script"] = str(script_path)

            elif self.blender_preset == "webm_vp9" and fg_path.exists() and alpha_path.exists():
                self.log_received.emit("encoding webm vp9 transparent video...")
                webm_file = self.output_dir / f"{stem}_keyed_vp9.webm"
                if export_webm_vp9_rgba(fg_path, alpha_path, webm_file):
                    output_summary["webm_vp9"] = str(webm_file)
                    self.log_received.emit(f"created: {webm_file.name}")

            elif self.blender_preset == "qtrle" and fg_path.exists() and alpha_path.exists():
                self.log_received.emit("encoding quicktime animation lossless rgba container...")
                qtrle_file = self.output_dir / f"{stem}_keyed_animation.mov"
                if export_qtrle_rgba(fg_path, alpha_path, qtrle_file):
                    output_summary["qtrle"] = str(qtrle_file)
                    self.log_received.emit(f"created: {qtrle_file.name}")

            elif self.blender_preset == "tiff_seq" and fg_path.exists() and alpha_path.exists():
                self.log_received.emit("exporting 16-bit uncompressed tiff sequence...")
                tiff_dir = self.output_dir / f"{stem}_tiff_sequence"
                if export_tiff_rgba_sequence(fg_path, alpha_path, tiff_dir):
                    output_summary["tiff_sequence"] = str(tiff_dir)
                    self.log_received.emit(f"created tiff sequence in: {tiff_dir.name}")

            elif self.blender_preset == "davinci_pack" and fg_path.exists() and alpha_path.exists():
                self.log_received.emit("exporting davinci resolve dual-track matte & fill pack...")
                fill_file = self.output_dir / f"{stem}_fill_prores422hq.mov"
                matte_file = self.output_dir / f"{stem}_matte_prores422.mov"
                if export_davinci_pack(fg_path, alpha_path, fill_file, matte_file):
                    output_summary["davinci_fill"] = str(fill_file)
                    output_summary["davinci_matte"] = str(matte_file)
                    self.log_received.emit(f"created: {fill_file.name} and {matte_file.name}")

            # extract preview frames from outputs to update canvas
            self._load_and_emit_preview_frames(alpha_path, fg_path, cutout_path)

            self.finished.emit(True, "Keying complete! Deliverables generated.", output_summary)

        except Exception as e:
            self.finished.emit(False, str(e), {})

    def _load_and_emit_preview_frames(self, alpha_path: Path, fg_path: Path, cutout_path: Path):
        try:
            stem = self.input_path.stem
            despill_tag = int(self.despill_strength * 100)
            checker_path = self.output_dir / f"{stem}_checker_comp_despill{despill_tag:03d}.mp4"
            if not checker_path.exists():
                candidates = list(self.output_dir.glob(f"{stem}_checker_comp_*.mp4"))
                if candidates:
                    checker_path = candidates[0]

            def read_frame(p: Path):
                if not p.exists():
                    return None
                cap = cv2.VideoCapture(str(p))
                ret, frame = cap.read()
                cap.release()
                return frame if ret else None

            def bgr_to_pixmap(bgr):
                if bgr is None:
                    return None
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
                return QPixmap.fromImage(qimg.copy())

            frame_orig = read_frame(self.input_path)
            frame_alpha = read_frame(alpha_path)
            frame_fg = read_frame(fg_path)
            frame_checker = read_frame(checker_path)

            pm_orig = bgr_to_pixmap(frame_orig)
            pm_alpha = bgr_to_pixmap(frame_alpha)
            pm_fg = bgr_to_pixmap(frame_fg)
            pm_checker = bgr_to_pixmap(frame_checker)

            # merge fg + alpha into transparent rgba cutout
            pm_cutout = None
            if frame_fg is not None and frame_alpha is not None:
                b, g, r = cv2.split(frame_fg)
                if len(frame_alpha.shape) == 3:
                    a = cv2.cvtColor(frame_alpha, cv2.COLOR_BGR2GRAY)
                else:
                    a = frame_alpha
                if a.shape[:2] != frame_fg.shape[:2]:
                    a = cv2.resize(a, (frame_fg.shape[1], frame_fg.shape[0]), interpolation=cv2.INTER_LINEAR)
                rgba = cv2.merge([r, g, b, a])
                h, w, ch = rgba.shape
                qimg_rgba = QImage(rgba.data, w, h, ch * w, QImage.Format.Format_RGBA8888)
                pm_cutout = QPixmap.fromImage(qimg_rgba.copy())
            elif pm_checker is not None:
                pm_cutout = pm_checker

            bundle = {
                "original": pm_orig,
                "cutout": pm_cutout,
                "alpha": pm_alpha,
                "fg": pm_fg,
                "checker": pm_checker,
            }
            self.preview_bundle_ready.emit(bundle)
            self.frame_preview_ready.emit(pm_orig, pm_cutout)
        except Exception:
            pass
