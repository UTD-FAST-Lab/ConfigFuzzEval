#!/bin/bash

# Script to clone expat source code

set -e

EXPAT_REPO="https://github.com/libexpat/libexpat.git"
DOWNLOAD_DIR="/src_dir"

echo "Cloning libexpat repository as src_dir..."
git clone --depth 1 "${EXPAT_REPO}" "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir/expat/lib
-I src_dir/expat/xmlwf
EOF

echo "Libexpat source code cloned to ${DOWNLOAD_DIR}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
