# cd pcre2
./autogen.sh
./configure --disable-shared
make
make install CC=$CC CXX=$CXX

# cp pcre2test $OUT/pcre2test
