#!/bin/bash
./configure --disable-shared 
make check
make install

cp pngstest $OUT/pngstest
mkdir $OUT/seeds
cp *.png $OUT/seeds