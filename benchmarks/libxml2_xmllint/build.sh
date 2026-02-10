# cd $SRC/libxml2
./autogen.sh 
./configure CC=clang CXX=clang++ --with-legacy --without-schematron --without-zlib --without-docs --disable-shared --enable-static {{CT_CONFIGURATION}}
make -j$(nproc) CC=$CC CXX=$CXX