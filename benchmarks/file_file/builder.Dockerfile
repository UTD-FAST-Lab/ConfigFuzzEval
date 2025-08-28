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

RUN git clone https://github.com/file/file.git

WORKDIR file
COPY build.sh .

RUN bash build.sh

# GENERAL
# Copy supporting files to the docker image
COPY run_target.sh /
COPY seed /seed

# Copy the binary to fuzz
CMD ["bash", "-c", "cp -r /file/src/file /benchmark_out_dir/ && cp /run_target.sh /benchmark_out_dir/ && cp -r /seed /benchmark_out_dir/seed"]

