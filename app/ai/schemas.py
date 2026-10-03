from __future__ import annotations

from typing import Any

from app.domain.errors import ValidationError


QUESTION_REQUIRED_FIELDS = {
    "provisionalId", "displayOrder", "text", "competencyKey", "sourceKind",
    "purpose", "questionType", "difficulty", "expectedEvidence", "rubric",
    "isRequired", "estimatedSeconds",
}


def validate_question_generation(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("AI output must be an object")
    if payload.get("schemaVersion") != "question-generation.v1":
        raise ValidationError("Unsupported question generation schema version")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not 5 <= len(questions) <= 8:
        raise ValidationError("Question generation output must contain 5 to 8 questions")
    duration = payload.get("estimatedDurationSeconds")
    if not isinstance(duration, int) or isinstance(duration, bool) or not 600 <= duration <= 900:
        raise ValidationError("Estimated duration must be between 600 and 900 seconds")
    orders: set[int] = set()
    for question in questions:
        if not isinstance(question, dict) or not QUESTION_REQUIRED_FIELDS.issubset(question):
            raise ValidationError("AI question is missing required fields")
        order = question["displayOrder"]
        if not isinstance(order, int) or order in orders or not 1 <= order <= 8:
            raise ValidationError("Question display order is invalid")
        orders.add(order)
        rubric = question["rubric"]
        if not isinstance(rubric, dict) or any(
            not isinstance(rubric.get(f"score{score}"), str)
            or not rubric[f"score{score}"].strip()
            for score in range(5)
        ):
            raise ValidationError("Question rubric must define score0 through score4")
        for field in ("text", "competencyKey", "purpose", "expectedEvidence"):
            if not isinstance(question[field], str) or not question[field].strip():
                raise ValidationError(f"Question {field} is required")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValidationError("AI confidence must be between 0 and 1")
    return payload
