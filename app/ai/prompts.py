from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.errors import ValidationError


_PROMPTS = {
    "question_generation": ("question_generation_prompt.md", "question-generation.v1"),
    "answer_evaluation": ("answer_evaluation_prompt.md", "answer-evaluation.v1"),
    "answer_evaluation_v2": ("answer_evaluation_prompt_v2.md", "answer-evaluation.v2"),
    "follow_up_question": ("follow_up_question_prompt.md", "follow-up.v1"),
}


class PromptCatalog:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def version(self, key: str) -> str:
        try:
            return _PROMPTS[key][1]
        except KeyError as error:
            raise ValidationError(f"Unknown prompt key: {key}") from error

    def render(self, key: str, payload: dict[str, Any]) -> str:
        try:
            filename, _ = _PROMPTS[key]
        except KeyError as error:
            raise ValidationError(f"Unknown prompt key: {key}") from error
        template = (self.root / filename).read_text(encoding="utf-8")
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"{template.rstrip()}\n\nBEGIN_UNTRUSTED_INPUT\n{serialized}\nEND_UNTRUSTED_INPUT\n"
