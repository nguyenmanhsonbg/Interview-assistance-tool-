from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from typing import Any, Mapping, Sequence

from app.domain.errors import ValidationError


HTML_PACKAGE_FORMAT_VERSION = "candidate-html.v1"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
MAX_HTML_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_QUESTIONS = 9
MAX_TEXT_CHARS = 10_000

_PACKAGE_TYPES = {"QUESTION", "DRAFT", "RESPONSE"}
_QUESTION_TYPES = {"SHORT_TEXT", "LONG_TEXT", "SCENARIO"}
_MANIFEST_FIELDS = {
    "formatVersion",
    "packageId",
    "questionSetId",
    "questionSetVersion",
    "questionSetFingerprint",
    "durationSeconds",
    "questionCount",
    "exportedAt",
}
_QUESTION_FIELDS = {
    "questionId",
    "displayOrder",
    "questionText",
    "questionType",
    "isRequired",
}
_ANSWER_FIELDS = {"questionId", "answerText", "isAnswered"}
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PAYLOAD_ID = "candidate-package-payload"


@dataclass(frozen=True)
class CandidateHtmlPackage:
    package_type: str
    manifest: dict[str, Any]
    questions: list[dict[str, Any]]
    answers: list[dict[str, Any]]
    package_sha256: str


class _PayloadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.payload_parts: list[str] = []
        self._inside_payload = False
        self._found_payload = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attributes = dict(attrs)
        if (
            attributes.get("id") == _PAYLOAD_ID
            and attributes.get("type") == "application/json"
        ):
            if self._found_payload:
                raise ValidationError("HTML package contains multiple payloads")
            self._found_payload = True
            self._inside_payload = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._inside_payload:
            self._inside_payload = False

    def handle_data(self, data: str) -> None:
        if self._inside_payload:
            self.payload_parts.append(data)


def export_question_package(
    manifest: Mapping[str, Any], questions: Sequence[Mapping[str, Any]]
) -> bytes:
    normalized_questions = _normalize_questions(
        [_candidate_question(question) for question in questions]
    )
    normalized_manifest = _normalize_manifest(manifest, normalized_questions)
    payload = {
        "formatVersion": HTML_PACKAGE_FORMAT_VERSION,
        "packageType": "QUESTION",
        "manifest": normalized_manifest,
        "questions": normalized_questions,
        "answers": [],
    }
    return _render_html(payload)


def import_candidate_package(raw: bytes) -> CandidateHtmlPackage:
    if not isinstance(raw, bytes) or not raw:
        raise ValidationError("Candidate HTML package is required")
    if len(raw) > MAX_HTML_PACKAGE_BYTES:
        raise ValidationError("Candidate HTML package exceeds the size limit")

    parser = _PayloadParser()
    try:
        parser.feed(raw.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValidationError) as error:
        if isinstance(error, ValidationError):
            raise
        raise ValidationError("Candidate HTML package must be UTF-8") from error
    if not parser._found_payload:
        raise ValidationError("Candidate HTML package payload is missing")
    try:
        payload = json.loads("".join(parser.payload_parts))
    except json.JSONDecodeError as error:
        raise ValidationError("Candidate HTML package payload is invalid JSON") from error

    normalized = _normalize_payload(payload)
    return CandidateHtmlPackage(
        package_type=normalized["packageType"],
        manifest=normalized["manifest"],
        questions=normalized["questions"],
        answers=normalized["answers"],
        package_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Candidate HTML package payload must be an object")
    allowed = {"formatVersion", "packageType", "manifest", "questions", "answers", "clientState"}
    if set(payload) - allowed:
        raise ValidationError("Candidate HTML package contains unknown fields")
    if payload.get("formatVersion") != HTML_PACKAGE_FORMAT_VERSION:
        raise ValidationError("Unsupported candidate HTML package version")
    package_type = payload.get("packageType")
    if package_type not in _PACKAGE_TYPES:
        raise ValidationError("Unsupported candidate HTML package type")
    questions = _normalize_questions(payload.get("questions"))
    manifest = _normalize_manifest(payload.get("manifest"), questions)
    answers = _normalize_answers(payload.get("answers"), questions, package_type)
    client_state = payload.get("clientState")
    if client_state is not None and not isinstance(client_state, dict):
        raise ValidationError("Candidate HTML package clientState is invalid")
    return {
        "formatVersion": HTML_PACKAGE_FORMAT_VERSION,
        "packageType": package_type,
        "manifest": manifest,
        "questions": questions,
        "answers": answers,
        **({"clientState": client_state} if client_state is not None else {}),
    }


def _normalize_manifest(
    manifest: Any, questions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS:
        raise ValidationError("Candidate HTML package manifest is invalid")
    package_id = manifest.get("packageId")
    question_set_id = manifest.get("questionSetId")
    if not isinstance(package_id, str) or not _ID_RE.fullmatch(package_id):
        raise ValidationError("Candidate HTML package ID is invalid")
    if not isinstance(question_set_id, str) or not _ID_RE.fullmatch(question_set_id):
        raise ValidationError("Candidate HTML Question Set ID is invalid")
    if manifest.get("formatVersion") != HTML_PACKAGE_FORMAT_VERSION:
        raise ValidationError("Candidate HTML package manifest version is invalid")
    version = manifest.get("questionSetVersion")
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise ValidationError("Candidate HTML Question Set version is invalid")
    fingerprint = manifest.get("questionSetFingerprint")
    if not isinstance(fingerprint, str) or not _SHA256_RE.fullmatch(fingerprint):
        raise ValidationError("Candidate HTML Question Set fingerprint is invalid")
    duration = manifest.get("durationSeconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 600 <= duration <= 900:
        raise ValidationError("Candidate HTML duration is invalid")
    count = manifest.get("questionCount")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(questions):
        raise ValidationError("Candidate HTML question count is invalid")
    exported_at = manifest.get("exportedAt")
    if not isinstance(exported_at, str) or not exported_at.strip() or len(exported_at) > 64:
        raise ValidationError("Candidate HTML exportedAt is invalid")
    return {
        "formatVersion": HTML_PACKAGE_FORMAT_VERSION,
        "packageId": package_id,
        "questionSetId": question_set_id,
        "questionSetVersion": version,
        "questionSetFingerprint": fingerprint,
        "durationSeconds": duration,
        "questionCount": count,
        "exportedAt": exported_at,
    }


def _normalize_questions(questions: Any) -> list[dict[str, Any]]:
    if not isinstance(questions, (list, tuple)) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise ValidationError("Candidate HTML questions are invalid")
    normalized: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, Mapping) or set(question) != _QUESTION_FIELDS:
            raise ValidationError("Candidate HTML question fields are invalid")
        question_id = question.get("questionId")
        text = question.get("questionText")
        order = question.get("displayOrder")
        question_type = question.get("questionType")
        if not isinstance(question_id, str) or not _ID_RE.fullmatch(question_id):
            raise ValidationError("Candidate HTML question ID is invalid")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise ValidationError("Candidate HTML question text is invalid")
        if isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= MAX_QUESTIONS:
            raise ValidationError("Candidate HTML display order is invalid")
        if question_type not in _QUESTION_TYPES:
            raise ValidationError("Candidate HTML question type is invalid")
        if not isinstance(question.get("isRequired"), bool):
            raise ValidationError("Candidate HTML required flag is invalid")
        normalized.append({
            "questionId": question_id,
            "displayOrder": order,
            "questionText": text,
            "questionType": question_type,
            "isRequired": question["isRequired"],
        })
    ids = [item["questionId"] for item in normalized]
    orders = [item["displayOrder"] for item in normalized]
    if len(ids) != len(set(ids)) or len(orders) != len(set(orders)):
        raise ValidationError("Candidate HTML questions must have unique IDs and orders")
    if sorted(orders) != list(range(1, len(normalized) + 1)):
        raise ValidationError("Candidate HTML question orders must be contiguous")
    return sorted(normalized, key=lambda item: item["displayOrder"])


def _candidate_question(question: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(question, Mapping):
        raise ValidationError("Candidate HTML question fields are invalid")
    try:
        return {
            "questionId": question["questionId"],
            "displayOrder": question["displayOrder"],
            "questionText": question["questionText"],
            "questionType": question["questionType"],
            "isRequired": question["isRequired"],
        }
    except KeyError as error:
        raise ValidationError("Candidate HTML question fields are invalid") from error


def _normalize_answers(
    answers: Any, questions: Sequence[Mapping[str, Any]], package_type: str
) -> list[dict[str, Any]]:
    if not isinstance(answers, list):
        raise ValidationError("Candidate HTML answers are invalid")
    if package_type == "QUESTION":
        if answers:
            raise ValidationError("Question package cannot contain answers")
        return []
    if len(answers) != len(questions):
        raise ValidationError("Candidate HTML answer count is invalid")
    question_ids = {question["questionId"] for question in questions}
    normalized: list[dict[str, Any]] = []
    for answer in answers:
        if not isinstance(answer, Mapping) or set(answer) != _ANSWER_FIELDS:
            raise ValidationError("Candidate HTML answer fields are invalid")
        question_id = answer.get("questionId")
        answer_text = answer.get("answerText")
        is_answered = answer.get("isAnswered")
        if question_id not in question_ids:
            raise ValidationError("Candidate HTML answer question is unknown")
        if isinstance(answer_text, str):
            if len(answer_text) > MAX_TEXT_CHARS:
                raise ValidationError("Candidate HTML answer is too long")
        else:
            raise ValidationError("Candidate HTML answer text is invalid")
        if not isinstance(is_answered, bool):
            raise ValidationError("Candidate HTML answer flag is invalid")
        if is_answered and not answer_text.strip():
            raise ValidationError("Answered candidate HTML answer must contain text")
        if not is_answered and answer_text != "":
            raise ValidationError("Unanswered candidate HTML answer must be blank")
        normalized.append({
            "questionId": question_id,
            "answerText": answer_text,
            "isAnswered": is_answered,
            "assessmentStatus": "ANSWERED" if is_answered else "NOT_ASSESSED",
        })
    ids = [answer["questionId"] for answer in normalized]
    if len(ids) != len(set(ids)) or set(ids) != question_ids:
        raise ValidationError("Candidate HTML answers must match all questions")
    question_order = {question["questionId"]: question["displayOrder"] for question in questions}
    return sorted(normalized, key=lambda item: question_order[item["questionId"]])


def _render_html(payload: Mapping[str, Any]) -> bytes:
    encoded = _safe_json(payload)
    package_id = escape(str(payload["manifest"]["packageId"]), quote=True)
    html = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Candidate Assessment</title>
  <style>
    :root { color-scheme: light; font-family: "Segoe UI", Arial, sans-serif; }
    body { margin: 0; background: #f5f6f9; color: #202338; }
    main { max-width: 920px; margin: 0 auto; padding: 24px; }
    header, article, .actions, .notice { background: #fff; border: 1px solid #e5e7ee; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
    header { position: sticky; top: 0; z-index: 1; }
    h1, h2, p { margin-top: 0; }
    .muted { color: #666d80; }
    .status { color: #22664e; min-height: 1.4em; }
    .timer { font-size: 18px; font-weight: 700; }
    textarea { box-sizing: border-box; width: 100%; min-height: 150px; padding: 12px; border: 1px solid #cfd3df; border-radius: 8px; font: inherit; line-height: 1.5; resize: vertical; }
    textarea:focus { outline: 3px solid #d9d3fa; border-color: #6250c4; }
    button { min-height: 40px; border: 0; border-radius: 8px; padding: 0 16px; background: #6250c4; color: #fff; font: inherit; cursor: pointer; }
    button.secondary { background: #eceaf8; color: #3d347f; }
    button:disabled { cursor: not-allowed; opacity: .55; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .question-number { color: #6250c4; font-weight: 700; }
  </style>
</head>
<body>
  <main id="candidate-app" data-package-id="__PACKAGE_ID__">
    <header>
      <h1>Assessment</h1>
      <p id="summary" class="muted"></p>
      <p id="timer" class="timer"></p>
      <p id="status" class="status" role="status"></p>
    </header>
    <section id="questions" aria-live="polite"></section>
    <section id="actions" class="actions"></section>
  </main>
  <script id="candidate-package-payload" type="application/json">__PAYLOAD__</script>
  <script>
  (function () {
    "use strict";
    var payloadNode = document.getElementById("candidate-package-payload");
    var payload = JSON.parse(payloadNode.textContent);
    var questionsNode = document.getElementById("questions");
    var actionsNode = document.getElementById("actions");
    var statusNode = document.getElementById("status");
    var timerNode = document.getElementById("timer");
    var summaryNode = document.getElementById("summary");
    var answerMap = new Map((payload.answers || []).map(function (answer) {
      return [answer.questionId, answer];
    }));
    var startedAt = payload.clientState && payload.clientState.startedAt;
    var locked = payload.packageType === "RESPONSE";

    function addText(parent, tag, value, className) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      node.textContent = String(value == null ? "" : value);
      parent.appendChild(node);
      return node;
    }

    function safeJson(value) {
      return JSON.stringify(value)
        .replace(/</g, "\\u003c")
        .replace(/>/g, "\\u003e")
        .replace(/&/g, "\\u0026")
        .replace(/\\u2028/g, "\\u2028")
        .replace(/\\u2029/g, "\\u2029");
    }

    function answerRows() {
      return payload.questions.map(function (question) {
        var input = document.getElementById("answer-" + question.questionId);
        var text = input ? input.value : ((answerMap.get(question.questionId) || {}).answerText || "");
        var answered = Boolean(text.trim());
        return { questionId: question.questionId, answerText: answered ? text : "", isAnswered: answered };
      });
    }

    function downloadPackage(packageType, answers) {
      var next = Object.assign({}, payload, {
        packageType: packageType,
        answers: answers,
        clientState: { startedAt: startedAt || new Date().toISOString(), submittedAt: packageType === "RESPONSE" ? new Date().toISOString() : null }
      });
      var clone = document.documentElement.cloneNode(true);
      clone.querySelector("#candidate-package-payload").textContent = safeJson(next);
      var blob = new Blob(["<!doctype html>\\n", clone.outerHTML], { type: "text/html" });
      var link = document.createElement("a");
      var suffix = packageType === "DRAFT" ? "-draft" : "-response";
      link.download = "candidate-assessment-" + String(payload.manifest.packageId).replace(/[^A-Za-z0-9_.-]/g, "_") + suffix + ".html";
      link.href = URL.createObjectURL(blob);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(function () { URL.revokeObjectURL(link.href); }, 0);
    }

    function renderQuestions() {
      payload.questions.forEach(function (question) {
        var article = document.createElement("article");
        addText(article, "h2", question.displayOrder + ". " + question.questionText, "question-number");
        var label = document.createElement("label");
        label.htmlFor = "answer-" + question.questionId;
        label.textContent = "Câu trả lời";
        article.appendChild(label);
        var input = document.createElement("textarea");
        input.id = "answer-" + question.questionId;
        input.name = "answer-" + question.questionId;
        input.disabled = locked;
        input.value = (answerMap.get(question.questionId) || {}).answerText || "";
        article.appendChild(input);
        questionsNode.appendChild(article);
      });
    }

    function renderResponse() {
      statusNode.textContent = "Bài đã nộp. Hãy gửi file response này cho HĐCM.";
      payload.answers.forEach(function (answer) {
        var question = payload.questions.find(function (item) { return item.questionId === answer.questionId; });
        var article = document.createElement("article");
        addText(article, "h2", question.displayOrder + ". " + question.questionText, "question-number");
        addText(article, "p", answer.isAnswered ? answer.answerText : "Chưa trả lời", "muted");
        questionsNode.appendChild(article);
      });
    }

    function updateTimer() {
      if (!startedAt || locked) return;
      var elapsed = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
      var remaining = Math.max(0, payload.manifest.durationSeconds - elapsed);
      var minutes = String(Math.floor(remaining / 60)).padStart(2, "0");
      var seconds = String(remaining % 60).padStart(2, "0");
      timerNode.textContent = "Thời gian còn lại: " + minutes + ":" + seconds;
      if (remaining === 0) statusNode.textContent = "Đã hết giờ. Hãy nộp bài.";
    }

    function start() {
      startedAt = startedAt || new Date().toISOString();
      statusNode.textContent = payload.packageType === "DRAFT" ? "Đã khôi phục bản nháp." : "Đang làm bài.";
      updateTimer();
      window.setInterval(updateTimer, 1000);
    }

    summaryNode.textContent = payload.manifest.questionCount + " câu hỏi · " + Math.floor(payload.manifest.durationSeconds / 60) + " phút";
    if (locked) {
      renderResponse();
    } else {
      renderQuestions();
      var startButton = document.createElement("button");
      startButton.textContent = payload.packageType === "DRAFT" ? "Tiếp tục làm bài" : "Bắt đầu làm bài";
      startButton.addEventListener("click", function () { startButton.disabled = true; start(); });
      actionsNode.appendChild(startButton);
      var draftButton = document.createElement("button");
      draftButton.className = "secondary";
      draftButton.textContent = "Lưu bản nháp";
      draftButton.addEventListener("click", function () { if (!startedAt) start(); downloadPackage("DRAFT", answerRows()); });
      actionsNode.appendChild(draftButton);
      var submitButton = document.createElement("button");
      submitButton.textContent = "Nộp bài";
      submitButton.addEventListener("click", function () {
        if (!window.confirm("Bạn có chắc muốn nộp bài? Sau khi nộp không thể sửa.")) return;
        if (!startedAt) start();
        locked = true;
        document.querySelectorAll("textarea").forEach(function (input) { input.disabled = true; });
        statusNode.textContent = "Đã khóa bài và đang tải file response.";
        downloadPackage("RESPONSE", answerRows());
      });
      actionsNode.appendChild(submitButton);
      if (startedAt) start();
    }
  }());
  </script>
</body>
</html>
"""
    html = html.replace("__PACKAGE_ID__", package_id).replace("__PAYLOAD__", encoded)
    raw = html.encode("utf-8")
    if len(raw) > MAX_HTML_PACKAGE_BYTES:
        raise ValidationError("Candidate HTML package exceeds the size limit")
    return raw


def _safe_json(value: Mapping[str, Any]) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
