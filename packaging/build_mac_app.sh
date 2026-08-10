#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
OUTPUT_DIR="$PROJECT_DIR/outputs"
BUILD_DIR="$PROJECT_DIR/work/pyinstaller"
DIST_DIR="$PROJECT_DIR/work/dist"
export PYINSTALLER_CONFIG_DIR="$PROJECT_DIR/work/pyinstaller-config"

cd "$PROJECT_DIR"
mkdir -p "$OUTPUT_DIR" "$BUILD_DIR" "$DIST_DIR" "$PYINSTALLER_CONFIG_DIR"

"$PROJECT_DIR/.venv/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --workpath "$BUILD_DIR" \
  --distpath "$DIST_DIR" \
  "$PROJECT_DIR/packaging/CleanReader.spec"

rm -rf "$OUTPUT_DIR/Clean Reader.app"
rm -f "$OUTPUT_DIR/Clean Reader-mac-arm64.zip"
ditto "$DIST_DIR/Clean Reader.app" "$OUTPUT_DIR/Clean Reader.app"
ditto -c -k --sequesterRsrc --keepParent \
  "$OUTPUT_DIR/Clean Reader.app" \
  "$OUTPUT_DIR/Clean Reader-mac-arm64.zip"

echo "$OUTPUT_DIR/Clean Reader.app"
echo "$OUTPUT_DIR/Clean Reader-mac-arm64.zip"
