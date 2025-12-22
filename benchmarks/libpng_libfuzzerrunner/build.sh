export CPPFLAGS="-I$PWD/LIBPNG_FUZZER/zlib"
export LDFLAGS="-L$PWD/LIBPNG_FUZZER/zlib"
autoreconf -f -i
./configure {{CT_CONFIGURATION}}  --with-zlib-prefix=/LIBPNG_FUZZER/zlib && \
make -j$(nproc) libpng16.la
