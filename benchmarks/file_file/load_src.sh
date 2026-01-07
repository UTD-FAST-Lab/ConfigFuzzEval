#!/bin/bash

# Script to clone file source code

set -e

FILE_REPO="https://github.com/file/file.git"
DOWNLOAD_DIR="/src_dir"

echo "Cloning file repository as src_dir..."
git clone "${FILE_REPO}" "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir/src
EOF

echo "File source code cloned to ${DOWNLOAD_DIR}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
