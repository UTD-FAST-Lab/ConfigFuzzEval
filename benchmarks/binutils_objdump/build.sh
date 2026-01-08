./configure CC=clang CXX=clang++
make  CC=clang CXX=clang++
cd ./binutils
./configure CC=$CC CXX=$CXX {{CT_CONFIGURATION}}
make clean
# Patch resbin.c to use the length parameter or mark it unused
sed -i '1219s/rc_uint_type length)/rc_uint_type length __attribute__((unused)))/' binutils/resbin.c
make CC=$CC CXX=$CXX