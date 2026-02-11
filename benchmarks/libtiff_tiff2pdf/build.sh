./autogen.sh CC=clang CXX=clang++
./configure CC=clang CXX=clang++ --enable-tools --disable-shared --enable-static --without-docs  {{CT_CONFIGURATION}} 
make CC=$CC CXX=$CXX