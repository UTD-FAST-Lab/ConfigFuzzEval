# cd $SRC/bison-3.8
./configure {{CT_CONFIGURATION}} 
make -j$(nproc) CC=$CC CXX=$CXX
# cp $SRC/bison-3.8/src/bison $OUT/bison
# make clean
# ./configure CC=clang CXX=clang++ CFLAGS="-fprofile-instr-generate -fcoverage-mapping" LDFLAGS="-fprofile-instr-generate"
# make CC=clang CXX=clang++
# mv $SRC/bison-3.8/src/bison coverage_binary_bison
# cp coverage_binary_bison $OUT/coverage_binary_bison
