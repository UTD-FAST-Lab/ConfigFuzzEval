./autogen.sh  CC=clang CXX=clang++
./configure  CC=clang CXX=clang++ --disable-shared {{CT_CONFIGURATION}}
make CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX