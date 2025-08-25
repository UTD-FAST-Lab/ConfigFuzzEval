FROM gcr.io/oss-fuzz-base/base-builder

RUN apt-get update -qq && apt-get install -qq -y --no-install-recommends \
    build-essential make autoconf libtool automake zlib1g zlib1g-dev

RUN git clone https://github.com/pnggroup/libpng.git

WORKDIR $SRC/libpng

COPY build.sh $SRC/