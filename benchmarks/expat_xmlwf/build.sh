# cd $SRC/libxml2
autoreconf -fi

./configure --disable-shared --without-docbook {{CT_CONFIGURATION}} 

make -j$(nproc) CC=$CC CXX=$CXX

