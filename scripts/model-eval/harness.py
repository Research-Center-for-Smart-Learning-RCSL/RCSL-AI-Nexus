"""Stable facade for model generation, extraction, scoring, and sampling."""

from harness_parts.client import HTTP_TIMEOUT, NUM_CTX, NUM_PREDICT, OLLAMA, chat, generate
from harness_parts.code_scoring import score_code_task
from harness_parts.dialogue import run_dialogue, score_dialogue_task
from harness_parts.extraction import exact_matches, extract_block, extract_final, normalise
from harness_parts.sample import sample, sample_dialogue
from harness_parts.scoring import score, score_exact_task

__all__ = [
    "HTTP_TIMEOUT", "NUM_CTX", "NUM_PREDICT", "OLLAMA", "chat", "exact_matches",
    "extract_block", "extract_final", "generate", "normalise", "run_dialogue", "sample",
    "sample_dialogue", "score", "score_code_task", "score_dialogue_task", "score_exact_task",
]
