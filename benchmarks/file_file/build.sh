#!/bin/bash
# autoreconf -fi
# ./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}} 

# make -j$(nproc) CC=$CC CXX=$CXX
# make install CC=$CC CXX=$CXX



autoreconf -fi
./configure CC=clang CXX=clang++ --disable-shared 
make -j$(nproc) CC=clang CXX=clang++ 
make install CC=clang CXX=clang++ 
cp magic/magic.mgc /tmp/magic.mgc
make clean
cp /tmp/magic.mgc magic/magic.mgc
make -j$(nproc) CC=$CC CXX=$CXX src/file
make install CC=$CC CXX=$CXX


# Phase 1: normal build
autoreconf -fi
./configure CC=clang CXX=clang++ --disable-shared
make -j$(nproc)  CC=clang CXX=clang++ 
cp magic/magic.mgc /tmp/magic.mgc

# Phase 2: instrumented build
make distclean   # better than clean, resets everything
cp /tmp/magic.mgc magic/magic.mgc
./configure CC=clang CXX=clang++ --disable-shared
make -j$(nproc) CC=$CC CXX=$CXX 