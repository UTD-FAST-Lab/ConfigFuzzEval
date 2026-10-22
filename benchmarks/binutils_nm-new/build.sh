./configure CC=clang CXX=clang++ --disable-plugins
make  CC=clang CXX=clang++
cd ./binutils 
./configure CC=$CC CXX=$CXX --disable-plugins {{CT_CONFIGURATION}}
make clean
make CC=$CC CXX=$CXX 
