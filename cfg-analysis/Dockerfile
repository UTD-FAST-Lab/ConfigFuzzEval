# SuperC presence-condition analysis (common/superc.py runs it).
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

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
    python3 \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# SuperC at a fixed commit, so the analysis is the same every time the image is built.
ARG SUPERC_COMMIT=ea12dd3e87568e2944291e0a552163c9f10fd86b
RUN git clone https://github.com/appleseedlab/superc.git /superc && \
    git -C /superc checkout $SUPERC_COMMIT

ENV JAVA_DEV_ROOT=/superc/
ENV CLASSPATH=$JAVA_DEV_ROOT/classes:$JAVA_DEV_ROOT/bin/junit.jar:$JAVA_DEV_ROOT/bin/antlr.jar:$JAVA_DEV_ROOT/bin/javabdd.jar:$JAVA_DEV_ROOT/bin/json-simple-1.1.1.jar:/usr/share/java/org.sat4j.core.jar:/usr/share/java/com.microsoft.z3.jar:/usr/share/java/json-lib.jar

WORKDIR /superc/
RUN make configure && make

COPY run_superc.sh /run_superc.sh
RUN chmod +x /run_superc.sh

WORKDIR /
ENTRYPOINT ["/run_superc.sh"]
