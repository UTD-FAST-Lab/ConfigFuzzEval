autoreconf -fi
./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}} 
make -j$(nproc) CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX