#!/bin/bash
./configure --disable-shared
make check
make install

cp pngimage $OUT/pngimage
mkdir $OUT/seeds
cp *.png $OUT/seeds