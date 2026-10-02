autoreconf -fi
# --disable-landlock / --disable-libseccomp: file sandboxes itself at runtime, which
# blocks the coverage runtime from writing its .profraw file (Permission denied).
./configure --enable-static CC=clang CXX=clang++ --disable-shared --disable-landlock --disable-libseccomp {{CT_CONFIGURATION}}
# Native build first: it runs src/file -C to compile magic/magic.mgc, which fails when
# src/file is built with a fuzzer compiler whose binaries cannot run outside the fuzzer.
make -j$(nproc)
# Rebuild only the file binary (and libmagic) with the fuzzer compiler.
make -C src clean
make -C src -j$(nproc) CC=$CC CXX=$CXX
