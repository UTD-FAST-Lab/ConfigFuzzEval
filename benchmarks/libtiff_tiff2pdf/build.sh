#!/bin/bash

# Force the inclusion of zlib, the C++ standard library (for LERC), and math
export LIBS="-lz -lstdc++ -lm"
export PKG_CONFIG="pkg-config"

./autogen.sh

# Configure with plain clang: configure runs the test programs it compiles, and
# binaries built with some fuzzer compilers (e.g. ZigZagFuzz) cannot run outside
# the fuzzer. The fuzzer compiler ($CC/$CXX) is used for the actual build below.
./configure CC=clang CXX=clang++ \
  --enable-tools \
  --disable-shared \
  --enable-static \
  {{CT_CONFIGURATION}}

make -j$(nproc) CC=$CC CXX=$CXX
