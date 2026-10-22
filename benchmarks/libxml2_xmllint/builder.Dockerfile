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

# GENERAL
ARG CC=$FUZZER_COMP
ARG CXX=$FUZZER_COMPXX
ARG CFLAGS=""

# GENERAL
# CC and CXX are set to clang-18 and clang++-18 wheb building coverage bianries
# If this needs to be changed, update the Dockerfile accordingly.

RUN apt-get install -y --no-install-recommends \
    make autoconf libtool pkg-config \
    zlib1g-dev liblzma-dev
RUN apt-get update && apt-get install -y \
    build-essential autoconf libtool pkg-config \
    libreadline-dev libcurl4-openssl-dev \
    liblzma-dev python3-dev libicu-dev \
    libxslt1-dev xsltproc zlib1g-dev

# Build requires automake 1.16.3
# RUN curl -LO http://mirrors.kernel.org/ubuntu/pool/main/a/automake-1.16/automake_1.16.5-1.3_all.deb && \
    # apt install ./automake_1.16.5-1.3_all.deb

RUN apt-get install -y automake
# The download below falls back to the copy in benchmarks/sources/ if it fails
# (the `sources` build context, passed by common/docker_image_builder.py).
COPY --from=sources libxml2.tar.xz /fbpp_sources/
RUN timeout 900 git clone --depth 1 https://gitlab.gnome.org/GNOME/libxml2.git /libxml2 || \
    (rm -rf /libxml2 && mkdir -p /libxml2 && \
     tar -xJf /fbpp_sources/libxml2.tar.xz -C /libxml2 --strip-components=1)
WORKDIR /libxml2
COPY build.sh .

RUN bash build.sh

# GENERAL
# Copy supporting files to the docker image
COPY run_target.sh /
COPY seed /seed
COPY dict /
COPY ranked_stubs.txt /
COPY build.sh /

COPY rt_grammar.json /

# CarpetFuzz/ProphetFuzz inputs: the target's man page and CarpetFuzz's

# analysis of it (fuzzers/carpetfuzz/analysis/generate.sh).

COPY manpage.1 /

COPY carpetfuzz /carpetfuzz_analysis
# Copy the binary to fuzz
CMD ["bash", "-c", "cp -r /libxml2/xmllint /benchmark_out_dir/    && cp /rt_grammar.json /benchmark_out_dir/ && cp /manpage.1 /benchmark_out_dir/ && cp -r /carpetfuzz_analysis /benchmark_out_dir/carpetfuzz  &&  cp /build.sh /benchmark_out_dir/  && cp /ranked_stubs.txt /benchmark_out_dir/  && cp /run_target.sh /benchmark_out_dir/  && cp /dict /benchmark_out_dir/ && cp -r /seed /benchmark_out_dir/seed "]