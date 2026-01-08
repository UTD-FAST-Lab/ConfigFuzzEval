#!/bin/bash
export CC=clang
export CXX=clang+
./autogen.sh
./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}}