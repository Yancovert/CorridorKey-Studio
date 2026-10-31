#!/usr/bin/env bash
set -e

# corridor key studio official linux uninstaller
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTO_CONFIRM=false

for arg in "$@"; do
    case "$arg" in
        -y|--yes|--force)
            AUTO_CONFIRM=true
            ;;
    esac
done

echo "=========================================="
echo "CorridorKey Studio - Uninstaller (Linux)"
echo "=========================================="
echo "Target installation: $SCRIPT_DIR"
echo ""

if [ "$AUTO_CONFIRM" = false ]; then
    read -p "Uninstall CorridorKey Studio? [y/N]: " confirm
    case "$confirm" in
        [yY]|[yY][eE][sS])
            ;;
        *)
            echo "Uninstallation cancelled."
            exit 0
            ;;
    esac
fi

echo "[1/4] Removing desktop and application launcher entries..."
USER_HOME="$HOME"
DESKTOP_DIR="$USER_HOME/Desktop"
if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$USER_HOME/Desktop")"
fi

rm -f "$DESKTOP_DIR/corridorkey-studio.desktop"
rm -f "$USER_HOME/.local/share/applications/corridorkey-studio.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$USER_HOME/.local/share/applications" 2>/dev/null || true
fi

echo "[2/4] Removing user configuration..."
rm -rf "$USER_HOME/.config/corridorkey-studio"

echo "[3/4] Removing virtual environment..."
rm -rf "$SCRIPT_DIR/venv" "$SCRIPT_DIR/.venv"

echo "[4/4] Removing installed application files..."
# if weights directory exists and is large, ask or clean
if [ "$AUTO_CONFIRM" = false ] && [ -d "$SCRIPT_DIR/weights" ]; then
    read -p "Delete downloaded model weights (~1.5 GB)? [y/N]: " rm_weights
    case "$rm_weights" in
        [yY]|[yY][eE][sS])
            rm -rf "$SCRIPT_DIR/weights"
            ;;
    esac
else
    rm -rf "$SCRIPT_DIR/weights"
fi

# remove launcher and build files
rm -f "$SCRIPT_DIR/launch_gui.sh" "$SCRIPT_DIR/launch_gui.bat" "$SCRIPT_DIR/.build_version" "$SCRIPT_DIR/install.sh"
rm -rf "$SCRIPT_DIR/gui" "$SCRIPT_DIR/corridorkey"

echo ""
echo "CorridorKey Studio has been completely uninstalled."
echo "You can now safely remove the remaining folder if desired: $SCRIPT_DIR"
