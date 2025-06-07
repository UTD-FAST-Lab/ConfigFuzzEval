FROM gcr.io/oss-fuzz-base/base-builder
RUN apt-get update && apt-get install -y make cmake flex bison
RUN wget  https://ftp.gnu.org/gnu/bison/bison-3.8.tar.xz
RUN tar -xf bison-3.8.tar.xz
WORKDIR ./bison-3.8

WORKDIR $SRC
COPY build.sh $SRC/

