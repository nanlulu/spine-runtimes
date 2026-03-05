#!/bin/bash
# Extract all skins into individual directories.
# Usage: ./extract_all_skins.sh [output_base_dir]
#   default output_base_dir: ./skins/

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_BASE="${1:-$SCRIPT_DIR/skins}"

cd "$SCRIPT_DIR"

SKINS=$(python extract_skin.py --list-skins | grep '^ ' | awk '{print $1}')

URLS_FILE="$OUTPUT_BASE/viewer_urls.txt"
mkdir -p "$OUTPUT_BASE"
> "$URLS_FILE"

for skin in $SKINS; do
    lower=$(echo "$skin" | tr '[:upper:]' '[:lower:]')
    outdir="$OUTPUT_BASE/$lower"
    echo "=== Extracting $skin -> $outdir ==="
    rm -rf "$outdir"
    python extract_skin.py --skin "$skin" --output-dir "$outdir"
    echo "http://127.0.0.1:8080/spine-webgl/demos/tools/skins/$lower/viewer.html" >> "$URLS_FILE"
    echo ""
done

echo "Done. Extracted $(echo "$SKINS" | wc -w | tr -d ' ') skins to $OUTPUT_BASE/"
echo "Viewer URLs written to $URLS_FILE"
