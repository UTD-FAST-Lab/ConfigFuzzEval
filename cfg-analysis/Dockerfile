# Base image with Java
FROM ubuntu:22.04

# Avoid interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# Argument to specify additional script to load source code
ARG LOAD_SRC_SCRIPT=""

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    openjdk-11-jdk \
    make \
    wget \
    curl \
    bison \
    gcc \
    libz3-java \
    libjson-java \
    sat4j \
    && rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Clone SuperC repository
RUN git clone https://github.com/appleseedlab/superc.git 

# Set JAVA_DEV_ROOT
ENV JAVA_DEV_ROOT=/superc/

# Build CLASSPATH with included libraries and system-installed libraries
ENV CLASSPATH=$JAVA_DEV_ROOT/classes:$JAVA_DEV_ROOT/bin/junit.jar:$JAVA_DEV_ROOT/bin/antlr.jar:$JAVA_DEV_ROOT/bin/javabdd.jar:$JAVA_DEV_ROOT/bin/json-simple-1.1.1.jar:/usr/share/java/org.sat4j.core.jar:/usr/share/java/com.microsoft.z3.jar:/usr/share/java/json-lib.jar

# Set JVM arguments
ENV JAVA_ARGS="-Xms2048m -Xmx4048m -Xss128m"

RUN export JAVA_DEV_ROOT CLASSPATH JAVA_ARGS JAVA_HOME

WORKDIR /superc/
RUN make configure
RUN make

COPY cfg-analysis/run_superc.sh /superc/run_superc.sh
COPY ${LOAD_SRC_SCRIPT} /load_src.sh

WORKDIR /
RUN bash load_src.sh
WORKDIR /superc/


# CMD ["bash", "run_superc.sh"]
