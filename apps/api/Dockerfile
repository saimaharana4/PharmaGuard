FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.32
RUN apt-get update && apt-get install --no-install-recommends --only-upgrade -y liblzma5=5.8.1-1+deb13u2 libsqlite3-0=3.46.1-7+deb13u2 && rm -rf /var/lib/apt/lists/*
COPY infra/images/python_runtime.py /build/python_runtime.py
RUN python /build/python_runtime.py
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra embeddings --no-install-project && uv cache clean
COPY apps/api/src apps/api/src
COPY ingestion ingestion
COPY evaluation evaluation
RUN uv sync --frozen --no-dev --extra embeddings && uv cache clean
COPY migrations migrations
COPY alembic.ini ./
COPY config config
ENV HF_HOME=/opt/huggingface
RUN uv run --no-sync python -m ingestion.cache_models && chmod -R a+rX /opt/huggingface
RUN mkdir -p /app/.data && chown 65532:65532 /app/.data && rm -f /runtime/usr/local/bin/uvx /runtime/usr/local/bin/pip3 /runtime/usr/local/bin/pip3.12

FROM gcr.io/distroless/cc-debian13:nonroot@sha256:83b9b50586253821cf63ffcec87d3d94265a093ad30da232039af962dd8f4edf AS runtime
COPY --from=build /runtime/ /
COPY --from=build /app /app
COPY --from=build /opt/huggingface /opt/huggingface
COPY --from=build --chown=65532:65532 /app/.data /app/.data
WORKDIR /app
ENV PATH="/app/.venv/bin:/usr/local/bin:$PATH" LD_LIBRARY_PATH=/usr/local/lib PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/opt/huggingface OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 HF_HUB_OFFLINE=1
USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD ["python", "-c", "import http.client; c=http.client.HTTPConnection('127.0.0.1',8080,timeout=3); c.request('GET','/health'); raise SystemExit(c.getresponse().status != 200)"]
CMD ["python", "-m", "uvicorn", "pharmaguard.main:app", "--host", "0.0.0.0", "--port", "8080"]
