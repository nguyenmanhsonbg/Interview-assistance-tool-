from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.domain.errors import ValidationError


_SCHEMA_FILES = {
    "QUESTION_GENERATION": {"question-generation.v1": "question_generation.schema.json"},
    "ANSWER_EVIDENCE": {"answer-evidence.v1": "answer_evidence.v1.schema.json"},
    "ANSWER_EVALUATION": {
        "answer-evaluation.v1": "answer_evaluation.schema.json",
        "answer-evaluation.v2": "answer_evaluation.v2.schema.json",
    },
    "QUESTION_VARIANT": {
        "question-variant.v1": "question-variant.v1.schema.json",
    },
    "QUESTION_ADDITION": {
        "question-addition.v1": "question-addition.v1.schema.json",
    },
    "FOLLOW_UP": {"follow-up.v1": "follow_up_question.schema.json"},
}


class SchemaRegistry:
    """Validate the JSON-Schema subset used by the three versioned AI contracts."""

    def __init__(self, root: Path) -> None:
        root = Path(root)
        self.schemas = {
            operation: {
                version: json.loads((root / filename).read_text(encoding="utf-8"))
                for version, filename in files.items()
            }
            for operation, files in _SCHEMA_FILES.items()
        }

    def validate(
        self,
        operation: str,
        payload: Any,
        *,
        context: dict[str, Any] | None = None,
        schema_version: str | None = None,
    ) -> dict[str, Any]:
        if operation not in self.schemas:
            raise ValidationError(f"Unknown AI output operation: {operation}")
        version = schema_version or (
            payload.get("schemaVersion") if isinstance(payload, dict) else None
        )
        schema = self.schemas[operation].get(version)
        if schema is None:
            raise ValidationError(f"Unsupported AI schema version: {version}")
        _validate_node(payload, schema, "$")
        if operation == "QUESTION_GENERATION":
            _validate_question_rules(payload)
        elif operation == "ANSWER_EVIDENCE":
            _validate_evidence_rules(payload, context or {})
        elif operation == "ANSWER_EVALUATION":
            _validate_evaluation_rules(payload, context or {})
        elif operation == "QUESTION_VARIANT":
            _validate_question_variant_rules(payload, context or {})
        elif operation == "QUESTION_ADDITION":
            _validate_question_addition_rules(payload, context or {})
        elif operation == "FOLLOW_UP":
            _validate_follow_up_rules(payload, context or {})
        return payload


def validate_question_generation(payload: Any) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "schemas"
    return SchemaRegistry(root).validate("QUESTION_GENERATION", payload)


def validate_question_variant(
    payload: Any,
    *,
    question_set_id: str | None = None,
    source_question_id: str | None = None,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "schemas"
    return SchemaRegistry(root).validate(
        "QUESTION_VARIANT",
        payload,
        context={
            "questionSetId": question_set_id,
            "sourceQuestionId": source_question_id,
        },
    )


def validate_question_addition(
    payload: Any,
    *,
    question_set_id: str | None = None,
    target_category: str | None = None,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "schemas"
    return SchemaRegistry(root).validate(
        "QUESTION_ADDITION",
        payload,
        context={
            "questionSetId": question_set_id,
            "targetCategory": target_category,
        },
    )


def _validate_node(value: Any, schema: dict[str, Any], path: str) -> None:
    if "const" in schema and value != schema["const"]:
        _fail(path, f"must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        _fail(path, "contains an unsupported value")
    allowed_types = schema.get("type")
    if allowed_types is not None:
        if isinstance(allowed_types, str):
            allowed_types = [allowed_types]
        if not any(_is_type(value, expected) for expected in allowed_types):
            _fail(path, f"must be {' or '.join(allowed_types)}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            _fail(path, f"is missing required field {missing[0]}")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                _fail(path, f"contains unsupported field {sorted(extras)[0]}")
        for name, child in value.items():
            if name in properties:
                _validate_node(child, properties[name], f"{path}.{name}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            _fail(path, "contains too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            _fail(path, "contains too many items")
        if schema.get("items"):
            for index, item in enumerate(value):
                _validate_node(item, schema["items"], f"{path}[{index}]")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            _fail(path, "is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            _fail(path, "is too long")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            _fail(path, "is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            _fail(path, "is above the maximum")


def _is_type(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "boolean": lambda: isinstance(value, bool),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": lambda: value is None,
    }
    return checks.get(expected, lambda: False)()


def _validate_question_rules(payload: dict[str, Any]) -> None:
    questions = payload["questions"]
    if len(questions) != 9:
        raise ValidationError("AI Question Set must contain exactly 9 questions")
    orders = [question["displayOrder"] for question in questions]
    if orders != list(range(1, 10)):
        raise ValidationError("AI question displayOrder values must be contiguous from 1 to 9")
    counts = {
        category: sum(question["questionCategory"] == category for question in questions)
        for category in ("FOUNDATION", "APPLICATION", "DEEP_DIVE")
    }
    if counts != {"FOUNDATION": 3, "APPLICATION": 4, "DEEP_DIVE": 2}:
        raise ValidationError(
            "AI Question Set must use the FOUNDATION/APPLICATION/DEEP_DIVE distribution 3/4/2"
        )
    expected_sources = {
        "FOUNDATION": {"STANDARDIZED"},
        "APPLICATION": {"SITUATIONAL"},
        "DEEP_DIVE": {"CV_VERIFICATION", "GAP_CONFLICT"},
    }
    for question in questions:
        if question["sourceKind"] not in expected_sources[question["questionCategory"]]:
            raise ValidationError("AI question sourceKind does not match questionCategory")
    deep_dive_sources = [
        question["sourceKind"]
        for question in questions
        if question["questionCategory"] == "DEEP_DIVE"
    ]
    if sorted(deep_dive_sources) != ["CV_VERIFICATION", "GAP_CONFLICT"]:
        raise ValidationError(
            "AI DEEP_DIVE questions must contain one CV_VERIFICATION and one GAP_CONFLICT question"
        )


def _validate_evidence_rules(payload: dict[str, Any], context: dict[str, Any]) -> None:
    answer_ids = context.get("answerIds")
    question_ids = context.get("questionIds")
    competency_keys = context.get("competencyKeys")
    seen_answers: set[str] = set()
    seen_questions: set[str] = set()
    for evidence in payload["perAnswerEvidence"]:
        answer_id = evidence["answerId"]
        question_id = evidence["questionId"]
        if answer_id in seen_answers or question_id in seen_questions:
            raise ValidationError("AI evidence output contains duplicate answer or question references")
        seen_answers.add(answer_id)
        seen_questions.add(question_id)
        if answer_ids is not None and answer_id not in answer_ids:
            raise ValidationError("AI evidence output references an unknown answer")
        if question_ids is not None and question_id not in question_ids:
            raise ValidationError("AI evidence output references an unknown question")
        not_assessed = evidence["evidenceStatus"] == "NOT_ASSESSED"
        if not_assessed != (evidence["score"] is None):
            raise ValidationError("NOT_ASSESSED evidence must have a null score")
    if answer_ids is not None and seen_answers != set(answer_ids):
        raise ValidationError("AI evidence output must contain exactly one record for every answer")
    if question_ids is not None and seen_questions != set(question_ids):
        raise ValidationError("AI evidence output must contain exactly one record for every question")
    seen_competencies: set[str] = set()
    for evidence in payload["competencyEvidence"]:
        competency_key = evidence["competencyKey"]
        if competency_key in seen_competencies:
            raise ValidationError("AI evidence output contains duplicate competency references")
        seen_competencies.add(competency_key)
        if competency_keys is not None and competency_key not in competency_keys:
            raise ValidationError("AI evidence output references an unknown competency")


def _validate_evaluation_rules(payload: dict[str, Any], context: dict[str, Any]) -> None:
    answer_ids = context.get("answerIds")
    question_ids = context.get("questionIds")
    seen_answers: set[str] = set()
    seen_questions: set[str] = set()
    for evaluation in payload["perAnswerEvaluations"]:
        answer_id = evaluation["answerId"]
        question_id = evaluation["questionId"]
        if answer_id in seen_answers or question_id in seen_questions:
            raise ValidationError("AI evaluation output contains duplicate answer or question references")
        seen_answers.add(answer_id)
        seen_questions.add(question_id)
        if answer_ids is not None and answer_id not in answer_ids:
            raise ValidationError("AI evaluation output references an unknown answer")
        if question_ids is not None and question_id not in question_ids:
            raise ValidationError("AI evaluation output references an unknown question")
        not_assessed = evaluation["evidenceStatus"] == "NOT_ASSESSED"
        if not_assessed != (evaluation["score"] is None):
            raise ValidationError("NOT_ASSESSED answers must have a null score")
    if answer_ids is not None and seen_answers != set(answer_ids):
        raise ValidationError("AI evaluation output must contain exactly one record for every answer")
    if question_ids is not None and seen_questions != set(question_ids):
        raise ValidationError("AI evaluation output must contain exactly one record for every question")


def _validate_question_variant_rules(
    payload: dict[str, Any], context: dict[str, Any]
) -> None:
    expected_question_set_id = context.get("questionSetId")
    expected_source_question_id = context.get("sourceQuestionId")
    if (
        expected_question_set_id is not None
        and payload["questionSetId"] != expected_question_set_id
    ):
        raise ValidationError("AI question variant references an unknown question set")
    if (
        expected_source_question_id is not None
        and payload["sourceQuestionId"] != expected_source_question_id
    ):
        raise ValidationError("AI question variant references an unknown source question")


def _validate_question_addition_rules(
    payload: dict[str, Any], context: dict[str, Any]
) -> None:
    expected_question_set_id = context.get("questionSetId")
    expected_category = context.get("targetCategory")
    if (
        expected_question_set_id is not None
        and payload["questionSetId"] != expected_question_set_id
    ):
        raise ValidationError("AI question addition references an unknown question set")
    if expected_category is not None and payload["targetCategory"] != expected_category:
        raise ValidationError("AI question addition category does not match the target group")
    allowed_sources = {
        "FOUNDATION": {"STANDARDIZED"},
        "APPLICATION": {"SITUATIONAL"},
        "DEEP_DIVE": {"CV_VERIFICATION", "GAP_CONFLICT"},
    }
    if payload["question"]["sourceKind"] not in allowed_sources[payload["targetCategory"]]:
        raise ValidationError("AI question addition sourceKind does not match targetCategory")


def _normalize_question(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _validate_follow_up_rules(payload: dict[str, Any], context: dict[str, Any]) -> None:
    asked = {_normalize_question(str(question)) for question in context.get("askedQuestions", [])}
    for question in payload["questions"]:
        if _normalize_question(question["text"]) in asked:
            raise ValidationError("Follow-up question repeats an already asked question")


def _fail(path: str, message: str) -> None:
    raise ValidationError(f"AI output {path} {message}")
