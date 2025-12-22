./configure CC=clang CXX=clang++
make  CC=clang CXX=clang++
cd ./binutils 
./configure CC=$CC CXX=$CXX {{CT_CONFIGURATION}}
make clean
make CC=$CC CXX=$CXX 
