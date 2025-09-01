./configure CC=clang CXX=clang++
make -j$(nproc)
cp doc/bison.help /tmp/bison.help
make clean
./configure CC=$CC CXX=$CXX {{CT_CONFIGURATION}}
cp /tmp/bison.help doc/bison.help
make -j$(nproc) CC=$CC CXX=$CXX src/bison
