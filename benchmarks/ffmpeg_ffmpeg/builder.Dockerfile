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
ENV CFLAGS="$CFLAGS $FUZZER_FLAGS"
ENV CXXFLAGS="$CXXFLAGS $FUZZER_FLAGS"
ENV AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1
ENV AFL_SKIP_CPUFREQ=1

# Find the line that looks like: RUN apt-get update && apt-get install -y ...
# And add libgnutls28-dev to it:

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgnutls28-dev \
    && rm -rf /var/lib/apt/lists/*

# GENERAL
# CC and CXX are set to clang-18 and clang++-18 wheb building coverage bianries
# If this needs to be changed, update the Dockerfile accordingly.
WORKDIR /
# RUN  git clone --depth 1 https://github.com/FFmpeg/FFmpeg.git /ffmpeg-4.7
# WORKDIR /ffmpeg-4.7
RUN  git clone --depth 1 https://github.com/FFmpeg/FFmpeg.git /ffmpeg-4.7
WORKDIR /ffmpeg-4.7
COPY build.sh .
RUN bash build.sh || true
# GENERAL
# Copy supporting files to the docker image
COPY run_target.sh /
COPY seed /seed
COPY dict /
COPY ranked_stubs.txt /
COPY build.sh /
COPY rt_grammar.json /
# Copy the binary to fuzz
CMD ["bash", "-c", "cp /rt_grammar.json /benchmark_out_dir/  &&  cp /ranked_stubs.txt /benchmark_out_dir/  && cp /build.sh /benchmark_out_dir/  &&  cp /run_target.sh /benchmark_out_dir/  && cp /dict /benchmark_out_dir/ &&  cp -r /seed /benchmark_out_dir/seed  && cp -r /ffmpeg-4.7/ffmpeg /benchmark_out_dir/"]
# CMD ["bash", "-c", "cp -r /ffmpeg-4.7/ffmpeg /benchmark_out_dir/    && cp /rt_grammar.json /benchmark_out_dir/  &&  cp /ranked_stubs.txt /benchmark_out_dir/  && cp /build.sh /benchmark_out_dir/  &&  cp /run_target.sh /benchmark_out_dir/  && cp /dict /benchmark_out_dir/ &&  cp -r /seed /benchmark_out_dir/seed"]