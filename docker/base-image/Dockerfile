# Base image: Ubuntu 22.04 (Jammy)
FROM ubuntu:22.04

# Ensure non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive
ENV AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1
ENV AFL_SKIP_CPUFREQ=1
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
    psutil numpy matplotlib seaborn z3-solver

# DEBUG: Print clang version on container startup
# CMD ["clang --version"]
