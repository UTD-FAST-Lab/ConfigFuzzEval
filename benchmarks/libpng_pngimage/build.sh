#!/bin/bash
./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}}
make check CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX

# cp pngimage $OUT/pngimage
# mkdir $OUT/seeds
# cp *.png $OUT/seeds