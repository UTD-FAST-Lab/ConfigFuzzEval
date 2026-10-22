./configure CC=clang CXX=clang++
make -j$(nproc)
cp doc/bison.help /tmp/bison.help
make clean
# Configure with plain clang: configure runs the test programs it compiles, and with
# a fuzzer compiler they can misbehave (VAFuzz's argv instrumentation makes a test
# that re-runs itself with "-child" start copies of itself without end). The fuzzer
# compiler ($CC/$CXX) is used for the actual build below.
./configure --disable-nls --without-libtextstyle-prefix --disable-dependency-tracking CC=clang CXX=clang++ {{CT_CONFIGURATION}}

cp /tmp/bison.help doc/bison.help
# make clean removed gnulib's generated headers (BUILT_SOURCES), which only a full
# "make" regenerates; generate them before building just src/bison.
BUILT_SOURCES=$(printf 'print-built-sources:\n\t@echo $(BUILT_SOURCES)\n' | make -s -f Makefile -f - print-built-sources)
make -j$(nproc) CC=$CC CXX=$CXX $BUILT_SOURCES
make -j$(nproc) CC=$CC CXX=$CXX src/bison