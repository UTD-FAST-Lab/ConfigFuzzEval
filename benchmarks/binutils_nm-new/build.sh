# # Patch resbin.c to use the length parameter or mark it unused
# sed -i '1219s/rc_uint_type length)/rc_uint_type length __attribute__((unused)))/' binutils/resbin.c
# ./configure CC=clang CXX=clang++ {{CT_CONFIGURATION}}
# make  CC=clang CXX=clang++
# cd ./binutils
# ./configure CC=$CC CXX=$CXX 
# make clean
# make CC=$CC CXX=$CXX

#!/bin/bash

# 1. Export the AFL++ compilers
export CC="$CC"
export CXX="$CXX"

# 2. Inject flags to silence the fatal Clang warnings that break libiberty
export CFLAGS="$CFLAGS -Wno-error -Wno-gnu-offsetof-extensions -Wno-unknown-warning-option" 
export CXXFLAGS="$CXXFLAGS -Wno-error -Wno-gnu-offsetof-extensions -Wno-unknown-warning-option"

# 3. Patch the file BEFORE compiling anything
sed -i '1219s/rc_uint_type length)/rc_uint_type length __attribute__((unused)))/' binutils/resbin.c

# 4. Configure the top level. Disable NLS to prevent the bfd.po translation crash.
./configure \
    --disable-shared \
    --enable-static \
    --disable-nls \
    {{CT_CONFIGURATION}}

# 5. Build everything together
make -j$(nproc)