# cd pcre2
./autogen.sh
./configure --disable-shared {{CT_CONFIGURATION}}
make CC=$CC CXX=$CXX
make install CC=$CC CXX=$CXX

# cp pcre2test $OUT/pcre2test
