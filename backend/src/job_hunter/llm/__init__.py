"""A small language-model client shared by every feature that needs one (fit analysis, AI resume rewrite).

The jobs themselves are in ``job_hunter.llm.tasks``; the S3 hand-off to the worker Lambda is ``job_hunter.llm_transport``.
"""
from job_hunter.llm.client import (FakeLlm, HostedClient, LlmClient, LlmError, OllamaClient, build_client,
                                   complete_validated, parse_json_object)

__all__ = ["FakeLlm", "HostedClient", "LlmClient", "LlmError", "OllamaClient", "build_client",
           "complete_validated", "parse_json_object"]
