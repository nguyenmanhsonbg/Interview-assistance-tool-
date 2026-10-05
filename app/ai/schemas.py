from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.domain.errors import ValidationError


_SCHEMA_FILES = {
    "QUESTION_GENERATION": {"question-generation.v1": "question_generation.schema.json"},
    "ANSWER_EVALUATION": {
        "answer-evaluation.v1": "answer_evaluation.schema.json",
        "answer-evaluation.v2": "answer_evaluation.v2.schema.json",
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
        elif operation == "ANSWER_EVALUATION":
            _validate_evaluation_rules(payload)
        elif operation == "FOLLOW_UP":
            _validate_follow_up_rules(payload, context or {})
        return payload


def validate_question_generation(payload: Any) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "schemas"
    return SchemaRegistry(root).validate("QUESTION_GENERATION", payload)


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
    orders = [question["displayOrder"] for question in payload["questions"]]
    if orders != list(range(1, len(orders) + 1)):
        raise ValidationError("AI question displayOrder values must be contiguous from 1")


def _validate_evaluation_rules(payload: dict[str, Any]) -> None:
    for evaluation in payload["perAnswerEvaluations"]:
        not_assessed = evaluation["evidenceStatus"] == "NOT_ASSESSED"
        if not_assessed != (evaluation["score"] is None):
            raise ValidationError("NOT_ASSESSED answers must have a null score")


def _normalize_question(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _validate_follow_up_rules(payload: dict[str, Any], context: dict[str, Any]) -> None:
    asked = {_normalize_question(str(question)) for question in context.get("askedQuestions", [])}
    for question in payload["questions"]:
        if _normalize_question(question["text"]) in asked:
            raise ValidationError("Follow-up question repeats an already asked question")


def _fail(path: str, message: str) -> None:
    raise ValidationError(f"AI output {path} {message}")
