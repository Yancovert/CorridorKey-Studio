from __future__ import annotations

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
            )

    if total_gb <= 4.5:
        low_vram = True
        chunk = 8
    elif total_gb <= 6.5:
        low_vram = True
        chunk = 16
    elif total_gb <= 12.5:
        low_vram = False
        chunk = 48
    else:
        low_vram = False
        chunk = 80

    stride = max(1, chunk // 2)

    return GpuProfile(
        name=name,
        total_vram_gb=round(total_gb, 1),
        free_vram_gb=round(free_gb, 1),
        is_cuda_available=is_cuda,
        recommended_low_vram=low_vram,
        recommended_chunk=chunk,
        recommended_stride=stride,
    )


@dataclass
class ClipHardwareRecommendation:
    low_vram: bool
    chunk: int
    stride: int
    title: str
    explanation: str
    is_tight_memory: bool


def recommend_settings_for_clip(gpu: GpuProfile, width: int, height: int, total_frames: int) -> ClipHardwareRecommendation:
    pixels = width * height
    is_4k_or_higher = pixels >= (2560 * 1440)
    res_label = f"{width}x{height}"

    if not gpu.is_cuda_available:
        return ClipHardwareRecommendation(
            low_vram=True,
            chunk=4,
            stride=2,
            title="CPU / Fallback Profile",
            explanation="No CUDA GPU detected; staged execution enabled with minimal chunk size.",
            is_tight_memory=True,
        )

    # 4gb cards (e.g. rtx 3050 mobile) need chunk 4 on 4k to fit attention maps
    if gpu.total_vram_gb <= 4.5:
        if is_4k_or_higher:
            return ClipHardwareRecommendation(
                low_vram=True,
                chunk=4,
                stride=2,
                title="Ultra-Safe Staged Profile (4K / 4GB VRAM)",
                explanation=f"Detected {res_label} on {gpu.total_vram_gb} GB GPU. Applied minimal chunk (4) and disk memmaps to avoid CUDA OOM.",
                is_tight_memory=True,
            )
        return ClipHardwareRecommendation(
            low_vram=True,
            chunk=8,
            stride=4,
            title="Safe Staged Profile (1080p / 4GB VRAM)",
            explanation=f"Detected {res_label} on {gpu.total_vram_gb} GB GPU. Applied chunk 8 with low-VRAM staging for optimal stability.",
            is_tight_memory=False,
        )

    # 6gb to 8gb cards
    if gpu.total_vram_gb <= 8.5:
        if is_4k_or_higher:
            return ClipHardwareRecommendation(
                low_vram=True,
                chunk=8,
                stride=4,
                title="Staged Profile (4K / Mid VRAM)",
                explanation=f"Detected {res_label} on {gpu.total_vram_gb} GB GPU. Staging enabled with chunk 8 to preserve VRAM headroom.",
                is_tight_memory=False,
            )
        return ClipHardwareRecommendation(
            low_vram=False,
            chunk=24,
            stride=12,
            title="Balanced In-Memory Profile",
            explanation=f"Detected {res_label} on {gpu.total_vram_gb} GB GPU. Direct memory execution enabled with chunk 24.",
            is_tight_memory=False,
        )

    # workstation cards with >= 12gb vram
    if is_4k_or_higher:
        return ClipHardwareRecommendation(
            low_vram=False,
            chunk=48,
            stride=24,
            title="High-Performance 4K Profile",
            explanation=f"Detected {res_label} with ample {gpu.total_vram_gb} GB VRAM. Full resolution attention chunk 48 active.",
            is_tight_memory=False,
        )

    return ClipHardwareRecommendation(
        low_vram=False,
        chunk=80,
        stride=40,
        title="Maximum Throughput Profile",
        explanation=f"Detected {res_label} on {gpu.total_vram_gb} GB GPU. Maximum temporal window (chunk 80) active without staging.",
        is_tight_memory=False,
    )
