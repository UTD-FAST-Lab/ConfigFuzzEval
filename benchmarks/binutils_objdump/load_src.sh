#!/bin/bash

# Script to download binutils source code

set -e

# BINUTILS_URL="https://ftpmirror.gnu.org/binutils/binutils-2.37.tar.xz"
DOWNLOAD_DIR="/benchmark/source"

# echo "Downloading binutils source code..."
# wget $BINUTILS_URL 
# tar -xf binutils-2.37.tar.xz -C /tmp
# cp -r /tmp/binutils-2.37/. $DOWNLOAD_DIR

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I ${DOWNLOAD_DIR}
-I ${DOWNLOAD_DIR}/include
-I ${DOWNLOAD_DIR}/bfd
-I ${DOWNLOAD_DIR}/binutils
EOF

echo "Done"