ARG parent_image
FROM $parent_image

RUN apt-get update && \
    apt-get install -y \
    build-essential \
    python3-dev \
    python3-setuptools \
    automake \
    cmake \
    git \
    flex \
    bison \
    libglib2.0-dev \
    libpixman-1-dev \
    cargo \
    libgtk-3-dev \
    # for QEMU mode
    ninja-build \
    gcc-$(gcc --version|head -n1|sed 's/\..*//'|sed 's/.* //')-plugin-dev \
    libstdc++-$(gcc --version|head -n1|sed 's/\..*//'|sed 's/.* //')-dev

# Download afl++.
RUN git clone -b dev https://github.com/AFLplusplus/AFLplusplus /libfuzzer_aflpp && \
    cd /libfuzzer_aflpp && \
    git checkout 56d5aa3101945e81519a3fac8783d0d8fad82779 || \
    true

# Build without Python support as we don't need it.
# Set AFL_NO_X86 to skip flaky tests.
RUN cd /libfuzzer_aflpp && \
    unset CFLAGS CXXFLAGS && \
    export CC=clang AFL_NO_X86=1 && \
    PYTHON_INCLUDE=/ make

ENV FUZZER_COMP=/libfuzzer_aflpp/afl-clang-fast
ENV FUZZER_COMPXX=/libfuzzer_aflpp/afl-clang-fast++
ENV FUZZER_FLAGS="-fsanitize=fuzzer-no-link,address -O2 /libfuzzer_aflpp/utils/aflpp_driver/libAFLDriver.a"

    
# Stash fuzzer assets
RUN mkdir -p /libfuzzer_aflpp/
COPY run.sh /libfuzzer_aflpp/
COPY coverage.py /libfuzzer_aflpp/


ENV CC=clang
ENV CXX=clang++


CMD ["bash", "-c", "cp -r /libfuzzer_aflpp /fuzzer_output/", "&&", "cp /libfuzzer_aflpp/run.sh /fuzzer_output/ ", "&&", "cp /libfuzzer_aflpp/coverage.py /fuzzer_output/"]