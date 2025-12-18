#!/bin/bash

# Root directory containing source files
SRC_DIR="/home/safeer/test_super_c/bison"

# Output directory for sourcelinePC files
OUT_DIR="${SRC_DIR}/sourceline_pc_outputs"

# Include directories (edit or add more as needed)
INCLUDE_DIRS=(
    "-I /home/safeer/test_super_c/bison/src"
    "-I /home/safeer/test_super_c/bison/lib"
)

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

