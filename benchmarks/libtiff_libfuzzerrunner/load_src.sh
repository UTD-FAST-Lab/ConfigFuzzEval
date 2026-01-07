#!/bin/bash

# Script to clone libtiff source code

set -e

LIBTIFF_REPO="https://gitlab.com/libtiff/libtiff.git"
DOWNLOAD_DIR="/src_dir"

echo "Cloning libtiff repository as src_dir..."
git clone "${LIBTIFF_REPO}" "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir/libtiff
EOF

echo "LibTIFF source code cloned to ${DOWNLOAD_DIR}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
