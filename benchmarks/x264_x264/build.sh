./configure --enable-cli CC=$CC CXX=$CXX --extra-ldflags="$CFLAGS" {{CT_CONFIGURATION}}
make -j$(nproc) CC=$CC CXX=$CXX