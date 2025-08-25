FROM fbpp/base

ARG RUNTIME
ENV RUNTIME=${RUNTIME}
ENV OUT=/fuzzer_output

CMD ["bash", "-c", "RUN_TARGET=$(cat /benchmark/run_target.sh) && export RUN_TARGET && exec bash fuzzer/run.sh"]
