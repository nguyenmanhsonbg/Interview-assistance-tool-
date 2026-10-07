from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.errors import ValidationError


RETRY_REPAIR_INSTRUCTION = (
    "Return one corrected JSON object that strictly matches the requested schema."
)


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
        repair_instruction = payload.get("repairInstruction")
        input_payload = payload
        if repair_instruction == RETRY_REPAIR_INSTRUCTION:
            input_payload = dict(payload)
            input_payload.pop("repairInstruction")
        serialized = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
        rendered = template.rstrip()
        if repair_instruction == RETRY_REPAIR_INSTRUCTION:
            rendered += (
                "\n\nRETRY_REPAIR_INSTRUCTION\n"
                f"{RETRY_REPAIR_INSTRUCTION}\n"
                "END_RETRY_REPAIR_INSTRUCTION"
            )
        return f"{rendered}\n\nBEGIN_UNTRUSTED_INPUT\n{serialized}\nEND_UNTRUSTED_INPUT\n"
