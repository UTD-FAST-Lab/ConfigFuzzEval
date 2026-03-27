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

ARG parent_image
FROM $parent_image

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev libjbig0 libjbig-dev
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    clang llvm build-essential autoconf automake libtool pkg-config git python3 python3-pip
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    zlib1g-dev \
    libjpeg-dev \
    liblzma-dev \
    libjbig-dev \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y wget gnupg lsb-release && \
    wget https://apt.llvm.org/llvm.sh && chmod +x llvm.sh && \
    ./llvm.sh 18 && \
    ln -sf /usr/bin/clang-18 /usr/bin/clang && \
    ln -sf /usr/bin/clang++-18 /usr/bin/clang++ && \
    ln -sf /usr/bin/llvm-profdata-18 /usr/bin/llvm-profdata && \
    ln -sf /usr/bin/llvm-cov-18 /usr/bin/llvm-cov
# Install Clang 14 (matching OSS-Fuzz baseline)
RUN apt-get update -qq && apt-get install -y clang-14 llvm-14
ENV CC=clang-18
ENV CXX=clang++-18
ENV CFLAGS="-fprofile-instr-generate -fcoverage-mapping"
ENV CXXFLAGS="-fprofile-instr-generate -fcoverage-mapping"
# Setup directories
ENV LIBTIFF_DIR=/LIBTIFF_FUZZER/libtiff
ENV HARNESS_DIR=/LIBTIFF_FUZZER/harness

RUN mkdir -p /LIBTIFF_FUZZER
RUN git clone https://gitlab.com/libtiff/libtiff.git /LIBTIFF_FUZZER/libtiff


COPY harness /LIBTIFF_FUZZER/harness
COPY harness/dict.dict /LIBTIFF_FUZZER/harness
COPY corpus /LIBTIFF_FUZZER/corpus
COPY build.sh .
RUN bash build.sh || true
COPY run_target.sh /
COPY load_src.sh /



ENV FUZZER_FLAGS=""
ARG CC=$FUZZER_COMP
ARG CXX=$FUZZER_COMPXX
ARG FUZZER_FLAGS=$FUZZER_FLAGS


# Build fuzz target
WORKDIR /LIBTIFF_FUZZER
RUN apt-get update && apt-get install -y libdeflate-dev
RUN ${CXX} ${CFLAGS} ${FUZZER_FLAGS} -std=c++11 \
    -I/LIBTIFF_FUZZER/libtiff/libtiff \
    /LIBTIFF_FUZZER/harness/libtiff_tiff_read_fuzzer.cc \
    /LIBTIFF_FUZZER/libtiff/libtiff/.libs/libtiff.a \
    -o /LIBTIFF_FUZZER/libfuzzerrunner \
    -lz -ljpeg -llzma -ljbig -ldeflate


# General ASAN/UBSAN for runtime
ENV ASAN_OPTIONS="detect_leaks=0:allocator_may_return_null=1:halt_on_error=1:symbolize=1"
ENV UBSAN_OPTIONS="halt_on_error=1"

# Profiling dir
RUN mkdir -p /profraw

# Copy output artifacts to benchmark_out_dir
CMD ["bash", "-c", "cp -r /LIBTIFF_FUZZER/harness /benchmark_out_dir/harness && \
    cp -r /LIBTIFF_FUZZER/corpus /benchmark_out_dir/corpus && \
    cp /run_target.sh /benchmark_out_dir/ && \
    cp -r /load_src.sh /benchmark_out_dir/ && \
    cp /LIBTIFF_FUZZER/libfuzzerrunner /benchmark_out_dir/"]
