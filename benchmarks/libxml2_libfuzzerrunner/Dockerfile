# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################

# Base image: Ubuntu 22.04 (Jammy)
FROM ubuntu:22.04

# Ensure non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Update and install common dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    wget curl git build-essential ninja-build pkg-config cmake \
    automake autoconf libtool libglib2.0-dev libpixman-1-dev \
    python3 python3-pip python3-setuptools python3-dev \
    zlib1g-dev liblzma-dev libbz2-dev libssl-dev libdeflate0 libjbig0 libjbig-dev \
    libxml2-dev libsqlite3-dev libpng-dev libjpeg-dev \
    llvm \
    && rm -rf /var/lib/apt/lists/*

# Install Clang/LLVM 18
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg lsb-release software-properties-common && \
    wget https://apt.llvm.org/llvm.sh && chmod +x llvm.sh && \
    ./llvm.sh 18 all && \
    rm -f llvm.sh && \
    rm -rf /var/lib/apt/lists/*

# Set Clang 18 as default compiler
RUN update-alternatives --install /usr/bin/clang clang /usr/bin/clang-18 100 && \
    update-alternatives --install /usr/bin/clang++ clang++ /usr/bin/clang++-18 100 && \
    update-alternatives --install /usr/bin/ld ld /usr/bin/ld.lld-18 100 && \
    update-alternatives --install /usr/bin/llvm-config llvm-config /usr/bin/llvm-config-18 100 && \
    update-alternatives --install /usr/bin/llvm-profdata llvm-profdata /usr/bin/llvm-profdata-18 100 && \
    update-alternatives --install /usr/bin/llvm-cov llvm-cov /usr/bin/llvm-cov-18 100

# Install AFL++ common Python deps
RUN pip3 install --no-cache-dir \
    psutil numpy matplotlib seaborn

# DEBUG: Print clang version on container startup
# CMD ["clang --version"]
















WORKDIR /

RUN apt-get install -y --no-install-recommends \
    make autoconf libtool pkg-config \
    zlib1g-dev liblzma-dev

# Build requires automake 1.16.3
RUN curl -LO http://mirrors.kernel.org/ubuntu/pool/main/a/automake-1.16/automake_1.16.5-1.3_all.deb && \
    apt install ./automake_1.16.5-1.3_all.deb
# Install build tools
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    clang llvm build-essential autoconf automake libtool pkg-config git python3 python3-pip

# Install Clang 14 (matching OSS-Fuzz baseline)
RUN apt-get update -qq && apt-get install -y clang-14 llvm-14
ENV CC=clang-14
ENV CXX=clang++-14
ENV CFLAGS="-fprofile-instr-generate -fcoverage-mapping"
ENV CXXFLAGS="-fprofile-instr-generate -fcoverage-mapping"

# Setup directories
ENV LIBXML2_DIR=/LIBXML2_FUZZER/libxml2
ENV HARNESS_DIR=/LIBXML2_FUZZER/harness

RUN mkdir -p /LIBXML2_FUZZER

# Clone libxml2
RUN git clone --depth 1 https://gitlab.gnome.org/GNOME/libxml2.git /LIBXML2_FUZZER/libxml2

# Copy harness, dict, and corpus
COPY harness /LIBXML2_FUZZER/harness
COPY corpus /LIBXML2_FUZZER/corpus
COPY dict /LIBXML2_FUZZER/dict

# Copy build script and run it
COPY build.sh .
RUN bash build.sh || true

# Copy runner script
COPY run_target.sh /

# Build the fuzz target binary
RUN clang++ ${CFLAGS} -std=c++11 -fsanitize=fuzzer,address \
    -I/LIBXML2_FUZZER/libxml2/include \
    /LIBXML2_FUZZER/harness/libxml2_xml_read_fuzzer.cc \
    /LIBXML2_FUZZER/libxml2/.libs/libxml2.a \
    -o /LIBXML2_FUZZER/libfuzzerrunner

# General ASAN/UBSAN for runtime
ENV ASAN_OPTIONS="detect_leaks=0:allocator_may_return_null=1:halt_on_error=1:symbolize=1"
ENV UBSAN_OPTIONS="halt_on_error=1"

# Profiling dir
RUN mkdir -p /profraw