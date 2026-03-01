#!/bin/bash
# Local "release" bundling script for Fedora/KDE

set -e

PROJECT_ROOT="/home/rswift/dev/personal/quinoa"
BIN_DEST="/home/rswift/.local/bin/quinoa"
DESKTOP_DEST="/home/rswift/.local/share/applications/quinoa.desktop"
ICON_DEST="/home/rswift/.local/share/icons/hicolor/scalable/apps/quinoa.png"

echo "📦 Bundling Quinoa local release..."

# 1. Build Rust extension in release mode
echo "🦀 Building Rust extension (release)..."
cd "$PROJECT_ROOT/quinoa_audio"
uv run maturin develop --release --features real-audio
cd "$PROJECT_ROOT"

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
# Use absolute path for icon in desktop file to be extra safe
sed "s|Icon=quinoa|Icon=$HOME/.local/share/icons/quinoa.png|" "$PROJECT_ROOT/quinoa.desktop" > "$DESKTOP_DEST"

# Update desktop database
update-desktop-database "$(dirname "$DESKTOP_DEST")" || true
# Also refresh icon cache
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" || true

echo "✅ Release bundled! You can now launch Quinoa from your application menu."
echo "   Command: $BIN_DEST"
