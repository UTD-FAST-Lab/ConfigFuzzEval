./configure --enable-xz --disable-shared  --enable-static --disable-werror CC=clang CXX=clang++ {{CT_CONFIGURATION}}
make -j$(nproc) CC=$CC CXX=$CXX 