import { apiFetch } from "../api.js";
import { getState } from "../store.js";
import { createTimer } from "../components/timer.js";

export async function renderCandidateAssessment(container, attemptId) {
  const { candidateToken } = getState();
  const headers = { "X-Candidate-Token": candidateToken };
  const view = await apiFetch(`/api/v1/assessment-attempts/${attemptId}/questions`, { headers });
  const section = document.createElement("section");
  const timer = createTimer(view.expiresAt, () => location.hash = "/candidate/submitted");
  section.append(timer.element);
  for (const question of view.questions) {
    const label = document.createElement("label");
    label.textContent = `${question.displayOrder}. ${question.questionText}`;
    const textarea = document.createElement("textarea");
    textarea.value = question.answerText;
    textarea.dataset.revision = String(question.saveRevision);
    let pending = null;
    textarea.addEventListener("input", () => {
      window.clearTimeout(pending);
      pending = window.setTimeout(async () => {
        const revision = Number(textarea.dataset.revision) + 1;
        const saved = await apiFetch(
          `/api/v1/assessment-attempts/${attemptId}/answers/${question.id}`,
          {
            method: "PUT", headers,
            body: JSON.stringify({
              text: textarea.value,
              isAnswered: Boolean(textarea.value.trim()),
              clientRevision: revision,
            }),
          },
        );
        textarea.dataset.revision = String(saved.saveRevision);
      }, 700);
    });
    label.append(textarea);
    section.append(label);
  }
  container.replaceChildren(section);
}
