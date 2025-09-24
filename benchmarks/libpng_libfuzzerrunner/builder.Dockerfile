ARG parent_image
FROM $parent_image

# Install build tools
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    clang llvm build-essential autoconf libtool automake zlib1g zlib1g-dev git

# Environment for build
# ENV CC=$CC_LIBFUZZER
# ENV CXX=$CXX_LIBFUZZER
RUN apt-get update -qq && apt-get install -y clang-14 llvm-14
ENV CC=clang-14
ENV CXX=clang++-14
ENV CFLAGS="-fprofile-instr-generate -fcoverage-mapping"
ENV CXXFLAGS="-fprofile-instr-generate -fcoverage-mapping"
ENV LIBPNG_DIR=/LIBPNG_FUZZER/libpng
ENV ZLIB_DIR=/LIBPNG_FUZZER/zlib
ENV HARNESS_DIR=/LIBPNG_FUZZER/harness

RUN mkdir /LIBPNG_FUZZER

# Build zlib
RUN git clone --depth 1 https://github.com/madler/zlib.git /LIBPNG_FUZZER/zlib && \
    cd /LIBPNG_FUZZER/zlib && \
    ./configure && \
    make -j$(nproc)

RUN git clone --depth 1 https://github.com/pnggroup/libpng.git /LIBPNG_FUZZER/libpng

COPY harness /LIBPNG_FUZZER/harness
COPY harness/dict.dict /LIBPNG_FUZZER/harness
COPY corpus /LIBPNG_FUZZER/corpus
COPY build.sh  .
RUN bash build.sh

COPY run_target.sh /

# Build the libfuzzer binary
RUN clang++ ${CFLAGS} -std=c++11  -fsanitize=fuzzer,address \
    -I/LIBPNG_FUZZER/libpng -I/LIBPNG_FUZZER/zlib /LIBPNG_FUZZER/harness/libpng_read_fuzzer.cc /LIBPNG_FUZZER/libpng/.libs/libpng16.a /LIBPNG_FUZZER/zlib/libz.a \
    -o /LIBPNG_FUZZER/libfuzzerrunner

# General ASAN/UBSAN for runtime
ENV ASAN_OPTIONS="detect_leaks=0:allocator_may_return_null=1:halt_on_error=1:symbolize=1"
ENV UBSAN_OPTIONS="halt_on_error=1"
RUN mkdir -p /profraw
# Copy output files
CMD ["bash", "-c", "cp /LIBPNG_FUZZER/libfuzzerrunner /benchmark_out_dir/   &&   cp /run_target.sh /benchmark_out_dir/  && cp -r /LIBPNG_FUZZER/harness /benchmark_out_dir/harness && cp -r /LIBPNG_FUZZER/corpus /benchmark_out_dir/corpus"]
