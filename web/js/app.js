import { apiFetch } from "./api.js";
import { registerRoute, startRouter } from "./router.js";
import { clearSensitiveState, enterCandidateMode, getState, setState } from "./store.js";
import { renderCandidateAssessment } from "./views/candidate_assessment.js";

const main = document.querySelector("#main-content");
const navigation = document.querySelector("#primary-navigation");
const modeLabel = document.querySelector("#mode-label");

const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};

function button(label, action, kind = "") {
  const node = element("button", label, kind);
  node.type = "button";
  node.addEventListener("click", () => Promise.resolve(action()).catch(showError));
  return node;
}

function link(label, href) {
  const node = element("a", label);
  node.href = href;
  return node;
}

function field(labelText, name, type = "text", value = "") {
  const label = element("label", labelText);
  const input = element(type === "textarea" ? "textarea" : "input");
  if (type !== "textarea") input.type = type;
  input.name = name;
  input.value = value ?? "";
  label.append(input);
  return { label, input };
}

function panel(title) {
  const section = element("section", undefined, "card stack");
  section.append(element("h1", title));
  return section;
}

function showError(error) {
  const message = element("p", `${error.code || "ERROR"}: ${error.message}`, "error notice");
  main.prepend(message);
}

async function boot() {
  const bootstrap = await apiFetch("/api/v1/bootstrap");
  setState({ startupToken: bootstrap.startupToken });
  renderAuthentication(bootstrap.pinConfigured);
}

function renderAuthentication(pinConfigured) {
  navigation.replaceChildren();
  const section = panel(pinConfigured ? "Mở Committee Mode" : "Thiết lập Committee PIN");
  const pin = field("PIN", "pin", "password");
  const submit = button(pinConfigured ? "Đăng nhập" : "Lưu PIN", async () => {
    if (pinConfigured) {
      const result = await apiFetch("/api/v1/auth/committee-session", {
        method: "POST", body: JSON.stringify({ pin: pin.input.value }),
      });
      setState({ committeeSession: result.committeeSession, mode: "COMMITTEE" });
      launchCommittee();
    } else {
      await apiFetch("/api/v1/auth/committee-pin", {
        method: "POST", body: JSON.stringify({ pin: pin.input.value }),
      });
      renderAuthentication(true);
    }
  }, "primary");
  section.append(element("p", "PIN chỉ bảo vệ Committee Mode trên máy này.", "muted"), pin.label, submit);
  main.replaceChildren(section);
}

let routerStarted = false;
function launchCommittee() {
  modeLabel.textContent = "Committee Mode";
  navigation.replaceChildren(
    link("Interview Cases", "#/cases"),
    link("Tạo case", "#/cases/new"),
    link("Backup", "#/backups"),
  );
  if (!routerStarted) {
    registerRoute("/cases", () => renderCases());
    registerRoute("/cases/new", () => renderNewCase());
    registerRoute("/cases/:caseId", ({ caseId }) => renderCase(caseId));
    registerRoute("/cases/:caseId/documents", ({ caseId }) => renderDocuments(caseId));
    registerRoute("/cases/:caseId/questions", ({ caseId }) => renderQuestions(caseId));
    registerRoute("/cases/:caseId/check-in", ({ caseId }) => renderCheckIn(caseId));
    registerRoute("/cases/:caseId/ai", ({ caseId }) => renderAI(caseId));
    registerRoute("/cases/:caseId/brief", ({ caseId }) => renderBrief(caseId));
    registerRoute("/cases/:caseId/live", ({ caseId }) => renderLive(caseId));
    registerRoute("/cases/:caseId/evaluation", ({ caseId }) => renderEvaluation(caseId));
    registerRoute("/candidate/assessment", () => renderCandidate());
    registerRoute("/candidate/submitted", () => renderSubmitted());
    registerRoute("/backups", () => renderBackups());
    routerStarted = true;
    startRouter((route) => main.replaceChildren(panel(`Không tìm thấy: ${route}`)));
  } else {
    location.hash = "/cases";
  }
}

async function renderCases() {
  const data = await apiFetch("/api/v1/interview-cases");
  const section = panel("Interview Cases");
  section.append(link("+ Tạo Interview Case", "#/cases/new"));
  if (!data.items.length) section.append(element("p", "Chưa có case.", "muted"));
  for (const item of data.items) {
    const row = element("article", undefined, "list-row");
    row.append(
      link(`${item.candidate.candidateCode} — ${item.job.positionTitle}`, `#/cases/${item.id}`),
      element("span", item.status, "badge"),
    );
    section.append(row);
  }
  main.replaceChildren(section);
}

async function renderNewCase() {
  const section = panel("Tạo Interview Case");
  const fields = [
    field("Mã ứng viên", "candidateCode"), field("Tên ứng viên", "fullName"),
    field("Mã vị trí", "jobCode"), field("Vị trí", "positionTitle"),
    field("Level", "targetLevel"), field("Tên Lead HĐCM", "leadName"),
  ];
  section.append(...fields.map((item) => item.label));
  section.append(button("Tạo case", async () => {
    const values = Object.fromEntries(fields.map((item) => [item.input.name, item.input.value]));
    const job = (await apiFetch("/api/v1/jobs", { method: "POST", body: JSON.stringify(values) })).job;
    const candidate = (await apiFetch("/api/v1/candidates", { method: "POST", body: JSON.stringify(values) })).candidate;
    const created = await apiFetch("/api/v1/interview-cases", {
      method: "POST", body: JSON.stringify({
        candidateId: candidate.id, jobId: job.id,
        committeeMembers: [{ displayName: values.leadName, role: "LEAD" }],
      }),
    });
    location.hash = `/cases/${created.case.id}/documents`;
  }, "primary"));
  main.replaceChildren(section);
}

async function renderCase(caseId) {
  const { case: item } = await apiFetch(`/api/v1/interview-cases/${caseId}`);
  const section = panel(`${item.candidate.fullName} — ${item.job.positionTitle}`);
  section.append(element("p", `Trạng thái: ${item.status}`, "badge"));
  const actions = element("div", undefined, "actions");
  const routes = [
    ["JD / CV", "documents"], ["Bộ câu hỏi", "questions"], ["Check-in", "check-in"],
    ["AI / fallback", "ai"], ["Interview Brief", "brief"], ["Live Interview", "live"],
    ["Final Evaluation", "evaluation"],
  ];
  for (const [label, route] of routes) actions.append(link(label, `#/cases/${caseId}/${route}`));
  section.append(actions);
  main.replaceChildren(section);
}

async function renderDocuments(caseId) {
  const data = await apiFetch(`/api/v1/interview-cases/${caseId}/documents`);
  const section = panel("JD và CV đã làm sạch");
  for (const type of ["JD", "CV"]) {
    const current = data.items.find((item) => item.documentType === type && item.isCurrent);
    const input = field(`${type} text`, type, "textarea", current?.extractedText || "");
    section.append(input.label, button(`Lưu và xác nhận ${type}`, async () => {
      const created = await apiFetch(`/api/v1/interview-cases/${caseId}/documents`, {
        method: "POST", body: JSON.stringify({ documentType: type, sourceKind: "MANUAL_TEXT", text: input.input.value }),
      });
      await apiFetch(`/api/v1/interview-cases/${caseId}/documents/${created.document.id}/confirm`, {
        method: "POST", body: JSON.stringify({ confirmed: true, textSha256: created.document.contentSha256 }),
      });
      await renderDocuments(caseId);
    }));
  }
  section.append(link("Tiếp: Bộ câu hỏi", `#/cases/${caseId}/questions`));
  main.replaceChildren(section);
}

function manualQuestions() {
  const topics = ["Nền tảng chuyên môn", "Tình huống thực tế", "Kinh nghiệm trong CV", "Trade-off", "Khoảng trống bằng chứng"];
  return topics.map((topic, index) => ({
    displayOrder: index + 1, questionText: `${topic}: hãy trình bày một ví dụ cụ thể.`,
    competencyKey: `competency-${index + 1}`, sourceKind: "MANUAL",
    purpose: `Đánh giá ${topic}`, questionType: index === 1 ? "SCENARIO" : "LONG_TEXT",
    difficulty: "MEDIUM", expectedEvidence: "Bối cảnh, hành động, kết quả và lập luận",
    rubric: { score0: "Không trả lời", score1: "Rất yếu", score2: "Cơ bản", score3: "Đáp ứng", score4: "Tốt, có bằng chứng" },
    isRequired: true, estimatedSeconds: 150,
  }));
}

async function renderQuestions(caseId) {
  const section = panel("Bộ câu hỏi");
  let questionSet = null;
  try { questionSet = (await apiFetch(`/api/v1/interview-cases/${caseId}/question-set`)).questionSet; } catch (error) { if (error.status !== 404) throw error; }
  if (!questionSet) {
    section.append(
      button("Sinh bằng AI", async () => {
        const task = await apiFetch(`/api/v1/interview-cases/${caseId}/question-set`, { method: "POST", body: JSON.stringify({ operation: "GENERATE" }) });
        await waitForTask(task.taskId);
        await renderQuestions(caseId);
      }, "primary"),
      button("Dùng bộ câu hỏi manual", async () => {
        await apiFetch(`/api/v1/interview-cases/${caseId}/question-set`, { method: "POST", body: JSON.stringify({ operation: "MANUAL", questions: manualQuestions() }) });
        await renderQuestions(caseId);
      }),
    );
  } else {
    section.append(element("p", `${questionSet.status} — version ${questionSet.versionNo}`, "badge"));
    for (const question of questionSet.questions) section.append(element("p", `${question.displayOrder}. ${question.questionText}`));
    if (questionSet.status !== "APPROVED") {
      const overview = (await apiFetch(`/api/v1/interview-cases/${caseId}`)).case;
      section.append(button("Duyệt bộ câu hỏi", async () => {
        await apiFetch(`/api/v1/interview-cases/${caseId}/question-set/approve`, {
          method: "POST", body: JSON.stringify({ questionSetId: questionSet.id, memberId: overview.committeeMembers[0].id, confirmation: "APPROVE_QUESTION_SET" }),
        });
        location.hash = `/cases/${caseId}/check-in`;
      }, "primary"));
    }
  }
  main.replaceChildren(section);
}

async function renderCheckIn(caseId) {
  const overview = (await apiFetch(`/api/v1/interview-cases/${caseId}`)).case;
  const section = panel("Candidate check-in");
  let attempt;
  try { attempt = (await apiFetch(`/api/v1/interview-cases/${caseId}/assessment`)).attempt; }
  catch (error) {
    if (error.status !== 404) throw error;
    attempt = (await apiFetch(`/api/v1/interview-cases/${caseId}/assessment`, {
      method: "POST", body: JSON.stringify({ questionSetId: overview.questionSetId }),
    })).attempt;
  }
  section.append(element("p", `Attempt: ${attempt.status}`));
  if (attempt.status === "READY_FOR_ASSESSMENT") {
    section.append(button("Xác nhận và bắt đầu Candidate Mode", async () => {
      const started = (await apiFetch(`/api/v1/interview-cases/${caseId}/assessment/start`, {
        method: "POST", body: JSON.stringify({ candidateCodeConfirmed: true, committeePinVerified: true }),
      })).attempt;
      enterCandidateMode({ candidateToken: started.candidateToken, attemptId: started.id, caseId });
      location.hash = "/candidate/assessment";
    }, "primary"));
  }
  main.replaceChildren(section);
}

async function renderCandidate() {
  modeLabel.textContent = "Candidate Mode";
  navigation.replaceChildren();
  const state = getState();
  if (!state.candidateAttemptId || !state.candidateToken) {
    main.replaceChildren(panel("Candidate session không còn hiệu lực"));
    return;
  }
  await renderCandidateAssessment(main, state.candidateAttemptId);
}

function renderSubmitted() {
  const section = panel("Bài đã được nộp. Vui lòng chờ HĐCM.");
  section.append(button("Mở lại Committee Mode", () => {
    clearSensitiveState();
    modeLabel.textContent = "Locked";
    location.hash = "";
    renderAuthentication(true);
  }));
  main.replaceChildren(section);
}

async function renderAI(caseId) {
  const overview = (await apiFetch(`/api/v1/interview-cases/${caseId}`)).case;
  const section = panel("AI Evaluation / Manual fallback");
  section.append(button("Phân tích câu trả lời", async () => {
    const task = await apiFetch(`/api/v1/interview-cases/${caseId}/ai/evaluate`, {
      method: "POST", body: JSON.stringify({ attemptId: overview.assessmentAttemptId }),
    });
    const result = await waitForTask(task.taskId);
    if (result.task.status === "COMPLETED") location.hash = `/cases/${caseId}/brief`;
    else await renderAI(caseId);
  }, "primary"));
  if (overview.status === "AI_ANALYSIS_FAILED") {
    section.append(button("Tạo Interview Brief manual", async () => {
      await apiFetch(`/api/v1/interview-cases/${caseId}/interview-brief`, {
        method: "POST", body: JSON.stringify({
          sourceKind: "MANUAL", attemptId: overview.assessmentAttemptId,
          memberId: overview.committeeMembers[0].id,
          brief: { summary: "Brief manual — AI không khả dụng", strengths: [], gaps: [], conflicts: [], competencyMatrix: [], requiredLiveQuestions: ["Xác minh năng lực chính", "Làm rõ kinh nghiệm", "Thảo luận trade-off"], additionalLiveQuestions: [], limitations: ["AI unavailable"] },
        }),
      });
      location.hash = `/cases/${caseId}/brief`;
    }));
  }
  main.replaceChildren(section);
}

async function renderBrief(caseId) {
  const { brief } = await apiFetch(`/api/v1/interview-cases/${caseId}/interview-brief`);
  const section = panel("Interview Brief");
  section.append(element("p", brief.brief.summary), element("p", `Nguồn: ${brief.sourceKind} — version ${brief.versionNo}`, "muted"));
  const list = element("ol");
  for (const question of brief.brief.requiredLiveQuestions) list.append(element("li", question));
  section.append(element("h2", "Câu hỏi bắt buộc"), list, link("Mở Live Interview", `#/cases/${caseId}/live`));
  main.replaceChildren(section);
}

async function renderLive(caseId) {
  const overview = (await apiFetch(`/api/v1/interview-cases/${caseId}`)).case;
  const memberId = overview.committeeMembers[0].id;
  if (overview.status === "INTERVIEW_BRIEF_READY") {
    await apiFetch(`/api/v1/interview-cases/${caseId}/live-interview/start`, { method: "POST", body: JSON.stringify({ memberId }) });
  }
  const records = (await apiFetch(`/api/v1/interview-cases/${caseId}/live-interview/records`)).items;
  const section = panel("Live Interview");
  for (const record of records) {
    const row = element("article", undefined, "question-card");
    const notes = field("Ghi chú", `notes-${record.sequenceNo}`, "textarea", record.liveNotes || "");
    row.append(element("h2", `${record.sequenceNo}. ${record.questionText}`), notes.label,
      button("Lưu đã hỏi", async () => {
        await apiFetch(`/api/v1/interview-cases/${caseId}/live-interview/records`, { method: "POST", body: JSON.stringify({ sequenceNo: record.sequenceNo, committeeMemberId: memberId, askedStatus: "ASKED", liveNotes: notes.input.value, score: 3, evidenceStatus: "VERIFIED" }) });
      }),
      button("Bỏ qua", async () => {
        await apiFetch(`/api/v1/interview-cases/${caseId}/live-interview/records`, { method: "POST", body: JSON.stringify({ sequenceNo: record.sequenceNo, committeeMemberId: memberId, askedStatus: "SKIPPED", liveNotes: notes.input.value, score: null, evidenceStatus: "NOT_ASSESSED" }) });
      }));
    section.append(row);
  }
  section.append(button("Hoàn tất Live Interview", async () => {
    await apiFetch(`/api/v1/interview-cases/${caseId}/live-interview/complete`, { method: "POST", body: JSON.stringify({ memberId, reason: "AGENDA_COMPLETE" }) });
    location.hash = `/cases/${caseId}/evaluation`;
  }, "primary"));
  main.replaceChildren(section);
}

async function renderEvaluation(caseId) {
  const overview = (await apiFetch(`/api/v1/interview-cases/${caseId}`)).case;
  const section = panel("Final Evaluation của HĐCM");
  const summary = field("Tóm tắt", "summary", "textarea");
  const result = element("select");
  result.name = "finalResult";
  for (const value of ["PASS", "FAIL", "NEXT_ROUND", "NEEDS_ADDITIONAL_ASSESSMENT"]) {
    const option = element("option", value); option.value = value; result.append(option);
  }
  const resultLabel = element("label", "Kết luận"); resultLabel.append(result);
  section.append(resultLabel, summary.label, button("Lưu draft và chốt", async () => {
    const draft = (await apiFetch(`/api/v1/interview-cases/${caseId}/final-evaluation`, {
      method: "PUT", body: JSON.stringify({ finalResult: result.value, summary: summary.input.value, strengths: [], gaps: [], risks: [] }),
    })).evaluation;
    await apiFetch(`/api/v1/interview-cases/${caseId}/final-evaluation/finalize`, {
      method: "POST", body: JSON.stringify({ evaluationId: draft.id, memberId: overview.committeeMembers[0].id, confirmation: "FINALIZE_EVALUATION" }),
    });
    location.hash = `/cases/${caseId}`;
  }, "danger"));
  main.replaceChildren(section);
}

async function renderBackups() {
  const section = panel("Backup và Export");
  section.append(button("Tạo backup đầy đủ", async () => {
    const result = await apiFetch("/api/v1/backups", { method: "POST", body: JSON.stringify({ label: "manual", includeDocuments: true }) });
    section.append(element("p", `Đã tạo: ${result.backup.safePathSummary}`, "notice"));
  }, "primary"));
  main.replaceChildren(section);
}

async function waitForTask(taskId) {
  const status = element("p", "AI task đang chờ…", "notice");
  main.prepend(status);
  for (let attempt = 0; attempt < 150; attempt += 1) {
    const result = await apiFetch(`/api/v1/tasks/${taskId}`);
    status.textContent = `AI task: ${result.task.status}`;
    if (["COMPLETED", "FAILED"].includes(result.task.status)) return result;
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  throw new Error("AI task timeout");
}

boot().catch(showError);
