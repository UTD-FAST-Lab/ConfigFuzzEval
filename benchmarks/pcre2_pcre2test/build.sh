# cd pcre2
./autogen.sh
./configure --disable-shared {{CT_CONFIGURATION}}
make
make install

cp pcre2test $OUT/pcre2test
