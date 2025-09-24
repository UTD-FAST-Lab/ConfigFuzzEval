cd /LIBTIFF_FUZZER/libtiff
./autogen.sh CC=clang CXX=clang++
./configure CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}} 
make CC=$CC CXX=$CXX