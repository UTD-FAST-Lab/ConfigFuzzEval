#!/bin/bash

# Script to download libxml2 source code

set -e

LIBXML2_URL="https://github.com/GNOME/libxml2.git"
DOWNLOAD_DIR="/src_dir"

echo "Cloning libxml2 from git as src_dir..."
git clone "${LIBXML2_URL}" "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir
-I src_dir/libxml
-I src_dir/private
EOF

echo "Libxml2 source code cloned to ${DOWNLOAD_DIR}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
