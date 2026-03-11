
# export LIBS="-lz -lstdc++ -lm"
# export PKG_CONFIG="pkg-config" 
# ./autogen.sh CC=clang CXX=clang++
# ./configure CC=clang CXX=clang++ --enable-tools --disable-shared --enable-static --without-docs  {{CT_CONFIGURATION}} 
# make CC=$CC CXX=$CXX -j$(nproc)


#!/bin/bash

# Export the FuzzBench compiler variables
export CC="$CC"
export CXX="$CXX"

# Crucial: Force the inclusion of zlib, the C++ standard library (for LERC), and math
export LIBS="-lz -lstdc++ -lm"
export PKG_CONFIG="pkg-config" 

./autogen.sh 

# Run configure dynamically, but with our forced LIBS
./configure \
  --enable-tools \
  --disable-shared \
  --enable-static \
  {{CT_CONFIGURATION}}

make -j$(nproc)