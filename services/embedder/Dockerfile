FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EMBEDDER_CACHE_DIR=/models

WORKDIR /app

COPY pyproject.toml requirements.lock ./
COPY src ./src
# INSTALL_EXTRAS: "" (default) | "bedrock" | "bedrock,test"
ARG INSTALL_EXTRAS=""
RUN pip install --no-cache-dir -c requirements.lock ".${INSTALL_EXTRAS:+[$INSTALL_EXTRAS]}"

# Bake the model into the image so a container starts offline and fast.
# Use --build-arg BAKE_MODEL=0 for a model-less image (bedrock/fake backends).
ARG BAKE_MODEL=1
ARG EMBEDDER_MODEL_NAME=jinaai/jina-embeddings-v2-small-en
RUN if [ "$BAKE_MODEL" = "1" ]; then \
      python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${EMBEDDER_MODEL_NAME}', cache_dir='/models')"; \
    fi

# Model files are world-readable, so the unprivileged user needs no chown (which would duplicate the layer).
RUN useradd --no-create-home --uid 10001 embedder
USER embedder

EXPOSE 8100
HEALTHCHECK --interval=5s --timeout=3s --retries=24 --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/health', timeout=2)"
CMD ["uvicorn", "embedder_service.app:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8100"]
