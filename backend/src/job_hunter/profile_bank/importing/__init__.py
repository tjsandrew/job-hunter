"""Resume import extraction and review candidates; no HTTP/AWS dependencies."""
from .text import ExtractedText, SourceLine, ImportFailure, extract_text, from_text
from .parsers import document_to_json_resume, heuristic_to_json_resume
from .candidates import json_resume_to_candidates, match_candidates, additive_merge, evidence_for
from .models import ModelAdapter, FakeModel, OllamaModel, BedrockModel, llm_to_json_resume, parse_with_model
