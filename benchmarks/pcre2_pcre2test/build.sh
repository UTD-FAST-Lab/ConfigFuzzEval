./autogen.sh  CC=clang CXX=clang++
./configure --disable-rebuild-chartables --enable-pcre2-8 CC=clang CXX=clang++ --disable-shared --enable-static {{CT_CONFIGURATION}}
make CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX