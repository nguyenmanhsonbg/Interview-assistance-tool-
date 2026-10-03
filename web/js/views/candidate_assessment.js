import { apiFetch } from "../api.js";
import { clearSensitiveState, getState } from "../store.js";
import { createTimer } from "../components/timer.js";

export async function renderCandidateAssessment(container, attemptId) {
  const { candidateToken } = getState();
  const headers = { "X-Candidate-Token": candidateToken };
  const view = await apiFetch(`/api/v1/assessment-attempts/${attemptId}/questions`, { headers });
  if (view.status === "ASSESSMENT_SUBMITTED") {
    location.hash = "/candidate/submitted";
    return;
  }
  const section = document.createElement("section");
  section.className = "candidate-workspace stack";
  const heading = document.createElement("h1");
  heading.textContent = "Bài đánh giá có giám sát";
  const saveStatus = document.createElement("p");
  saveStatus.className = "muted";
  saveStatus.setAttribute("aria-live", "polite");
  if (view.status !== "ASSESSMENT_IN_PROGRESS") {
    saveStatus.textContent = "Bài làm đang tạm khóa; hãy báo HĐCM để tiếp tục.";
  }
  const editors = [];
  let submitting = false;
  const submitIdempotencyKey = crypto.randomUUID();

  const save = async (editor) => {
    window.clearTimeout(editor.pending);
    editor.pending = null;
    if (!editor.dirty) return editor.inFlight;
    editor.inFlight = editor.inFlight.catch(() => {}).then(async () => {
      const revision = Number(editor.textarea.dataset.revision) + 1;
      const text = editor.textarea.value;
      editor.dirty = false;
      saveStatus.textContent = "Đang lưu…";
      try {
        const saved = await apiFetch(
          `/api/v1/assessment-attempts/${attemptId}/answers/${editor.questionId}`,
          {
            method: "PUT", headers,
            body: JSON.stringify({
              text,
              isAnswered: Boolean(text.trim()),
              clientRevision: revision,
            }),
          },
        );
        editor.textarea.dataset.revision = String(saved.saveRevision);
        saveStatus.textContent = "Đã lưu";
      } catch (error) {
        editor.dirty = true;
        throw error;
      }
    });
    return editor.inFlight;
  };

  const submit = async () => {
    if (submitting) return;
    submitting = true;
    for (const editor of editors) editor.textarea.disabled = true;
    try {
      for (const editor of editors) {
        window.clearTimeout(editor.pending);
        editor.pending = null;
        while (editor.dirty) await save(editor);
        await editor.inFlight;
      }
      const answerRevisions = Object.fromEntries(
        editors.map((editor) => [editor.questionId, Number(editor.textarea.dataset.revision)]),
      );
      await apiFetch(`/api/v1/assessment-attempts/${attemptId}/submit`, {
        method: "POST",
        headers: { ...headers, "X-Idempotency-Key": submitIdempotencyKey },
        body: JSON.stringify({ confirmation: "SUBMIT_ASSESSMENT", answerRevisions }),
      });
      clearSensitiveState();
      location.hash = "/candidate/submitted";
    } catch (error) {
      if (error.code === "UNAUTHENTICATED") {
        clearSensitiveState();
        location.hash = "/candidate/submitted";
        return;
      }
      submitting = false;
      for (const editor of editors) editor.textarea.disabled = false;
      throw error;
    }
  };

  const timer = createTimer(view.expiresAt, () => submit().catch(() => {
    saveStatus.textContent = "Không thể tự nộp; hãy báo HĐCM.";
  }));
  section.append(heading, timer.element, saveStatus);
  for (const question of view.questions) {
    const card = document.createElement("article");
    card.className = "question-card";
    const label = document.createElement("label");
    label.textContent = `${question.displayOrder}. ${question.questionText}`;
    const textarea = document.createElement("textarea");
    textarea.rows = 6;
    textarea.value = question.answerText;
    textarea.dataset.revision = String(question.saveRevision);
    textarea.disabled = view.status !== "ASSESSMENT_IN_PROGRESS";
    const editor = {
      questionId: question.id,
      textarea,
      pending: null,
      dirty: false,
      inFlight: Promise.resolve(),
    };
    editors.push(editor);
    textarea.addEventListener("input", () => {
      editor.dirty = true;
      saveStatus.textContent = "Có thay đổi chưa lưu";
      window.clearTimeout(editor.pending);
      editor.pending = window.setTimeout(() => save(editor).catch((error) => {
        saveStatus.textContent = `Lưu thất bại: ${error.message}`;
      }), 700);
    });
    label.append(textarea);
    card.append(label);
    section.append(card);
  }
  const submitButton = document.createElement("button");
  submitButton.type = "button";
  submitButton.className = "primary";
  submitButton.textContent = "Nộp bài";
  submitButton.disabled = view.status !== "ASSESSMENT_IN_PROGRESS";
  submitButton.addEventListener("click", () => {
    if (window.confirm("Nộp bài và khóa toàn bộ câu trả lời?")) {
      submit().catch((error) => { saveStatus.textContent = error.message; });
    }
  });
  section.append(submitButton);
  container.replaceChildren(section);
}
