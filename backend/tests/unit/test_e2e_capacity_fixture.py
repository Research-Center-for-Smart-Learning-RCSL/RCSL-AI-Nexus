"""The full-stack harness reaches C4 without bypassing production admission."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from app.domain.entities.chat import Message, MessageRole


async def test_seeded_fake_models_have_declared_capacity_and_estimate_counting(tmp_path: Path):
    seeder_path = Path(__file__).resolve().parents[3] / "scripts" / "e2e_seed_stack.py"
    spec = spec_from_file_location("e2e_capacity_seeder", seeder_path)
    assert spec is not None and spec.loader is not None
    seeder = module_from_spec(spec)
    spec.loader.exec_module(seeder)
    seeder.seed_model_capacity(tmp_path)
    counter = GgufTokenCounter(tmp_path)
    for _, _, ref in seeder.MODELS:
        assert await counter.native_context_length(ref) == 32768
        assert await counter.count_prompt(ref, [Message(MessageRole.USER, "question")], []) is None
