#!/bin/bash
./autogen.sh
./configure CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}}
# pngimage is a check program, so it is only built when named explicitly.
make -j$(nproc) CC=$CC CXX=$CXX pngimage
