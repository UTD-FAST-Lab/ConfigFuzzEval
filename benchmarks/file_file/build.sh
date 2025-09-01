#!/bin/bash
autoreconf -fi
./configure --disable-shared {{CT_CONFIGURATION}} 

make -j$(nproc) CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX

