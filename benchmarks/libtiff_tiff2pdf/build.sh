#!/bin/bash
./autogen.sh
./configure --disable-shared
make check
make
make install
cp tools/tiff2pdf $OUT/tiff2pdf
mkdir $OUT/seeds
cp test/images/*.tiff $OUT/seeds/