from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class GpuProfile:
    name: str
    total_vram_gb: float
    free_vram_gb: float
    is_cuda_available: bool
    recommended_low_vram: bool
    recommended_chunk: int
    recommended_stride: int
    recommended_stage2_batch: int
    recommended_foundation_chunk: int
    recommended_swin_batch: int
    recommended_ffmpeg_threads: int
    tier_name: str
    tier_desc: str

    @property
    def short_name(self) -> str:
        s = self.name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
        s = s.replace(" Laptop GPU", " Laptop").replace(" GPU", "")
        return s.strip()


# Peak GPU memory in GiB by megapixels of model input, measured at each Hann
# chunk size from CorridorKey 2.0 empirical benchmarks.
_VRAM_PEAK_GB = {
    False: ((8, 24, 48, 80), (
        (0.98, (6.19, 7.52, 9.77, 12.89)),
        (2.21, (7.50, 11.33, 18.66, 24.89)),
        (3.93, (9.06, 14.78, 23.92, 33.19)),
        (8.36, (13.94, 25.96, 45.15, 70.45)),
    )),
    True: ((1, 2, 4, 8, 24, 48, 80), (
        (0.98, (2.71, 2.78, 2.94, 3.25, 4.54, 6.57, 9.50)),
        (2.21, (2.80, 2.97, 3.35, 4.12, 7.69, 13.20, 20.56)),
        (3.93, (2.92, 3.23, 3.85, 5.09, 10.09, 17.57, 27.75)),
        (8.36, (3.25, 3.92, 5.28, 8.38, 20.78, 39.66, 64.65)),
    )),
}


def _interp(x: float, points) -> float:
    points = list(points)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1 or (x1, y1) == points[-1]:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[0][1]


def estimate_peak_vram_gb(width: int, height: int, model_scale: float, hann_chunk: int, low_vram: bool) -> float:
    eff_w = max(320, width) * model_scale
    eff_h = max(240, height) * model_scale
    megapixels = (eff_w * eff_h) / 1_000_000.0

    chunks, rows = _VRAM_PEAK_GB[bool(low_vram)]
    frames = max(hann_chunk, chunks[0])
    per_chunk = [
        max(_interp(megapixels, [(mp, peaks[i]) for mp, peaks in rows]), rows[0][1][i])
        for i in range(len(chunks))
    ]
    val = _interp(frames, zip(chunks, per_chunk))
    return round(float(val), 1)


def _detect_via_smi() -> tuple[str, float, float] | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        res = subprocess.run(
            [smi, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            first_line = res.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first_line.split(",")]
            if len(parts) >= 3:
                name = parts[0]
                total_gb = float(parts[1]) / 1024.0
                free_gb = float(parts[2]) / 1024.0
                return name, total_gb, free_gb
    except Exception:
        pass
    return None


def detect_gpu_profile() -> GpuProfile:
    # fast path: query nvidia-smi in ~20ms without loading heavyweight pytorch cuda runtime
    smi_res = _detect_via_smi()
    if smi_res is not None:
        name, total_gb, free_gb = smi_res
        is_cuda = True
    else:
        # fallback: lazy torch import if nvidia-smi is missing
        try:
            import torch
            if not torch.cuda.is_available():
                return GpuProfile(
                    name="No CUDA GPU Detected",
                    total_vram_gb=0.0,
                    free_vram_gb=0.0,
                    is_cuda_available=False,
                    recommended_low_vram=True,
                    recommended_chunk=4,
                    recommended_stride=2,
                    recommended_stage2_batch=1,
                    recommended_foundation_chunk=2,
                    recommended_swin_batch=8,
                    recommended_ffmpeg_threads=2,
                    tier_name="CPU Fallback",
                    tier_desc="No CUDA GPU detected; minimal chunk staging active.",
                )
            props = torch.cuda.get_device_properties(0)
            total_gb = props.total_memory / (1024 ** 3)
            free_bytes, _ = torch.cuda.mem_get_info(0)
            free_gb = free_bytes / (1024 ** 3)
            name = props.name
            is_cuda = True
        except Exception:
            return GpuProfile(
                name="No CUDA GPU Detected",
                total_vram_gb=0.0,
                free_vram_gb=0.0,
                is_cuda_available=False,
                recommended_low_vram=True,
                recommended_chunk=4,
                recommended_stride=2,
                recommended_stage2_batch=1,
                recommended_foundation_chunk=2,
                recommended_swin_batch=8,
                recommended_ffmpeg_threads=2,
                tier_name="CPU Fallback",
                tier_desc="No CUDA GPU detected; minimal chunk staging active.",
            )

    cpu_cores = os.cpu_count() or 4

    # classify hardware tier and performance profile
    if total_gb >= 20.0:
        tier_name = "24GB+"
        tier_desc = "Direct VRAM"
        low_vram = False
        chunk = 80
        stride = 40
        stage2_batch = 4
        foundation_chunk = 16
        swin_batch = 64
        ffmpeg_threads = min(12, max(4, cpu_cores // 2))
    elif total_gb >= 11.5:
        tier_name = "12GB-16GB"
        tier_desc = "Direct VRAM"
        low_vram = False
        chunk = 64
        stride = 32
        stage2_batch = 2
        foundation_chunk = 8
        swin_batch = 32
        ffmpeg_threads = min(8, max(2, cpu_cores // 2))
    elif total_gb >= 7.5:
        tier_name = "8GB-10GB"
        tier_desc = "Direct VRAM"
        low_vram = False
        chunk = 32
        stride = 16
        stage2_batch = 2
        foundation_chunk = 8
        swin_batch = 32
        ffmpeg_threads = min(8, max(2, cpu_cores // 2))
    elif total_gb >= 5.0:
        tier_name = "6GB"
        tier_desc = "Staged Memory"
        low_vram = True
        chunk = 16
        stride = 8
        stage2_batch = 1
        foundation_chunk = 4
        swin_batch = 16
        ffmpeg_threads = min(6, max(2, cpu_cores // 2))
    else:
        tier_name = "4GB"
        tier_desc = "Staged Memory"
        low_vram = True
        chunk = 8
        stride = 4
        stage2_batch = 1
        foundation_chunk = 4
        swin_batch = 16
        ffmpeg_threads = min(4, max(2, cpu_cores // 2))

    return GpuProfile(
        name=name,
        total_vram_gb=round(total_gb, 1),
        free_vram_gb=round(free_gb, 1),
        is_cuda_available=is_cuda,
        recommended_low_vram=low_vram,
        recommended_chunk=chunk,
        recommended_stride=stride,
        recommended_stage2_batch=stage2_batch,
        recommended_foundation_chunk=foundation_chunk,
        recommended_swin_batch=swin_batch,
        recommended_ffmpeg_threads=ffmpeg_threads,
        tier_name=tier_name,
        tier_desc=tier_desc,
    )
