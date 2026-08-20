"""Stable Ollama adapter facade and encoding exports."""

from .encoding import DEFAULT_KEEP_ALIVE, message_payload, tool_payload
from .facade import OllamaAdapter

__all__ = ["DEFAULT_KEEP_ALIVE", "OllamaAdapter", "message_payload", "tool_payload"]
