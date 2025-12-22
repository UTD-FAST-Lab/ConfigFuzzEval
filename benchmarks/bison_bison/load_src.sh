#!/bin/bash

# Script to download bison-3.8 source code

set -e

BISON_VERSION="3.8"
BISON_URL="https://ftp.gnu.org/gnu/bison/bison-${BISON_VERSION}.tar.gz"
DOWNLOAD_DIR="/src_dir"

# Create src_dir if it doesn't exist
mkdir -p "${DOWNLOAD_DIR}"

echo "Downloading bison-${BISON_VERSION}..."
wget -O "${DOWNLOAD_DIR}/bison-${BISON_VERSION}.tar.gz" "${BISON_URL}"

echo "Extracting bison-${BISON_VERSION}..."
tar -xzf "${DOWNLOAD_DIR}/bison-${BISON_VERSION}.tar.gz" -C "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir/src
-I src_dir/lib
EOF

echo "Bison ${BISON_VERSION} source code downloaded and extracted to ${DOWNLOAD_DIR}/bison-${BISON_VERSION}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
