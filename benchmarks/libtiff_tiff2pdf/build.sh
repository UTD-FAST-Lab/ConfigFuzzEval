#!/bin/bash
cd /libtiff
./autogen.sh CC=clang CXX=clang++
./configure CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}} 
# make check CC=$CC CXX=$CXX
make CC=$CC CXX=$CXX
# make install CC=$CC CXX=$CXX
# cp tools/tiff2pdf $OUT/tiff2pdf
# mkdir $OUT/seeds
# cp test/images/*.tiff $OUT/seeds/