#!/bin/bash

set -e

echo "=========================================="
echo "Step 1: Running SuperC analysis..."
echo "=========================================="
cd /superc
bash run_superc.sh

echo ""
echo "=========================================="
echo "Step 2: Moving to root directory..."
echo "=========================================="
cd /

echo ""
echo "=========================================="
echo "Step 3: Merging PC with coverage..."
echo "=========================================="
cov_args=()
for file in /fuzzer_output/lcov_results/*.json; do
    # Extract the filename to use as the "Name"
    name=$(basename "$file")
    cov_args+=("$name:$file")
done

python3 1_merge_pc_with_coverage.py \
    --pc-dir /fuzzer_output/pc_analysis/sourceline_pc_outputs \
    --cov "${cov_args[@]}" \
    --out /fuzzer_output/pc_analysis/merged_pc_coverage.json

echo ""
echo "=========================================="
echo "Step 4: Analyzing PC coverage..."
echo "=========================================="
python3 2_analyze_pc_coverage.py \
    --merged /fuzzer_output/pc_analysis/merged_pc_coverage.json \
    --out-json /fuzzer_output/pc_analysis/pc_coverage_summary.json \
    --out-csv /fuzzer_output/pc_analysis/pc_coverage_summary.csv

echo ""
echo "=========================================="
echo "✅ All steps completed successfully!"
echo "=========================================="
