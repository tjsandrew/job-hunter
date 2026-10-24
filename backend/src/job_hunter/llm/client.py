"""Language-model clients behind one tiny interface.

``complete_json`` asks for a single JSON object and returns it parsed. It never relies on a model's tool-use or
"JSON mode", because small models may lack them: the reply is parsed and checked here instead.

* ``FakeLlm``       tests: canned answers, records every call.
* ``OllamaClient``  local development against a host Ollama (same model family as the Lambda).
* ``HostedClient``  a hosted model with an OpenAI-style API (the school's SoCLaaS gateway, Groq, Gemini, OpenRouter); needs internet.
* ``LlamaCppClient`` the LLM Lambda: a GGUF model baked into the image, run in-process on the CPU (no network).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_sleep = time.sleep   # replaced in tests


class LlmError(Exception):
    """The model is unavailable or returned something that is not the requested JSON."""


class LlmClient(Protocol):
    name: str

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict[str, Any]: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object in ``text``; tolerates code fences and chatter around it."""
    if not isinstance(text, str) or not text.strip():
        raise LlmError("The model returned an empty reply")
    body = _FENCE.sub("", text.strip())
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise LlmError("The model reply has no JSON object")
    try:
        value = json.loads(body[start:end + 1])
    except ValueError as exc:
        raise LlmError("The model reply is not valid JSON") from exc
    if not isinstance(value, dict):
        raise LlmError("The model reply is not a JSON object")
    return value


def complete_validated(client: LlmClient, system: str, user: str, validate: Callable[[dict], Any], *,
                       max_tokens: int = 1024) -> Any:
    """Ask, validate, and retry once with a short repair note. Raises ``LlmError`` if both attempts fail."""
    last: Exception | None = None
    prompt = user
    for _ in range(2):
        try:
            return validate(client.complete_json(system, prompt, max_tokens=max_tokens))
        except (LlmError, ValueError, KeyError, TypeError) as exc:
            last = exc
            prompt = (user + "\n\nYour previous reply was rejected (" + str(exc)[:200] +
                      "). Reply again with only the JSON object in the requested shape.")
    raise LlmError("The model did not return a usable answer: " + str(last)[:200])


class FakeLlm:
    """Returns canned answers: a list (used in order, the last one repeats) or ``fn(system, user) -> dict``."""
    name = "fake"

    def __init__(self, answers: list[dict] | Callable[[str, str], dict]):
        self._answers = answers
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict[str, Any]:
        self.calls.append((system, user))
        if callable(self._answers):
            return self._answers(system, user)
        index = min(len(self.calls) - 1, len(self._answers) - 1)
        return self._answers[index]


class OllamaClient:
    name = "ollama"

    def __init__(self, url: str, model: str, timeout: int = 600):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout
        self.last_usage: dict[str, int | None] = {}   # token counts of the latest call, for cost and speed measurements

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict[str, Any]:
        body = {"model": self.model, "stream": False, "format": "json",
                "options": {"temperature": 0, "num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        request = Request(self.url + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024:
                raise LlmError("The model reply is too large")
            data = json.loads(payload)
            self.last_usage = {"prompt_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")}
            return parse_json_object(data["message"]["content"])
        except (URLError, TimeoutError, KeyError, TypeError) as exc:
            raise LlmError("The AI model is not available") from exc
        except ValueError as exc:
            raise LlmError("The model reply could not be read") from exc


class HostedClient:
    """Any provider with an OpenAI-style ``/chat/completions`` endpoint (the school's SoCLaaS gateway, Groq, Gemini, ...).

    The key comes from the environment and is never logged. The call must come from somewhere that can reach the
    provider. Rate limits (429) and temporary server errors (5xx) are retried with a short backoff.
    """
    name = "hosted"
    ATTEMPTS = 3
    RETRY_STATUS = (429, 500, 502, 503, 504)

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 120, reasoning_effort: str = ""):
        if not (base_url and api_key and model):
            raise LlmError("A hosted model needs LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout
        self.name = f"hosted:{model}"     # recorded with every stored analysis
        self.reasoning_effort = reasoning_effort    # e.g. "none" stops reasoning models from spending tokens on thinking
        self.last_usage: dict[str, int | None] = {}

    def _body(self, system: str, user: str, max_tokens: int, json_mode: bool) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key})
        with urlopen(request, timeout=self.timeout) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise LlmError("The model reply is too large")
        return json.loads(payload)

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict[str, Any]:
        json_mode, last_error = True, "The hosted model is not available"
        for attempt in range(self.ATTEMPTS):
            delay = None
            try:
                data = self._post(self._body(system, user, max_tokens, json_mode))
                usage = data.get("usage") or {}
                self.last_usage = {"prompt_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}
                return parse_json_object(data["choices"][0]["message"]["content"])
            except HTTPError as exc:
                if exc.code == 400 and json_mode:
                    json_mode = False        # some backends reject response_format; the reply is parsed here anyway
                    continue
                if exc.code not in self.RETRY_STATUS:
                    raise LlmError(f"The hosted model refused the request (HTTP {exc.code})") from exc
                last_error = ("The hosted model is rate-limited, try again shortly" if exc.code == 429
                              else f"The hosted model had a temporary problem (HTTP {exc.code})")
                delay = _retry_after(exc)
            except (URLError, TimeoutError):
                last_error = "The hosted model is not available"
            except (KeyError, IndexError, TypeError) as exc:
                raise LlmError("The hosted model returned an unexpected reply") from exc
            except ValueError as exc:
                raise LlmError("The model reply could not be read") from exc
            if attempt < self.ATTEMPTS - 1:
                _sleep(delay if delay is not None else 2 ** attempt)
        raise LlmError(last_error)


def _retry_after(error: HTTPError) -> float | None:
    try:
        return min(float(error.headers.get("Retry-After")), 30.0)
    except (AttributeError, TypeError, ValueError):
        return None


class LlamaCppClient:
    """The model file is loaded once per Lambda container and reused by warm invocations."""
    name = "llamacpp"
    _model: Any = None

    def __init__(self, model_path: str, *, threads: int | None = None, context: int = 8192):
        self.model_path, self.threads, self.context = model_path, threads, context

    def _load(self) -> Any:
        if LlamaCppClient._model is None:
            try:
                from llama_cpp import Llama  # optional dependency, installed only in the LLM Lambda image
            except ImportError as exc:
                raise LlmError("llama-cpp-python is not installed") from exc
            try:
                LlamaCppClient._model = Llama(model_path=self.model_path, n_ctx=self.context, n_threads=self.threads,
                                              verbose=False)
            except (OSError, ValueError) as exc:
                raise LlmError("The model file could not be loaded") from exc
        return LlamaCppClient._model

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> dict[str, Any]:
        result = self._load().create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0, max_tokens=max_tokens, response_format={"type": "json_object"})
        try:
            return parse_json_object(result["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("The model reply could not be read") from exc


def build_client(settings: Any) -> LlmClient | None:
    """The client for ``settings.model_backend``, or ``None`` when no language model is configured."""
    backend = settings.model_backend
    if backend == "ollama":
        return OllamaClient(settings.ollama_url, settings.ollama_model, settings.llm_timeout_seconds)
    if backend == "llamacpp":
        return LlamaCppClient(settings.llm_model_path)
    if backend == "hosted":
        return HostedClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout_seconds,
                            settings.llm_reasoning_effort)
    return None
