# cd $SRC/libxml2
./autogen.sh 
./configure CC=clang CXX=clang++ --without-python --without-docs --disable-shared --enable-static {{CT_CONFIGURATION}}
make -j$(nproc) CC=$CC CXX=$CXX