ARG parent_image
FROM $parent_image


RUN apt-get update && \
    apt-get install -y libinih-dev libcurl4-openssl-dev libpng-dev xmlto vim nano htop autoconf automake build-essential libtool cmake git sudo software-properties-common gperf libselinux1-dev  bison texinfo flex zlib1g-dev libexpat1-dev libmpg123-dev wget curl python3-pip unzip pkg-config clang llvm-dev &&\
    python3 -m pip install -U pip
RUN wget -qO - https://apt.llvm.org/llvm-snapshot.gpg.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/llvm-archive-keyring.gpg && \
    add-apt-repository "deb http://apt.llvm.org/jammy/ llvm-toolchain-jammy-18 main" && \
    apt-get update

RUN (apt update && apt install -y llvm-18 clang-18 lld-18 llvm-18-dev  libjson-c-dev libgsl-dev )

# Install Rust (latest version)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

RUN wget https://apt.llvm.org/llvm.sh
RUN chmod +x llvm.sh
RUN ./llvm.sh 18
RUN apt install -y gettext libgpgmepp-dev libfontconfig-dev libfreetype-dev   libjpeg-dev ninja-build libopenjp2-7 libopenjp2-7-dev  libopenjp2-tools libnss3-dev libboost-dev libboost-all-dev  libboost-dev clang-format





# setup LibAFL
RUN git clone https://github.com/AFLplusplus/LibAFL.git /libafl
WORKDIR /libafl
RUN cargo build --release
WORKDIR /libafl/fuzzers/forkserver/libafl-fuzz/
RUN cargo build 
WORKDIR /libafl/fuzzers/forkserver/libafl-fuzz/test
RUN ./test.sh || true
WORKDIR /

# GENERAL
ENV FUZZER_COMP=/libafl/fuzzers/forkserver/libafl-fuzz/test/AFLplusplus/afl-clang-fast
ENV FUZZER_COMPXX=/libafl/fuzzers/forkserver/libafl-fuzz/test/AFLplusplus/afl-clang-fast++
COPY run.sh /libafl
COPY coverage.py /libafl
RUN chmod +x /libafl/run.sh

CMD ["bash", "-c", "cp -r /libafl /fuzzer_output/", "&&", "cp /libafl/run.sh /fuzzer_output/", "&&", "cp /libafl/coverage.py /fuzzer_output/"]