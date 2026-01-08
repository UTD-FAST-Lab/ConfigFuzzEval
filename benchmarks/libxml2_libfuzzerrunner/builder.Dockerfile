ARG parent_image
FROM $parent_image
RUN apt-get install -y --no-install-recommends \
    make autoconf libtool pkg-config \
    zlib1g-dev liblzma-dev
RUN apt-get update && apt-get install -y \
    build-essential autoconf libtool pkg-config \
    libreadline-dev libcurl4-openssl-dev libicu-dev \
    liblzma-dev python3-dev zlib1g-dev \
    libxslt1-dev xsltproc doxygen
# Build requires automake 1.16.3
RUN curl -LO http://mirrors.kernel.org/ubuntu/pool/main/a/automake-1.16/automake_1.16.5-1.3_all.deb && \
    apt install ./automake_1.16.5-1.3_all.deb
# Install build tools
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    clang llvm build-essential autoconf automake libtool pkg-config git python3 python3-pip

# Install Clang 14 (matching OSS-Fuzz baseline)
RUN apt-get update -qq && apt-get install -y clang-14 llvm-14
RUN apt-get update && apt-get install -y wget gnupg lsb-release && \
    wget https://apt.llvm.org/llvm.sh && chmod +x llvm.sh && \
    ./llvm.sh 18 && \
    ln -sf /usr/bin/clang-18 /usr/bin/clang && \
    ln -sf /usr/bin/clang++-18 /usr/bin/clang++ && \
    ln -sf /usr/bin/llvm-profdata-18 /usr/bin/llvm-profdata && \
    ln -sf /usr/bin/llvm-cov-18 /usr/bin/llvm-cov
ENV CC=clang-18
ENV CXX=clang++-18
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
COPY harness/dict.dict /LIBXML2_FUZZER/harness
COPY corpus /LIBXML2_FUZZER/corpus
WORKDIR /LIBXML2_FUZZER/libxml2
# Copy build script and run it
COPY build.sh .
RUN bash build.sh

# Copy runner script
COPY run_target.sh /
ENV FUZZER_FLAGS=""
ARG CC=$FUZZER_COMP
ARG CXX=$FUZZER_COMPXX
ARG FUZZER_FLAGS=$FUZZER_FLAGS

# Copy load source script
COPY load_src.sh /

# Build the fuzz target binary
RUN ${CXX} ${CFLAGS} ${FUZZER_FLAGS} -std=c++11  \
    -I/LIBXML2_FUZZER/libxml2/include \
    /LIBXML2_FUZZER/harness/libxml2_xml_read_fuzzer.cc \
    /LIBXML2_FUZZER/libxml2/.libs/libxml2.a \
    -o /LIBXML2_FUZZER/libfuzzerrunner

# General ASAN/UBSAN for runtime
ENV ASAN_OPTIONS="detect_leaks=0:allocator_may_return_null=1:halt_on_error=1:symbolize=1"
ENV UBSAN_OPTIONS="halt_on_error=1"

# Profiling dir
RUN mkdir -p /profraw

# Copy output artifacts to benchmark_out_dir
CMD ["bash", "-c", "cp /LIBXML2_FUZZER/libfuzzerrunner /benchmark_out_dir/ && \
    cp -r /LIBXML2_FUZZER/harness /benchmark_out_dir/harness && \
    cp -r /LIBXML2_FUZZER/corpus /benchmark_out_dir/corpus && \
    cp /run_target.sh /benchmark_out_dir/ && \
    cp -r /load_src.sh /benchmark_out_dir/"]
