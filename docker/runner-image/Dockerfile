FROM fbpp/base

ARG RUNTIME
ENV RUNTIME=${RUNTIME}
ENV OUT=/fuzzer_output
CMD ["bash", "-c", "bash benchmark/run_target.sh && bash fuzzer/run.sh"]
