./autogen.sh --disable-shared CC=clang CXX=clang++
./configure CC=clang CXX=clang++ --disable-shared --enable-static {{CT_CONFIGURATION}} 
make -j$(nproc) CC=$CC CXX=$CXX

