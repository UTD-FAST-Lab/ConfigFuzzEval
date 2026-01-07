#!/bin/bash

# Script to download pcre2 source code

set -e

PCRE2_URL="https://github.com/PCRE2Project/pcre2.git"
DOWNLOAD_DIR="/src_dir"

echo "Cloning pcre2 from git as src_dir..."
git clone "${PCRE2_URL}" "${DOWNLOAD_DIR}"

echo "Creating include directories file..."
cat > "${DOWNLOAD_DIR}/include_dirs.txt" << EOF
-I src_dir/src
EOF

echo "Pcre2 source code cloned to ${DOWNLOAD_DIR}"
echo "Include directories saved to ${DOWNLOAD_DIR}/include_dirs.txt"
echo "Done!"
