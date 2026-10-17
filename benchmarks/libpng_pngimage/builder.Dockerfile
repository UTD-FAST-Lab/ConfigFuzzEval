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

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev

# The download below falls back to the copy in benchmarks/sources/ if it fails
# (the `sources` build context, passed by common/docker_image_builder.py).
COPY --from=sources libpng.tar.xz /fbpp_sources/
RUN timeout 900 git clone https://github.com/pnggroup/libpng.git /libpng || \
    (rm -rf /libpng && mkdir -p /libpng && \
     tar -xJf /fbpp_sources/libpng.tar.xz -C /libpng --strip-components=1)

WORKDIR /libpng

COPY build.sh .

RUN bash build.sh

# # GENERAL
# # Copy supporting files to the docker image
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
CMD ["bash", "-c", "cp -r /libpng/pngimage /benchmark_out_dir/      && cp /rt_grammar.json /benchmark_out_dir/ && cp /manpage.1 /benchmark_out_dir/ && cp -r /carpetfuzz_analysis /benchmark_out_dir/carpetfuzz  &&  cp /build.sh /benchmark_out_dir/  && cp /ranked_stubs.txt /benchmark_out_dir/  &&  cp /dict /benchmark_out_dir/  && cp /run_target.sh /benchmark_out_dir/ && cp -r /seed /benchmark_out_dir/seed "]

