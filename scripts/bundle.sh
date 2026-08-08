#!/bin/bash
# Local "release" bundling script for Fedora/KDE

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN_DEST="${HOME}/.local/bin/quinoa"
DESKTOP_DEST="${HOME}/.local/share/applications/quinoa.desktop"
ICON_DEST="${HOME}/.local/share/icons/hicolor/scalable/apps/quinoa.png"

echo "📦 Bundling Quinoa local release..."

# 1. Build Rust extension in release mode from the project root so that
# pyproject.toml [tool.maturin] enables both extension-module and real-audio.
echo "🦀 Building Rust extension (release)..."
cd "$PROJECT_ROOT"
uv run maturin develop --release

# 2. Create the bin wrapper
echo "🔨 Creating wrapper script..."
mkdir -p "$(dirname "$BIN_DEST")"
cat > "$BIN_DEST" <<EOF
#!/bin/bash
cd "$PROJECT_ROOT"
export QT_QPA_PLATFORM=xcb  # Workaround for some Wayland/Qt issues if they arise, or omit for default
uv run python -m quinoa.main "\$@"
EOF
chmod +x "$BIN_DEST"

# 3. Install the icon
echo "🎨 Squaring and installing icon..."
# We'll create a squared version with transparent padding
ICON_SOURCE="$PROJECT_ROOT/quinoa_icon.png"
SQUARED_ICON="/tmp/quinoa_squared.png"

# Detect max dimension
WIDTH=$(magick identify -format "%w" "$ICON_SOURCE")
HEIGHT=$(magick identify -format "%h" "$ICON_SOURCE")
MAX_DIM=$(( WIDTH > HEIGHT ? WIDTH : HEIGHT ))

magick "$ICON_SOURCE" -background transparent -gravity center -extent ${MAX_DIM}x${MAX_DIM} "$SQUARED_ICON"

# Install to standard locations
mkdir -p "$HOME/.local/share/icons/hicolor/512x512/apps"
cp "$SQUARED_ICON" "$HOME/.local/share/icons/hicolor/512x512/apps/quinoa.png"
# Also put it in the top level for better compatibility
cp "$SQUARED_ICON" "$HOME/.local/share/icons/quinoa.png"

# 4. Install the desktop file
echo "🖥️ Installing desktop entry..."
mkdir -p "$(dirname "$DESKTOP_DEST")"
# Rewrite Exec and Icon to current-user absolute paths
sed -e "s|^Exec=.*|Exec=$BIN_DEST|" -e "s|^Icon=.*|Icon=$HOME/.local/share/icons/quinoa.png|" "$PROJECT_ROOT/quinoa.desktop" > "$DESKTOP_DEST"

# Update desktop database
update-desktop-database "$(dirname "$DESKTOP_DEST")" || true
# Also refresh icon cache
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" || true

echo "✅ Release bundled! You can now launch Quinoa from your application menu."
echo "   Command: $BIN_DEST"
