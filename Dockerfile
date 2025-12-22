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










# aflpp

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



ARG CC=$FUZZER_COMP
ARG CXX=$FUZZER_COMPXX

ENV CC=/aflplusplus/afl-clang-fast
ENV CXX=/aflplusplus/afl-clang-fast++



# binutils
WORKDIR /
RUN apt-get update && apt-get install -y make cmake flex bison
RUN  wget https://ftp.gnu.org/gnu/binutils/binutils-2.37.tar.xz
RUN tar -xf binutils-2.37.tar.xz
WORKDIR /binutils-2.37
RUN ./configure CC=clang CXX=clang++
RUN make  CC=clang CXX=clang++
WORKDIR ./binutils
RUN ./configure CC=$CC CXX=$CXX {{CT_CONFIGURATION}}
RUN make clean
RUN make CC=$CC CXX=$CXX



#xz
WORKDIR /
RUN wget https://tukaani.org/xz/xz-5.2.5.tar.gz
RUN tar -xzf xz-5.2.5.tar.gz
WORKDIR /xz-5.2.5
RUN ./configure  --disable-shared CC=$CC CXX=$CXX 
RUN make -j$(nproc) CC=$CC CXX=$CXX
RUN mkdir -p /xz_seeds && echo "hello" > /xz_seeds/seed.txt
# RUN /aflplusplus/afl-fuzz     -i /xz_seeds     -o /out22222    /xz-5.2.5/src/xz/xz

#x264
WORKDIR /
RUN apt install -y nasm yasm
RUN git clone https://code.videolan.org/videolan/x264.git
RUN cd /x264
RUN mkdir -p /x264_seeds
WORKDIR /x264_seeds
RUN dd if=/dev/zero bs=1 count=6144 > black_64x64.yuv && dd if=/dev/urandom bs=1 count=6144 > random_64x64.yuv && dd if=/dev/urandom bs=1 count=24576 > random_128x128.yuv && echo "AFLTEST" > corrupt.yuv && head -c 100 black_64x64.yuv > truncated.yuv && touch empty.yuv && dd if=/dev/urandom bs=1 count=50 > garbage.bin
WORKDIR  /x264
RUN ./configure 
RUN make -j$(nproc)
# RUN /aflplusplus/afl-fuzz     -i /x264_seeds     -o /out222    /x264/x264  --input-res 64x64  -o /dev/null @@


#BISON
WORKDIR /
RUN apt-get update && apt-get install -y make cmake flex bison
RUN wget  https://ftp.gnu.org/gnu/bison/bison-3.8.tar.xz
RUN tar -xf bison-3.8.tar.xz
WORKDIR /bison-3.8
RUN ./configure CC=clang CXX=clang++
RUN make -j$(nproc)
RUN cp doc/bison.help /tmp/bison.help
RUN make clean
RUN ./configure CC=$CC CXX=$CXX 
RUN cp /tmp/bison.help doc/bison.help
RUN make -j$(nproc) CC=$CC CXX=$CXX src/bison




#XMLWF
WORKDIR /
RUN apt-get update && apt-get install -y --no-install-recommends \
    make autoconf libtool pkg-config \
    zlib1g-dev liblzma-dev libbsd-dev
# Build requires automake 1.16.3
RUN curl -LO http://mirrors.kernel.org/ubuntu/pool/main/a/automake-1.16/automake_1.16.5-1.3_all.deb && \
    apt install ./automake_1.16.5-1.3_all.deb
RUN git clone --depth 1 https://github.com/libexpat/libexpat.git /libexpat
WORKDIR /libexpat/expat
RUN autoreconf -fi
RUN ./configure  CC=clang CXX=clang++  --disable-shared --without-docbook
RUN make -j$(nproc) CC=$CC CXX=$CXX






#file
WORKDIR /
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev
RUN git clone https://github.com/file/file.git /file
WORKDIR /file
RUN autoreconf -fi
RUN ./configure  CC=clang CXX=clang++ --disable-shared 
RUN make -j$(nproc) CC=$CC CXX=$CXX
RUN make install CC=$CC CXX=$CXX




#pngimage
WORKDIR /
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev
RUN git clone https://github.com/pnggroup/libpng.git /libpng
WORKDIR /libpng
# RUN ./configure  CC=clang CXX=clang++ --disable-shared 
# RUN make check CC=$CC CXX=$CXX
# RUN make install CC=$CC CXX=$CXX




#TIFF
WORKDIR /

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev libjbig0 libjbig-dev
RUN git clone https://gitlab.com/libtiff/libtiff.git /libtiff
WORKDIR /libtiff
RUN ./autogen.sh CC=clang CXX=clang++
RUN ./configure CC=clang CXX=clang++ --disable-shared 
RUN make CC=$CC CXX=$CXX


#XMLLINT
WORKDIR /
RUN apt-get install -y --no-install-recommends \
    make autoconf libtool pkg-config \
    zlib1g-dev liblzma-dev
RUN curl -LO http://mirrors.kernel.org/ubuntu/pool/main/a/automake-1.16/automake_1.16.5-1.3_all.deb && \
    apt install ./automake_1.16.5-1.3_all.deb
RUN git clone --depth 1 https://gitlab.gnome.org/GNOME/libxml2.git /libxml2
WORKDIR /libxml2
RUN apt-get update && apt-get install -y \
    build-essential autoconf libtool pkg-config \
    libreadline-dev libcurl4-openssl-dev libicu-dev \
    liblzma-dev python3-dev zlib1g-dev \
    libxslt1-dev xsltproc doxygen
RUN ./autogen.sh --disable-shared CC=clang CXX=clang++
RUN ./configure CC=clang CXX=clang++ --disable-shared --enable-static  
RUN make -j$(nproc) CC=$CC CXX=$CXX




#PCRE
WORKDIR /
RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake \
    libedit-dev libreadline-dev valgrind lcov git && \
    rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/PCRE2Project/pcre2.git /pcre2 && \
    cd /pcre2 && \
    git submodule update --init --recursive
WORKDIR /pcre2
RUN ./autogen.sh  CC=clang CXX=clang++
RUN ./configure  CC=clang CXX=clang++ --disable-shared 
RUN make CC=$CC CXX=$CXX
RUN make install CC=$CC CXX=$CXX