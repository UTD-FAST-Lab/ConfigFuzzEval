./autogen.sh CC=clang CXX=clang++
./configure CC=clang CXX=clang++ --enable-tools --disable-shared --enable-static  {{CT_CONFIGURATION}} 
make CC=$CC CXX=$CXX