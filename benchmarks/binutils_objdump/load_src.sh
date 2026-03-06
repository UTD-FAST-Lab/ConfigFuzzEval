#!/bin/bash

# Script to download binutils source code

set -e

BINUTILS_URL="https://ftpmirror.gnu.org/binutils/binutils-2.37.tar.xz"
DOWNLOAD_DIR="/src_dir"

echo "Downloading binutils source code..."
wget $BINUTILS_URL 
tar -xf binutils-2.37.tar.xz -C /tmp
cp -r /tmp/binutils-2.37/. $DOWNLOAD_DIR

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir
-I src_dir/include
-I src_dir/bfd
-I src_dir/binutils
EOF

echo "Done"