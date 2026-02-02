./configure --enable-cli CC=$CC CXX=$CXX {{CT_CONFIGURATION}}
make -j$(nproc) CC=$CC CXX=$CXX