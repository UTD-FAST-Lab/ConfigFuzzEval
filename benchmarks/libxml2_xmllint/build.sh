# cd $SRC/libxml2
apt-get update && apt-get install -y \
  build-essential autoconf libtool pkg-config \
  libreadline-dev libcurl4-openssl-dev libicu-dev \
  liblzma-dev python3-dev zlib1g-dev \
  libxslt1-dev xsltproc
./autogen.sh --disable-shared CC=clang CXX=clang++
./configure CC=clang CXX=clang++ --without-docs --disable-shared --enable-static {{CT_CONFIGURATION}} 

make -j$(nproc) CC=$CC CXX=$CXX

