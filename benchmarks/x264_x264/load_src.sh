#!/bin/bash

# Script to download x264 source code

set -e

X264_URL="https://code.videolan.org/videolan/x264.git"
DOWNLOAD_DIR="/src_dir"

echo "Cloning x264 from git as src_dir..."
git clone "${X264_URL}" "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir
-I src_dir/libxml
-I src_dir/private
EOF

echo "Libxml2 source code cloned to ${DOWNLOAD_DIR}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
