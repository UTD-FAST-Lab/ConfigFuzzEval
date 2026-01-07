#!/bin/bash

# Script to clone libpng source code

set -e

LIBPNG_REPO="https://github.com/pnggroup/libpng.git"
DOWNLOAD_DIR="/src_dir"

echo "Cloning libpng repository as src_dir..."
git clone "${LIBPNG_REPO}" "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir
-I src_dir/arm
-I src_dir/intel
-I src_dir/mips
-I src_dir/powerpc
EOF

echo "libpng source code cloned to ${DOWNLOAD_DIR}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
