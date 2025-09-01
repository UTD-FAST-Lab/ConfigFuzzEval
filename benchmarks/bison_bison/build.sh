./configure CC=clang CXX=clang++
make -j$(nproc)
cp doc/bison.help /tmp/bison.help
make clean
./configure CC=/zigzagfuzz/afl-clang-fast CXX=/zigzagfuzz/afl-clang-fast++
cp /tmp/bison.help doc/bison.help
make -j$(nproc) CC=$CC CXX=$CXX src/bison
