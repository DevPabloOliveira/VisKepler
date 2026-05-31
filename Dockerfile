FROM mambaorg/micromamba:2.6-debian12-slim

USER root
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update >/dev/null; \
    apt-get install -y --only-upgrade libgnutls30 libtinfo6 ncurses-base ncurses-bin perl-base zlib1g >/dev/null; \
    rm -rf /var/lib/apt/lists/*

USER $MAMBA_USER

WORKDIR /app

ENV CONDA_REMOTE_CONNECT_TIMEOUT_SECS=30
ENV CONDA_REMOTE_READ_TIMEOUT_SECS=300
ENV CONDA_REMOTE_MAX_RETRIES=10
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10

COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml

RUN set -eux; \
    attempt=1; \
    max_attempts=3; \
    while [ "$attempt" -le "$max_attempts" ]; do \
        if micromamba install -y -n base -f /tmp/environment.yml; then \
            micromamba clean --all --yes; \
            break; \
        fi; \
        if [ "$attempt" -eq "$max_attempts" ]; then \
            exit 1; \
        fi; \
        attempt=$((attempt + 1)); \
        sleep 15; \
    done

RUN micromamba run -n base python -m pip install --no-cache-dir --force-reinstall setuptools==80.9.0

COPY --chown=$MAMBA_USER:$MAMBA_USER . ./

USER root
RUN mkdir -p /shared && chown -R $MAMBA_USER:$MAMBA_USER /app /shared

USER $MAMBA_USER

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["micromamba", "run", "-n", "base", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
