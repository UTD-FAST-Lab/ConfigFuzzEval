#
# This Dockerfile for CarpetFuzz uses Ubuntu 22.04 and
# installs LLVM 12 for afl-clang-lto support.
#

From ubuntu:22.04


# Install required dependencies
RUN apt-get update
RUN apt install -y \
    clang-12 \
    clang-tools-12 \
    clang-12-doc \
    libclang-common-12-dev \
    libclang-12-dev \
    libclang-cpp12-dev \
    lld-12 \
    lldb-12 \
    llvm-12 \
    llvm-12-dev \
    llvm-12-doc \
    llvm-12-runtime \
    llvm-12-tools \
    libomp-12-dev


RUN git clone https://github.com/waugustus/CarpetFuzz-fuzzer /

WORKDIR CarpetFuzz-fuzzer
 
RUN make CC=clang-12 LLVM_CONFIG=llvm-config-12