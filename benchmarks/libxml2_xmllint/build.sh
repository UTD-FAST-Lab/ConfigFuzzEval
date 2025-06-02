# cd $SRC/libxml2
./autogen.sh
./configure --without-python --with-threads=no --with-zlib=no --with-lzma=no --disable-shared

make -j$(nproc)

ls -a -l

# Copy the binary to the destination directory
cp xmllint $OUT/xmllint
