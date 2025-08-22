# cd $SRC/libxml2
apt-get update && apt-get install -y \
  build-essential autoconf libtool pkg-config \
  libreadline-dev libcurl4-openssl-dev libicu-dev \
  liblzma-dev python3-dev zlib1g-dev \
  libxslt1-dev xsltproc doxygen

./autogen.sh --disable-shared
./configure {{CT_CONFIGURATION}} 

make -j$(nproc) CC=$FUZZER_COMP

# Copy the binary to the destination directory
cp xmllint $OUT/xmllint
