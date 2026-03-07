#!/bin/bash

# Root directory containing source files
SRC_DIR="/benchmark/source"

# Output directory for sourcelinePC files
OUT_DIR="/fuzzer_output/pc_analysis/sourceline_pc_outputs"

cd /benchmark
bash load_src.sh
cd -

# Load include directories from file
INCLUDE_DIRS_FILE="${SRC_DIR}/include_dirs.txt"
if [ ! -f "$INCLUDE_DIRS_FILE" ]; then
    echo "Error: Include directories file not found: $INCLUDE_DIRS_FILE"
    exit 1
fi

# Read include directories from file into array
mapfile -t INCLUDE_DIRS < "$INCLUDE_DIRS_FILE"

# Ensure output directory exists
mkdir -p "$OUT_DIR"

# Find all relevant C source files (adjust to include headers if needed)
find "$SRC_DIR" -type f -name "*.c" | while read -r file; do
    # Extract filename without path
    filename=$(basename "$file")
    base="${filename%.*}"

    # Define output file name
    out_file="${OUT_DIR}/sourceline_${base}.json"

    echo "Processing $file → $out_file"

    # Run SuperC with the proper include paths
    java superc.SuperC \
        -nostdinc \
        -keepErrors \
        -presenceConditions \
        -sourcelinePC "$out_file" \
        -configurationVariables \
        -silent \
        ${INCLUDE_DIRS[@]} \
        "$file"
done

echo "✅ All files processed. Outputs stored in: $OUT_DIR"

