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
RUN git clone -b dev https://github.com/AFLplusplus/AFLplusplus /aflplusplus && \
    cd /aflplusplus && \
    git checkout 56d5aa3101945e81519a3fac8783d0d8fad82779 || \
    true

# Build without Python support as we don't need it.
# Set AFL_NO_X86 to skip flaky tests.
RUN cd /aflplusplus && \
    unset CFLAGS CXXFLAGS && \
    export CC=clang AFL_NO_X86=1 && \
    PYTHON_INCLUDE=/ make

# GENERAL
ENV FUZZER_COMP=/aflplusplus/afl-clang-fast
ENV FUZZER_COMPXX=/aflplusplus/afl-clang-fast++

CMD ["bash", "-c", "cp -r /aflplusplus /fuzzer_output/"]