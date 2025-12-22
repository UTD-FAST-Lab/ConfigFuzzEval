#!/bin/bash
./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}}
make check CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX