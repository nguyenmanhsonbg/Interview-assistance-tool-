from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree

from app.domain.errors import ValidationError


WORKBOOK_FORMAT_VERSION = "question-answer.v1"
METADATA_FIELDS = (
    "format_version",
    "case_id",
    "question_set_id",
    "question_set_version",
    "duration_seconds",
    "exported_at",
)
QUESTION_HEADERS = (
    "question_id",
    "display_order",
    "question_text",
    "competency_key",
    "source_kind",
    "purpose",
    "question_type",
    "difficulty",
    "expected_evidence",
    "rubric_score_0",
    "rubric_score_1",
    "rubric_score_2",
    "rubric_score_3",
    "rubric_score_4",
    "is_required",
    "estimated_seconds",
    "answer_text",
    "is_answered",
)

MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 16
MAX_TOTAL_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_CELL_CHARS = 10_000
MAX_METADATA_CHARS = 500

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_NS = "http://www.w3.org/XML/1998/namespace"
WORKSHEET_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"

_QUESTION_FIELDS = (
    ("questionId", "question_id"),
    ("displayOrder", "display_order"),
    ("questionText", "question_text"),
    ("competencyKey", "competency_key"),
    ("sourceKind", "source_kind"),
    ("purpose", "purpose"),
    ("questionType", "question_type"),
    ("difficulty", "difficulty"),
    ("expectedEvidence", "expected_evidence"),
    ("rubric_score_0", "rubric_score_0"),
    ("rubric_score_1", "rubric_score_1"),
    ("rubric_score_2", "rubric_score_2"),
    ("rubric_score_3", "rubric_score_3"),
    ("rubric_score_4", "rubric_score_4"),
    ("isRequired", "is_required"),
    ("estimatedSeconds", "estimated_seconds"),
    ("answerText", "answer_text"),
    ("isAnswered", "is_answered"),
)
_SOURCE_KINDS = {
    "STANDARDIZED", "SITUATIONAL", "CV_VERIFICATION", "GAP_CONFLICT",
    "QUESTION_BANK", "MANUAL", "AI",
}
_QUESTION_TYPES = {"SHORT_TEXT", "LONG_TEXT", "SCENARIO"}
_DIFFICULTIES = {"EASY", "MEDIUM", "HARD"}
_METADATA_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


@dataclass(frozen=True)
class QuestionAnswerWorkbook:
    metadata: dict[str, str]
    questions: list[dict[str, Any]]
    question_headers: tuple[str, ...] = QUESTION_HEADERS


def export_question_answer_workbook(
    metadata: Mapping[str, str], questions: Sequence[Mapping[str, Any]]
) -> bytes:
    normalized_metadata = _validate_metadata(metadata)
    normalized_questions = [_normalize_question(question) for question in questions]
    _validate_questions(normalized_questions)

    metadata_rows = [(field, normalized_metadata[field]) for field in METADATA_FIELDS]
    question_rows = [list(QUESTION_HEADERS)] + [
        list(_excel_fields(question)) for question in normalized_questions
    ]
    metadata_sheet = _worksheet_xml([list(("field", "value")), *metadata_rows])
    question_sheet = _worksheet_xml(question_rows)
    files = {
        "[Content_Types].xml": _content_types_xml(),
        "_rels/.rels": _root_relationships_xml(),
        "xl/workbook.xml": _workbook_xml(),
        "xl/_rels/workbook.xml.rels": _workbook_relationships_xml(),
        "xl/worksheets/sheet1.xml": metadata_sheet,
        "xl/worksheets/sheet2.xml": question_sheet,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    raw = output.getvalue()
    if len(raw) > MAX_WORKBOOK_BYTES:
        raise ValidationError("Workbook exceeds the size limit")
    return raw


def import_question_answer_workbook(raw: bytes) -> QuestionAnswerWorkbook:
    if not isinstance(raw, bytes) or not raw:
        raise ValidationError("Workbook is required")
    if len(raw) > MAX_WORKBOOK_BYTES:
        raise ValidationError("Workbook exceeds the size limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as error:
        raise ValidationError("Workbook must be a valid .xlsx package") from error
    with archive:
        _validate_archive(archive)
        files = {name: archive.read(name) for name in archive.namelist()}
    workbook = _parse_xml(files["xl/workbook.xml"], "workbook")
    relationships = _parse_xml(files["xl/_rels/workbook.xml.rels"], "workbook relationships")
    targets = _sheet_targets(workbook, relationships)
    metadata_name = targets.get("metadata")
    questions_name = targets.get("questions")
    if metadata_name is None or questions_name is None or len(targets) != 2:
        raise ValidationError("Workbook must contain metadata and questions sheets only")
    metadata = _parse_metadata(_parse_rows(files[metadata_name], "metadata"))
    questions, headers = _parse_questions(_parse_rows(files[questions_name], "questions"))
    return QuestionAnswerWorkbook(metadata=metadata, questions=questions, question_headers=headers)


def _validate_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    if set(metadata) != set(METADATA_FIELDS):
        raise ValidationError("Workbook metadata fields are invalid")
    normalized: dict[str, str] = {}
    for field in METADATA_FIELDS:
        value = metadata[field]
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_METADATA_CHARS:
            raise ValidationError(f"Workbook metadata {field} is invalid")
        if not _METADATA_RE.fullmatch(value) and field != "exported_at":
            raise ValidationError(f"Workbook metadata {field} is invalid")
        normalized[field] = value.strip()
    if normalized["format_version"] != WORKBOOK_FORMAT_VERSION:
        raise ValidationError("Unsupported workbook format version")
    try:
        duration = int(normalized["duration_seconds"])
    except ValueError as error:
        raise ValidationError("Workbook duration_seconds is invalid") from error
    if not 600 <= duration <= 900:
        raise ValidationError("Workbook duration_seconds is invalid")
    return normalized


def _normalize_question(question: Mapping[str, Any]) -> dict[str, Any]:
    try:
        normalized = {
            "questionId": question["questionId"],
            "displayOrder": question["displayOrder"],
            "questionText": question["questionText"],
            "competencyKey": question["competencyKey"],
            "sourceKind": question["sourceKind"],
            "purpose": question["purpose"],
            "questionType": question["questionType"],
            "difficulty": question["difficulty"],
            "expectedEvidence": question["expectedEvidence"],
            "rubric": dict(question["rubric"]),
            "isRequired": question["isRequired"],
            "estimatedSeconds": question["estimatedSeconds"],
            "answerText": question.get("answerText", ""),
            "isAnswered": question.get("isAnswered", False),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError("Question row is invalid") from error
    _validate_question(normalized)
    return normalized


def _validate_questions(questions: Sequence[Mapping[str, Any]]) -> None:
    if not 5 <= len(questions) <= 8:
        raise ValidationError("Workbook must contain 5 to 8 questions")
    normalized = [_normalize_question(question) for question in questions]
    ids = [item["questionId"] for item in normalized]
    orders = [item["displayOrder"] for item in normalized]
    if len(ids) != len(set(ids)) or len(orders) != len(set(orders)):
        raise ValidationError("Workbook question IDs and display orders must be unique")
    if orders != list(range(1, len(orders) + 1)):
        raise ValidationError("Workbook display orders must be contiguous from 1")


def _validate_question(question: Mapping[str, Any]) -> None:
    for field in (
        "questionId", "questionText", "competencyKey", "sourceKind", "purpose",
        "questionType", "difficulty", "expectedEvidence",
    ):
        value = question[field]
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_CELL_CHARS:
            raise ValidationError(f"Workbook question {field} is invalid")
    if question["sourceKind"] not in _SOURCE_KINDS:
        raise ValidationError("Workbook source_kind is invalid")
    if question["questionType"] not in _QUESTION_TYPES:
        raise ValidationError("Workbook question_type is invalid")
    if question["difficulty"] not in _DIFFICULTIES:
        raise ValidationError("Workbook difficulty is invalid")
    if isinstance(question["displayOrder"], bool) or not isinstance(question["displayOrder"], int):
        raise ValidationError("Workbook display_order is invalid")
    if not 1 <= question["displayOrder"] <= 8:
        raise ValidationError("Workbook display_order is invalid")
    if not isinstance(question["isRequired"], bool):
        raise ValidationError("Workbook is_required is invalid")
    if (
        isinstance(question["estimatedSeconds"], bool)
        or not isinstance(question["estimatedSeconds"], int)
        or not 1 <= question["estimatedSeconds"] <= 900
    ):
        raise ValidationError("Workbook estimated_seconds is invalid")
    answer = question["answerText"]
    if not isinstance(answer, str) or len(answer) > MAX_CELL_CHARS:
        raise ValidationError("Workbook answer_text is invalid")
    if not isinstance(question["isAnswered"], bool):
        raise ValidationError("Workbook is_answered is invalid")
    if question["isAnswered"] != bool(answer.strip()):
        raise ValidationError("Workbook answer_text and is_answered do not match")
    rubric = question["rubric"]
    if set(rubric) != {f"score{score}" for score in range(5)}:
        raise ValidationError("Workbook rubric fields are invalid")
    for value in rubric.values():
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_CELL_CHARS:
            raise ValidationError("Workbook rubric fields are invalid")


def _excel_fields(question: Mapping[str, Any]) -> tuple[Any, ...]:
    values: list[Any] = []
    for field, _ in _QUESTION_FIELDS:
        if field.startswith("rubric_score_"):
            values.append(question["rubric"][f"score{field.rsplit('_', 1)[1]}"])
        else:
            values.append(question[field])
    return tuple(values)


def _validate_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ValidationError("Workbook contains too many archive entries")
    total = 0
    allowed = {
        "[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml",
        "xl/worksheets/sheet2.xml",
    }
    for info in infos:
        name = info.filename
        if name not in allowed or name.startswith("/") or ".." in name.split("/"):
            raise ValidationError("Workbook contains unsupported archive entries")
        if info.file_size > MAX_XML_BYTES or info.file_size > max(1, info.compress_size) * 100:
            raise ValidationError("Workbook archive entry is unsafe")
        total += info.file_size
    if total > MAX_TOTAL_UNCOMPRESSED_BYTES or set(archive.namelist()) != allowed:
        raise ValidationError("Workbook package is incomplete or too large")
    for name in allowed:
        raw = archive.read(name)
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw or re.search(rb"<\s*f(?:\s|>)", raw):
            raise ValidationError("Workbook contains unsupported XML content")


def _parse_xml(raw: bytes, label: str) -> ElementTree.Element:
    if len(raw) > MAX_XML_BYTES:
        raise ValidationError(f"Workbook {label} XML is too large")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise ValidationError(f"Workbook {label} XML is invalid") from error


def _sheet_targets(workbook: ElementTree.Element, relationships: ElementTree.Element) -> dict[str, str]:
    rels = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relationships
        if relation.tag.endswith("}Relationship")
        and relation.attrib.get("Type") == WORKSHEET_REL_TYPE
    }
    targets: dict[str, str] = {}
    for sheet in workbook.iter():
        if not sheet.tag.endswith("}sheet"):
            continue
        name = sheet.attrib.get("name", "")
        relationship_id = sheet.attrib.get(f"{{{REL_NS}}}id")
        target = rels.get(relationship_id or "")
        if not name or target is None or target.startswith("/") or ".." in target.split("/"):
            raise ValidationError("Workbook sheet relationships are invalid")
        normalized = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        targets[name] = normalized
    if len(targets) != 2 or set(targets) != {"metadata", "questions"}:
        raise ValidationError("Workbook must contain metadata and questions sheets only")
    return targets


def _parse_rows(raw: bytes, label: str) -> list[list[str]]:
    root = _parse_xml(raw, label)
    rows: list[list[str]] = []
    for row in root.iter():
        if not row.tag.endswith("}row"):
            continue
        cells = []
        for cell in row:
            if not cell.tag.endswith("}c"):
                continue
            cells.append(_cell_value(cell, label))
        rows.append(cells)
    if not rows:
        raise ValidationError(f"Workbook {label} sheet is empty")
    return rows


def _cell_value(cell: ElementTree.Element, label: str) -> str:
    if any(child.tag.endswith("}f") for child in cell.iter()):
        raise ValidationError(f"Workbook {label} contains a formula")
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        value = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
    elif cell_type == "b":
        value = cell.findtext(f"{{{MAIN_NS}}}v", default="")
        if value not in {"0", "1"}:
            raise ValidationError(f"Workbook {label} boolean cell is invalid")
    elif cell_type in {None, "n"}:
        value = cell.findtext(f"{{{MAIN_NS}}}v", default="")
    else:
        raise ValidationError(f"Workbook {label} cell type is unsupported")
    if len(value) > MAX_CELL_CHARS:
        raise ValidationError(f"Workbook {label} cell is too long")
    return value


def _parse_metadata(rows: list[list[str]]) -> dict[str, str]:
    if rows[0] != ["field", "value"]:
        raise ValidationError("Workbook metadata header is invalid")
    values: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) != 2 or row[0] in values:
            raise ValidationError("Workbook metadata rows are invalid")
        values[row[0]] = row[1]
    return _validate_metadata(values)


def _parse_questions(rows: list[list[str]]) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    if tuple(rows[0]) != QUESTION_HEADERS:
        raise ValidationError("Workbook questions header is invalid")
    parsed: list[dict[str, Any]] = []
    for row in rows[1:]:
        if len(row) != len(QUESTION_HEADERS):
            raise ValidationError("Workbook question row width is invalid")
        values = dict(zip(QUESTION_HEADERS, row))
        try:
            question = {
                "questionId": values["question_id"],
                "displayOrder": int(values["display_order"]),
                "questionText": values["question_text"],
                "competencyKey": values["competency_key"],
                "sourceKind": values["source_kind"],
                "purpose": values["purpose"],
                "questionType": values["question_type"],
                "difficulty": values["difficulty"],
                "expectedEvidence": values["expected_evidence"],
                "rubric": {f"score{score}": values[f"rubric_score_{score}"] for score in range(5)},
                "isRequired": _parse_bool(values["is_required"]),
                "estimatedSeconds": int(values["estimated_seconds"]),
                "answerText": values["answer_text"],
                "isAnswered": _parse_bool(values["is_answered"]),
            }
        except (TypeError, ValueError) as error:
            raise ValidationError("Workbook question numeric or boolean field is invalid") from error
        parsed.append(_normalize_question(question))
    _validate_questions(parsed)
    return parsed, QUESTION_HEADERS


def _parse_bool(value: str) -> bool:
    if value not in {"0", "1", "TRUE", "FALSE", "true", "false"}:
        raise ValueError("invalid boolean")
    return value in {"1", "TRUE", "true"}


def _worksheet_xml(rows: Sequence[Sequence[Any]]) -> bytes:
    root = ElementTree.Element(f"{{{MAIN_NS}}}worksheet")
    sheet_data = ElementTree.SubElement(root, f"{{{MAIN_NS}}}sheetData")
    for row_number, values in enumerate(rows, start=1):
        row = ElementTree.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": str(row_number)})
        for column_number, value in enumerate(values, start=1):
            cell_ref = f"{_column_name(column_number)}{row_number}"
            cell = ElementTree.SubElement(row, f"{{{MAIN_NS}}}c", {"r": cell_ref})
            if isinstance(value, bool):
                cell.set("t", "b")
                ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v").text = "1" if value else "0"
            elif isinstance(value, int):
                cell.set("t", "n")
                ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v").text = str(value)
            else:
                cell.set("t", "inlineStr")
                inline = ElementTree.SubElement(cell, f"{{{MAIN_NS}}}is")
                text = ElementTree.SubElement(inline, f"{{{MAIN_NS}}}t")
                text.set(f"{{{XML_NS}}}space", "preserve")
                text.text = str(value)
    return _xml_bytes(root)


def _workbook_xml() -> bytes:
    root = ElementTree.Element(f"{{{MAIN_NS}}}workbook", {f"{{{REL_NS}}}dummy": ""})
    root.attrib.pop(f"{{{REL_NS}}}dummy")
    sheets = ElementTree.SubElement(root, f"{{{MAIN_NS}}}sheets")
    for number, name in enumerate(("metadata", "questions"), start=1):
        ElementTree.SubElement(
            sheets,
            f"{{{MAIN_NS}}}sheet",
            {"name": name, "sheetId": str(number), f"{{{REL_NS}}}id": f"rId{number}"},
        )
    return _xml_bytes(root)


def _content_types_xml() -> bytes:
    root = ElementTree.Element(f"{{{CONTENT_TYPES_NS}}}Types")
    ElementTree.SubElement(root, f"{{{CONTENT_TYPES_NS}}}Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    ElementTree.SubElement(root, f"{{{CONTENT_TYPES_NS}}}Default", {"Extension": "xml", "ContentType": "application/xml"})
    ElementTree.SubElement(root, f"{{{CONTENT_TYPES_NS}}}Override", {"PartName": "/xl/workbook.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"})
    for number in (1, 2):
        ElementTree.SubElement(root, f"{{{CONTENT_TYPES_NS}}}Override", {"PartName": f"/xl/worksheets/sheet{number}.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"})
    return _xml_bytes(root)


def _root_relationships_xml() -> bytes:
    root = ElementTree.Element(f"{{{PKG_REL_NS}}}Relationships")
    ElementTree.SubElement(root, f"{{{PKG_REL_NS}}}Relationship", {"Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "Target": "xl/workbook.xml"})
    return _xml_bytes(root)


def _workbook_relationships_xml() -> bytes:
    root = ElementTree.Element(f"{{{PKG_REL_NS}}}Relationships")
    for number in (1, 2):
        ElementTree.SubElement(root, f"{{{PKG_REL_NS}}}Relationship", {"Id": f"rId{number}", "Type": WORKSHEET_REL_TYPE, "Target": f"worksheets/sheet{number}.xml"})
    return _xml_bytes(root)


def _xml_bytes(root: ElementTree.Element) -> bytes:
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _column_name(number: int) -> str:
    name = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        name = chr(65 + remainder) + name
    return name
