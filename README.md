# CorridorKey Studio (Windows)

Desktop workstation and chroma keying suite powered by CorridorKey 2.0.

CorridorKey Studio is an open-source Windows desktop workstation built on CorridorKey 2.0 (designed and trained by Zachary Harris in collaboration with Niko Pueringer and Corridor Digital). It wraps the foundation keying model in a modern Qt studio interface with real-time split preview, automated hybrid GPU offloading, hardware optimizations for 4GB+ GPUs, and production export pipelines for Blender, DaVinci Resolve, and VFX compositors.

Download & Documentation Hub: [https://yancovert.github.io/CorridorKey-Studio/](https://yancovert.github.io/CorridorKey-Studio/)

---

## Non-Commercial & Personal Experimentation Notice

This project is an independent, non-commercial open-source personal experimentation build created strictly for research, educational experimentation, and community workflow development.

- **Non-Commercial**: This software is not sold, monetized, or offered for commercial distribution.
- **Independent Project**: Not affiliated with, sponsored by, or endorsed by Corridor Digital, Zachary Harris, or Niko Pueringer.
- **Official Commercial Plugin**: For commercial studio use, supported video software integrations, and official production plugins, please visit **[corridorkey.com](https://corridorkey.com)**.
- **Model Ownership**: CorridorKey 2.0 foundation model weights and architecture belong to their respective creators under open research terms.

---


## What We Built

### 1. Modern Studio Workstation
- **Footage Drag-and-Drop**: Load MP4, MOV, or numbered image sequence directories directly into the workspace.
- **Interactive Split Preview**: Draggable A/B wipe divider to inspect the alpha matte, despilled foreground, or cutout directly over footage.
- **Timeline Transport & Scrubber**: Real-time frame navigation with play, pause, step forward/back, jump to start/end, looping, and Spacebar playback.
- **Companion Hint Detection**: Automatically discovers `<clip>FrameHint.png` (first-frame matte) and `<clip>_AlphaHint.mp4` (full tracking hint) when footage is loaded.

### 2. Dynamic GPU Selector & Hybrid Offload
- **Automated Hardware Discovery**: Detects all system GPUs across discrete NVIDIA adapters and integrated Intel/AMD graphics via WMI (`Win32_VideoController`) and `nvidia-smi`.
- **Auto Hybrid Offload**: Routes Qt GUI rendering and desktop compositing to the integrated GPU (iGPU) while dedicating 100% of discrete NVIDIA VRAM to neural inference.
- **Multi-GPU Targeting**: Select specific CUDA devices (`cuda:0`, `cuda:1`, etc.) via `CUDA_VISIBLE_DEVICES`.
- **Pre-Flight Validation**: Non-CUDA adapters (e.g. Intel Iris/UHD) are marked `[Unsupported: No CUDA]` and blocked from inference crashes with an informative dialog.

### 3. Low-VRAM Optimization for 4GB+ GPUs
- **Half-Precision Parameter Footprint**: In `--low_vram` mode, Stage 1 and Stage 2 model weights convert to `bfloat16` (or `float16`), cutting baseline memory in half (Stage 1: 906 MB, Stage 2: 395 MB).
- **DepthwiseSwiGLU Frame Partitioning**: Splits spatial convolution and padding buffers across the temporal frame axis into batches of 4.
- **SwiGLU 5D Temporal Chunking**: Chunks 5D activation tensors to prevent memory spikes in high-channel feed-forward blocks.
- **Swin Attention Window Batching**: Defaulted `low_vram_swin_window_batch` to 4, preventing contiguous token allocation bottlenecks.
- **Zero-Fragmentation Allocator**: Pre-configures `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` across backend execution.

### 4. Production Export Deliverables
- **Blender ProRes 4444**: 10-bit RGBA MOV with transparent alpha and auto-generated `import_to_blender.py` setup script.
- **Blender PNG Sequence**: Numbered RGBA frames for Cycles and Eevee image plane cards.
- **OpenEXR Sequence**: 16-bit half or 32-bit float scene-linear HDR frames for ACES and VFX composite graphs.
- **DaVinci Resolve Pack**: Fill + Matte dual-stream MOV pair for DaVinci Resolve External Matte nodes.
- **QuickTime Animation**: Lossless RGBA for Premiere Pro and After Effects.
- **Standard Video Previews**: Despilled Foreground (`fg`), Alpha Matte (`alpha`), and Checkerboard Composite (`checker`).

### 5. In-App Updater & Uninstaller
- **Integrated Git Updater**: Live update badge in the header bar; click to pull the latest release from GitHub and auto-restart.
- **Complete Uninstaller**: Clean uninstallation script (`uninstall.bat`) and Settings uninstaller button to remove dependencies, desktop shortcuts, and temporary cache.

---

## Installation

### Method 1: Standalone Windows Setup (Recommended)
Download and run the standalone installer:
- **Download**: [CorridorKey-Studio-Setup.exe](https://yancovert.github.io/CorridorKey-Studio/CorridorKey-Studio-Setup.exe)
- Or run `install.bat` from the repository root.

The setup wizard:
1. Validates your NVIDIA GPU, driver, and CUDA capability.
2. Selects the local drive with the most free storage space.
3. Downloads the required CorridorKey weights and foundation models (~5 GB).
4. Creates an isolated Python virtual environment with CUDA 12.8 PyTorch.
5. Adds Start Menu and Desktop shortcuts.

### Method 2: Manual Setup From Source
Prerequisites:
- 64-bit Windows 10 or Windows 11
- NVIDIA GPU (RTX 30-series or newer, compute capability 8.0+)
- Python 3.10 to 3.12 (with "Add Python to PATH" enabled during install)
- `ffmpeg` on your system PATH

```cmd
:: Clone the repository
git clone -b app-win https://github.com/Yancovert/CorridorKey-Studio.git
cd CorridorKey-Studio

:: Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

:: Install PyTorch with CUDA 12.8 support and dependencies
pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt

:: Download model weights and frozen foundations (~5 GB)
python scripts\download_weights.py

:: Launch CorridorKey Studio GUI
python main.py
```

---

## Workflow Presets

CorridorKey Studio includes 5 tuned hardware and quality presets:

| Preset | Target Hardware | Hann Window | Stride | VRAM Usage |
| :--- | :--- | :--- | :--- | :--- |
| **Balanced Studio** | 8 GB - 12 GB GPUs | 48 | 24 | ~2.5 GB - 3.5 GB |
| **Low-VRAM Staged** | 4 GB - 6 GB Laptop GPUs | 16 | 4 | ~900 MB - 1.5 GB |
| **Maximum Quality** | 16 GB - 24 GB GPUs | 80 | 40 | ~4.5 GB - 6.5 GB |
| **High-Performance** | 24 GB+ (RTX 4090 / A6000) | 80 | 40 | Multi-batch throughput |
| **Fast Turnaround** | Quick review / low res | 16 | 8 | Rapid keying previews |

---

## CLI Usage

For command-line automation, batch rendering, or scripting pipelines, run `infer.py`:

```cmd
python infer.py ^
  --input C:\path\to\shot.mp4 ^
  --output_dir C:\path\to\output ^
  --outputs alpha fg checker cutout ^
  --low_vram ^
  --hann_chunk 16 ^
  --hann_stride 4
```

### CLI Parameters:
- `--outputs`: Space-separated choices (`alpha`, `fg`, `checker`, `cutout`).
- `--low_vram`: Activates half-precision weights, frame chunking, and memory-safe window batching.
- `--output_format`: Choose `video` (MP4/MOV) or `exr` (numbered image sequence).
- `--cutout_linear`: Exports cutout with scene-linear RGB instead of sRGB gamma.
- `--despill_strength`: Edge color despill intensity from `0.0` to `1.0` (default: `0.5`).
- `--linear_brightness`: Multiplier for linear gain calibration (default: `1.0`).
- `--linear_contrast_pivot`: Contrast pivot level (default: `0.18`).
- `--ffmpeg_codec`: Video encoder codec (e.g. `libx264`, `prores_ks`).
- `--pix_fmt`: Pixel format (e.g. `yuva444p10le`, `yuv444p10le`).

---

## Uninstallation

To completely remove CorridorKey Studio, desktop shortcuts, and cached models:
```cmd
uninstall.bat
```
Or open **Advanced Settings** in the GUI and click **Run Uninstaller**.

---

## Credits & Notices

- **Model Architecture & Training**: Zachary Harris in collaboration with Niko Pueringer and Corridor Digital.
- **CorridorKey Studio GUI & Pipeline**: Yancovert.
- **Foundation Vision Models**:
  - [C-RADIO](https://github.com/NVlabs/RADIO) by NVIDIA (Open Model License)
  - [MoGe](https://github.com/microsoft/MoGe) by Microsoft (MIT License)
  - [RVM](https://github.com/google-deepmind/representations4d) by Google DeepMind (Apache 2.0 / CC-BY 4.0)
- **Official Commercial Plugin**: Available at [corridorkey.com](https://corridorkey.com).

CorridorKey 2.0 code and model weights are licensed for personal and commercial use under the terms in the LICENSE file.
