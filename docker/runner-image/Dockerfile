FROM fbpp/base

ARG COVERAGE=false
ENV OUT=/fuzzer_output
ENV COVERAGE=${COVERAGE}

# ENV RUNTIME is defined at docker run
ENV RUNTIME=0


# Single CMD, branch at runtime
CMD ["bash", "-c", " \
    if [ \"$COVERAGE\" = \"false\" ]; then \
        RUN_TARGET=$(cat /benchmark/run_target.sh); \
        export RUN_TARGET; \
        exec bash fuzzer/run.sh; \
    else \
        RUN_TARGET=$(cat /benchmark/run_target.sh); \
        export RUN_TARGET; \
        exec python3 fuzzer/coverage.py; \
    fi \
"]
