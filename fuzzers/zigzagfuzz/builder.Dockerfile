ARG parent_image
FROM $parent_image
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

# GENERAL
ENV FUZZER_COMP=/zigzagfuzz/afl-clang-fast
ENV FUZZER_COMPXX=/zigzagfuzz/afl-clang-fast++
COPY run.sh /zigzagfuzz
COPY coverage.py /zigzagfuzz
RUN chmod +x /zigzagfuzz/run.sh
CMD ["bash", "-c", "cp -r /zigzagfuzz /fuzzer_output/", "&&", "cp /zigzagfuzz/run.sh /fuzzer_output/"]