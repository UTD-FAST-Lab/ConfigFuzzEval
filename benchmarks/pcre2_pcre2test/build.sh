# cd pcre2
./autogen.sh  CC=clang CXX=clang++
./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}}
make CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX

# ./autogen.sh CC=$CC CXX=$CXX
# ./configure  CC=$CC CXX=$CXX --disable-shared {{CT_CONFIGURATION}}
# make CC=$CC CXX=$CXX
# make install CC=$CC CXX=$CXX