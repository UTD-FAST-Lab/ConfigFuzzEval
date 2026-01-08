./configure --enable-xz --disable-shared  --enable-static CC=$CC CXX=$CXX {{CT_CONFIGURATION}}
make -j$(nproc) CC=$CC CXX=$CXX 