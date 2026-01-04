#!/bin/bash
export CC=clang
export CXX=clang+
./autogen.sh
./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}}
make check
make install

# cp pngimage $OUT/pngimage
# mkdir $OUT/seeds
# cp *.png $OUT/seeds