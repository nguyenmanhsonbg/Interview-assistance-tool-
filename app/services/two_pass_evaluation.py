from __future__ import annotations

from typing import Any, Callable

from app.ai.provider import AIProvider
from app.ai.prompts import RETRY_REPAIR_INSTRUCTION
from app.ai.schemas import SchemaRegistry


class TwoPassEvaluationPipeline:
    """Run snapshot evaluation as validated evidence and synthesis phases."""

    def __init__(self, schemas: SchemaRegistry, set_phase: Callable[[str, str], None]):
        self.schemas = schemas
        self.set_phase = set_phase

    def run(
        self,
        task: dict[str, Any],
        provider: AIProvider,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._context(payload)
        evidence_payload = dict(payload)
        evidence_payload["operation"] = "ANALYZE_ANSWER_EVIDENCE"
        if task.get("status") == "PENDING_RETRY":
            evidence_payload["repairInstruction"] = RETRY_REPAIR_INSTRUCTION

        self.set_phase(task["id"], "EVIDENCE_ANALYSIS")
        evidence = provider.analyze_answer_evidence(evidence_payload)
        self.schemas.validate("ANSWER_EVIDENCE", evidence, context=context)

        synthesis_payload = dict(payload)
        synthesis_payload["operation"] = "SYNTHESIZE_ANSWER_EVALUATION"
        synthesis_payload["evidenceAnalysis"] = evidence
        if task.get("status") == "PENDING_RETRY":
            synthesis_payload["repairInstruction"] = RETRY_REPAIR_INSTRUCTION

        self.set_phase(task["id"], "EVALUATION_SYNTHESIS")
        result = provider.synthesize_answer_evaluation(synthesis_payload)
        self.schemas.validate(
            "ANSWER_EVALUATION",
            result,
            context=context,
            schema_version="answer-evaluation.v2",
        )
        return result

    @staticmethod
    def _context(payload: dict[str, Any]) -> dict[str, set[str]]:
        return {
            "answerIds": {answer["answerId"] for answer in payload.get("answers", [])},
            "questionIds": {question["questionId"] for question in payload.get("questions", [])},
            "competencyKeys": {question["competencyKey"] for question in payload.get("questions", [])},
        }
