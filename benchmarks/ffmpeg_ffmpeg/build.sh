./configure --cc="$CC" --cxx="$CXX" --enable-static --disable-shared --disable-asm --enable-cross-compile --disable-doc --pkg-config-flags="--static" --extra-ldexeflags="-static" --extra-cflags="$CFLAGS" \
--extra-cxxflags="$CXXFLAGS" \
--extra-ldflags="$CFLAGS" \
--extra-ldexeflags="$CFLAGS" {{CT_CONFIGURATION}} 
make CC=$CC CXX=$CXX