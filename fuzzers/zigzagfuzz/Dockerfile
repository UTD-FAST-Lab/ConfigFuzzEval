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

#zzf
RUN apt-get update && \
    apt-get install -y libpng-dev libcurl4-openssl-dev xmlto gawk vim nano htop autoconf automake build-essential libtool cmake git sudo software-properties-common gperf libselinux1-dev  bison texinfo flex zlib1g-dev libexpat1-dev libmpg123-dev wget curl python3-pip unzip pkg-config clang llvm-dev &&\
    python3 -m pip install -U pip

RUN (apt update && apt install -y llvm-13 clang-13 lld-13 libjson-c-dev libgsl-dev )
RUN wget https://apt.llvm.org/llvm.sh
RUN chmod +x llvm.sh
RUN sudo ./llvm.sh 18
RUN sudo apt install -y gettext libgpgmepp-dev libfontconfig-dev libfreetype-dev   libjpeg-dev ninja-build libopenjp2-7 libopenjp2-7-dev  libopenjp2-tools libnss3-dev libboost-dev libboost-all-dev  libboost-dev clang-format

# setup ZZF
RUN git clone https://github.com/swtv-kaist/ZigZagFuzz.git /zigzagfuzz
WORKDIR /zigzagfuzz
RUN git checkout tosem_2024
RUN make LLVM_CONFIG=llvm-config-13 CC=clang-13

# # GENERAL
# ENV FUZZER_COMP=/zigzagfuzz/afl-clang-fast
# ENV FUZZER_COMPXX=/zigzagfuzz/afl-clang-fast++
# COPY run.sh /zigzagfuzz
# COPY coverage.py /zigzagfuzz
# RUN chmod +x /zigzagfuzz/run.sh
# CMD ["bash", "-c", "cp -r /zigzagfuzz /fuzzer_output/", "&&", "cp /zigzagfuzz/run.sh /fuzzer_output/"]

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev libjbig0 libjbig-dev

RUN git clone https://gitlab.com/libtiff/libtiff.git

WORKDIR ./libtiff

RUN ./autogen.sh CC=clang CXX=clang++
RUN ./configure CC=clang CXX=clang++ --disable-shared
ENV FUZZER_COMP=/zigzagfuzz/afl-clang-fast
ENV FUZZER_COMPXX=/zigzagfuzz/afl-clang-fast++
ENV CC=/zigzagfuzz/afl-clang-fast
ENV CXX=/zigzagfuzz/afl-clang-fast++
# RUN make check CC=$CC CXX=$CXX
RUN make CC=$CC CXX=$CXX
# RUN make install CC=$CC CXX=$CXX


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




WORKDIR /

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev

RUN git clone https://github.com/pnggroup/libpng.git /libpng

WORKDIR /libpng