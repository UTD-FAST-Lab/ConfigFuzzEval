./configure CC=clang CXX=clang++
make -j$(nproc)
cp doc/bison.help /tmp/bison.help
make clean
./configure --disable-nls --without-libtextstyle-prefix --disable-dependency-tracking \ CC=$CC CXX=$CXX {{CT_CONFIGURATION}}

cp /tmp/bison.help doc/bison.help
make -j$(nproc) CC=$CC CXX=$CXX src/bison