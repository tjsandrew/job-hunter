"""FastAPI app: validation, limits, error shape. Knows nothing about which model sits behind it."""
from __future__ import annotations

import logging
import math
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .backends import EmbeddingBackend, build_backend
from .config import Settings
from .errors import ServiceError
from .schemas import EmbedRequest, EmbedResponse, ModelInfo, Usage

log = logging.getLogger("embedder_service")


class _State:
    """Holds the backend once loaded. Loading happens off the request path so /health can answer 503."""

    def __init__(self, settings: Settings, backend: EmbeddingBackend | None):
        self.settings = settings
        self.backend = backend
        self.load_error: str | None = None

    def load(self) -> None:
        try:
            started = time.perf_counter()
            self.backend = build_backend(self.settings)
            log.info("backend=%s model=%s dims=%d loaded in %.1fs", self.backend.name, self.backend.model_id,
                     self.backend.dimensions, time.perf_counter() - started)
        except Exception as exc:  # reported via /health; never crash the process silently
            self.load_error = f"{type(exc).__name__}: {exc}"
            log.error("backend failed to load: %s", self.load_error)


def create_app(settings: Settings | None = None, backend: EmbeddingBackend | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    state = _State(settings, backend)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if state.backend is None:
            threading.Thread(target=state.load, name="backend-loader", daemon=True).start()
        yield

    app = FastAPI(title="Embedder service", version="0.1.0", lifespan=lifespan)
    app.state.embedder = state

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        err = ServiceError(422, "invalid_request", f"{where or 'body'}: {first.get('msg', 'invalid request')}")
        return JSONResponse(status_code=err.status, content=err.body())

    def ready_backend() -> EmbeddingBackend:
        if state.backend is None:
            detail = state.load_error or "model is still loading"
            raise ServiceError(503, "not_ready", detail)
        return state.backend

    @app.get("/health")
    def health():
        backend_ = ready_backend()
        return {"status": "ok", "backend": backend_.name, "model": backend_.model_id}

    @app.get("/v1/model", response_model=ModelInfo)
    def model_info():
        b = state.backend
        return ModelInfo(
            model=b.model_id if b else settings.model_name,
            backend=b.name if b else settings.backend,
            dimensions=b.dimensions if b else settings.dimensions,
            normalized=b.normalized if b else True,
            max_texts=settings.max_texts,
            max_chars=settings.max_chars,
            ready=b is not None,
        )

    @app.post("/v1/embed", response_model=EmbedResponse)
    def embed(request: EmbedRequest):
        inputs = request.inputs
        if not inputs:
            raise ServiceError(422, "no_inputs", "inputs must contain at least one text")
        if len(inputs) > settings.max_texts:
            raise ServiceError(422, "too_many_inputs",
                               f"at most {settings.max_texts} texts per request, got {len(inputs)}")
        for i, text in enumerate(inputs):
            if not text.strip():
                raise ServiceError(422, "blank_input", f"inputs[{i}] is empty or whitespace")

        backend_ = ready_backend()
        truncated = [len(t) > settings.max_chars for t in inputs]
        texts = [t[: settings.max_chars] for t in inputs]

        started = time.perf_counter()
        try:
            vectors = backend_.embed(texts)
        except Exception as exc:
            log.error("embed failed: texts=%d error=%s", len(texts), type(exc).__name__)
            raise ServiceError(502, "backend_error", f"{backend_.name} backend failed: {type(exc).__name__}") from exc

        if len(vectors) != len(texts) or any(len(v) != backend_.dimensions for v in vectors) \
                or any(not math.isfinite(x) for v in vectors for x in v):
            raise ServiceError(502, "backend_error", "backend returned malformed vectors")

        log.info("embed texts=%d chars=%d truncated=%d ms=%.0f", len(texts), sum(map(len, texts)),
                 sum(truncated), (time.perf_counter() - started) * 1000)  # counts only, never text
        return EmbedResponse(
            model=backend_.model_id,
            backend=backend_.name,
            dimensions=backend_.dimensions,
            normalized=backend_.normalized,
            embeddings=vectors,
            truncated=truncated,
            usage=Usage(texts=len(texts)),
        )

    return app


def app_factory() -> FastAPI:
    """uvicorn entrypoint: `uvicorn embedder_service.app:app_factory --factory`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
