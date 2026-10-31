# CorridorKey Studio Web Portal & Download Hub

Official web portal and distribution branch for CorridorKey Studio, deployed live on GitHub Pages.

Live Site: [https://yancovert.github.io/CorridorKey-Studio/](https://yancovert.github.io/CorridorKey-Studio/)

---

## Non-Commercial & Personal Experimentation Notice

This project is an independent, non-commercial open-source personal experimentation build created strictly for research, educational experimentation, and community workflow development.

- **Non-Commercial**: This software is not sold, monetized, or offered for commercial distribution.
- **Independent Project**: Not affiliated with, sponsored by, or endorsed by Corridor Digital, Zachary Harris, or Niko Pueringer.
- **Official Commercial Plugin**: For commercial studio use, supported video software integrations, and official production plugins, please visit **[corridorkey.com](https://corridorkey.com)**.
- **Model Ownership**: CorridorKey 2.0 foundation model weights and architecture belong to their respective creators under open research terms.

---


## Branch Overview

The `gh-pages` branch serves as the static web host and download distribution center for CorridorKey Studio. It provides an operating system-aware landing page with live interface walkthroughs, technical deliverable specifications, hardware guidance, and direct links to standalone installer binaries for Linux and Windows.

---

## Assets & Directory Structure

```
.
├── index.html                           # Single-page web portal and documentation
├── CorridorKey-Studio-Installer-Linux   # Standalone Linux installer binary
├── CorridorKey-Studio-Setup.exe         # Standalone Windows installer executable
├── install.sh                           # One-line curl installer for Linux
├── install.bat                          # One-click batch launcher for Windows
├── install.py                           # Cross-platform installation engine (CLI mode)
├── install_gui.py                       # Cross-platform graphical installation wizard
├── screenshot.png                       # Interface preview screenshot
├── screenshot_updating.png              # In-app update process screenshot
└── gui/
    └── icon.png                         # High-resolution application icon
```

---

## Web Portal Features

1. **Automatic OS Detection**: Detects user operating system (Windows vs. Linux) and highlights the corresponding recommended installer button.
2. **Interactive Walkthrough**: Visual step-by-step instructions for loading footage, selecting hardware presets, scrubbing timeline frames, and exporting deliverables.
3. **Hardware & VRAM Guidance**: Technical table outlining recommended settings across 4GB laptop GPUs up to 24GB+ workstations.
4. **Deliverables Table**: Reference documentation covering Blender ProRes 4444 RGBA, PNG sequences, OpenEXR sequences, DaVinci Resolve packs, and WebM VP9 containers.
5. **Direct Download Links**: Fast, direct downloads for Linux and Windows standalone setup bundles.

---

## Installer Distribution

### Linux (`install.sh`)
Serves the automated installation script:
```bash
curl -fsSL https://yancovert.github.io/CorridorKey-Studio/install.sh | bash
```
Downloads the installer, validates CUDA drivers, provisions a local virtual environment with PyTorch CUDA 12.8, downloads model weights (~5 GB), and installs `.desktop` shortcuts.

### Windows (`install.bat` / `CorridorKey-Studio-Setup.exe`)
Executes the self-contained installer wizard with drive space detection, virtual environment configuration, weight downloads, and Desktop/Start Menu shortcut creation.

---

## Deployment & Maintenance

This branch is configured to deploy directly through **GitHub Pages**:
- **Source**: Deploy from branch `gh-pages`
- **Folder**: `/ (root)`
- **Domain**: `https://yancovert.github.io/CorridorKey-Studio/`

Any commits pushed to `origin/gh-pages` are automatically deployed to the production portal via GitHub Pages actions.
