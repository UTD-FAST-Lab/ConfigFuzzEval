#!/bin/bash
./configure --disable-shared
make check
make install

cp pngimage $OUT/pngimage