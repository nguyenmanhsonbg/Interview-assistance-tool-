import { apiDownload, apiFetch, apiUpload } from "./api.js";
import { registerRoute, startRouter } from "./router.js";
import { clearSensitiveState, setState } from "./store.js";

const main = document.querySelector("#main-content");
const navigation = document.querySelector("#primary-navigation");
const modeLabel = document.querySelector("#mode-label");
const MAX_WORKBOOK_BYTES = 10 * 1024 * 1024;

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

function panel(title, subtitle) {
  const section = element("section", undefined, "card stack");
  section.append(element("h1", title));
  if (subtitle) section.append(element("p", subtitle, "muted"));
  return section;
}

function showError(error) {
  main.prepend(element("p", `${error.code || "ERROR"}: ${error.message}`, "error notice"));
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
  section.append(
    element("p", "PIN chỉ bảo vệ Committee Mode trên máy này.", "muted"),
    pin.label,
    button(pinConfigured ? "Đăng nhập" : "Lưu PIN", async () => {
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
    }, "primary"),
  );
  main.replaceChildren(section);
}

let routerStarted = false;

function launchCommittee() {
  modeLabel.textContent = "Committee Mode";
  const logout = button("Khóa phiên", () => {
    clearSensitiveState();
    location.hash = "";
    renderAuthentication(true);
  });
  navigation.replaceChildren(link("Interview Cases", "#/cases"), link("Tạo case", "#/cases/new"), logout);
  if (!routerStarted) {
    registerRoute("/cases", () => renderCases());
    registerRoute("/cases/new", () => renderNewCase());
    registerRoute("/cases/:caseId", ({ caseId }) => renderCase(caseId));
    registerRoute("/cases/:caseId/documents", ({ caseId }) => renderDocuments(caseId));
    registerRoute("/cases/:caseId/questions", ({ caseId }) => renderQuestions(caseId));
    registerRoute("/cases/:caseId/answers", ({ caseId }) => renderAnswers(caseId));
    registerRoute("/cases/:caseId/evaluation", ({ caseId }) => renderEvaluation(caseId));
    routerStarted = true;
    startRouter((route) => main.replaceChildren(panel(`Không tìm thấy: ${route}`)));
  } else {
    location.hash = "/cases";
  }
}

async function renderCases() {
  const data = await apiFetch("/api/v1/interview-cases");
  const section = panel("Interview Cases", "Flow chính: JD/CV → câu hỏi → Excel → đánh giá AI.");
  section.append(link("+ Tạo Interview Case", "#/cases/new"));
  if (!data.items.length) section.append(element("p", "Chưa có case.", "muted"));
  for (const item of data.items) {
    const row = element("article", undefined, "list-row");
    row.append(
      link(`${item.candidate.candidateCode} — ${item.job.positionTitle}`, `#/cases/${item.id}`),
      element("span", item.refinedFlowStatus || item.status, "badge"),
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
      method: "POST",
      body: JSON.stringify({
        candidateId: candidate.id,
        jobId: job.id,
        committeeMembers: [{ displayName: values.leadName, role: "LEAD" }],
      }),
    });
    setState({ currentCaseId: created.case.id, currentSnapshotId: null });
    location.hash = `/cases/${created.case.id}/documents`;
  }, "primary"));
  main.replaceChildren(section);
}

async function renderCase(caseId) {
  setState({ currentCaseId: caseId });
  const { case: item } = await apiFetch(`/api/v1/interview-cases/${caseId}`);
  const section = panel(`${item.candidate.fullName} — ${item.job.positionTitle}`);
  section.append(
    element("p", `Trạng thái flow: ${item.refinedFlowStatus || item.status}`, "badge"),
    element("p", "Kết quả AI chỉ hỗ trợ HĐCM, không phải quyết định tuyển dụng.", "muted"),
  );
  const actions = element("div", undefined, "actions");
  for (const [label, route] of [
    ["1. JD / CV", "documents"], ["2. Bộ câu hỏi", "questions"],
    ["3. Nhập Excel trả lời", "answers"], ["4. Đánh giá AI", "evaluation"],
  ]) actions.append(link(label, `#/cases/${caseId}/${route}`));
  section.append(actions);
  main.replaceChildren(section);
}

async function renderDocuments(caseId) {
  setState({ currentCaseId: caseId });
  const data = await apiFetch(`/api/v1/interview-cases/${caseId}/documents`);
  const section = panel("1. Import và xác nhận JD / CV", "Chỉ văn bản đã xác nhận mới được dùng cho flow.");
  for (const type of ["JD", "CV"]) {
    const current = data.items.find((item) => item.documentType === type && item.isCurrent);
    const input = field(`${type} text`, type, "textarea", current?.extractedText || "");
    section.append(input.label, button(`Lưu và xác nhận ${type}`, async () => {
      const created = await apiFetch(`/api/v1/interview-cases/${caseId}/documents`, {
        method: "POST",
        body: JSON.stringify({ documentType: type, sourceKind: "MANUAL_TEXT", text: input.input.value }),
      });
      await apiFetch(`/api/v1/interview-cases/${caseId}/documents/${created.document.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ confirmed: true, textSha256: created.document.contentSha256 }),
      });
      await renderDocuments(caseId);
    }));
  }
  section.append(link("Tiếp: 2. Bộ câu hỏi", `#/cases/${caseId}/questions`), link("Về case", `#/cases/${caseId}`));
  main.replaceChildren(section);
}

function manualQuestions() {
  const topics = ["Nền tảng chuyên môn", "Tình huống thực tế", "Kinh nghiệm trong CV", "Trade-off", "Khoảng trống bằng chứng"];
  return topics.map((topic, index) => ({
    displayOrder: index + 1,
    questionText: `${topic}: hãy trình bày một ví dụ cụ thể.`,
    competencyKey: `competency-${index + 1}`,
    sourceKind: "MANUAL",
    purpose: `Đánh giá ${topic}`,
    questionType: index === 1 ? "SCENARIO" : "LONG_TEXT",
    difficulty: "MEDIUM",
    expectedEvidence: "Bối cảnh, hành động, kết quả và lập luận",
    rubric: { score0: "Không trả lời", score1: "Rất yếu", score2: "Cơ bản", score3: "Đáp ứng", score4: "Tốt, có bằng chứng" },
    isRequired: true,
    estimatedSeconds: 150,
  }));
}

async function renderQuestions(caseId) {
  setState({ currentCaseId: caseId });
  const section = panel("2. Tạo và duyệt bộ câu hỏi", "Workbook xuất ra là format chuẩn để nhập câu trả lời.");
  let questionSet = null;
  try {
    questionSet = (await apiFetch(`/api/v1/interview-cases/${caseId}/question-set`)).questionSet;
  } catch (error) {
    if (error.status !== 404) throw error;
  }
  if (!questionSet) {
    section.append(
      button("Sinh bằng AI", async () => {
        const task = await apiFetch(`/api/v1/interview-cases/${caseId}/question-set`, {
          method: "POST", body: JSON.stringify({ operation: "GENERATE" }),
        });
        await waitForTask(task.taskId);
        await renderQuestions(caseId);
      }, "primary"),
      button("Dùng bộ câu hỏi manual", async () => {
        await apiFetch(`/api/v1/interview-cases/${caseId}/question-set`, {
          method: "POST", body: JSON.stringify({ operation: "MANUAL", questions: manualQuestions() }),
        });
        await renderQuestions(caseId);
      }),
    );
    main.replaceChildren(section);
    return;
  }
  section.append(element("p", `${questionSet.status} — version ${questionSet.versionNo}`, "badge"));
  for (const question of questionSet.questions) {
    const row = element("article", undefined, "question-card");
    row.append(element("h2", `${question.displayOrder}. ${question.questionText}`), element("p", `${question.competencyKey} · ${question.difficulty}`, "muted"));
    section.append(row);
  }
  if (questionSet.status !== "APPROVED") {
    const overview = (await apiFetch(`/api/v1/interview-cases/${caseId}`)).case;
    section.append(button("Duyệt bộ câu hỏi", async () => {
      await apiFetch(`/api/v1/interview-cases/${caseId}/question-set/approve`, {
        method: "POST",
        body: JSON.stringify({ questionSetId: questionSet.id, memberId: overview.committeeMembers[0].id, confirmation: "APPROVE_QUESTION_SET" }),
      });
      await renderQuestions(caseId);
    }, "primary"));
  }
  section.append(button("Xuất Excel câu hỏi", async () => {
    const downloaded = await apiDownload(`/api/v1/interview-cases/${caseId}/question-set/export`, { method: "POST" });
    saveDownload(downloaded.blob, downloaded.response.headers.get("Content-Disposition") || "question-answer.xlsx");
    location.hash = `/cases/${caseId}/answers`;
  }, "primary"));
  main.replaceChildren(section);
}

function saveDownload(blob, contentDisposition) {
  const match = /filename="?([^";]+)"?/i.exec(contentDisposition);
  const filename = match ? match[1] : "question-answer.xlsx";
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.textContent = "Tải workbook";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

async function renderAnswers(caseId) {
  setState({ currentCaseId: caseId });
  let snapshot = null;
  try {
    snapshot = (await apiFetch(`/api/v1/interview-cases/${caseId}/assessment-snapshots/current`)).snapshot;
    setState({ currentSnapshotId: snapshot.id });
  } catch (error) {
    if (error.status !== 404) throw error;
  }
  const section = panel("3. Nhập Excel Question + Answer", "Chỉ nhận workbook .xlsx đã xuất từ bước trước.");
  if (snapshot) section.append(element("p", `Snapshot ${snapshot.id} — ${snapshot.refinedFlowStatus}`, "badge"));
  const file = document.createElement("input");
  file.type = "file";
  file.accept = ".xlsx";
  file.name = "question-answer-workbook";
  const choose = element("label", "Workbook câu hỏi và câu trả lời");
  choose.append(file);
  section.append(choose);
  section.append(button("Import workbook", async () => {
    const workbook = file.files?.[0];
    if (!workbook) throw new Error("Hãy chọn file .xlsx");
    if (!workbook.name.toLowerCase().endsWith(".xlsx")) throw new Error("Chỉ hỗ trợ file .xlsx");
    if (workbook.size > MAX_WORKBOOK_BYTES) throw new Error("Workbook vượt quá 10 MB");
    const result = await apiUpload(`/api/v1/interview-cases/${caseId}/assessment-snapshots/import`, workbook);
    setState({ currentSnapshotId: result.snapshot.id });
    location.hash = `/cases/${caseId}/evaluation`;
  }, "primary"));
  section.append(link("Về bộ câu hỏi", `#/cases/${caseId}/questions`), link("Tiếp: 4. Đánh giá AI", `#/cases/${caseId}/evaluation`));
  main.replaceChildren(section);
}

function renderList(section, title, values) {
  section.append(element("h2", title));
  const list = element("ul");
  for (const value of values || []) list.append(element("li", String(value)));
  section.append(list);
}

function renderEvaluationPayload(section, payload) {
  renderList(section, "Strengths", payload.strengths);
  renderList(section, "Gaps", payload.gaps);
  renderList(section, "Conflicts", payload.conflicts);
  renderList(section, "Risks", payload.risks);
  section.append(element("p", `Confidence: ${payload.confidence}`));
  renderList(section, "Limitations", payload.limitations);
  section.append(element("h2", "Per-answer evaluations"));
  for (const item of payload.perAnswerEvaluations || []) {
    const row = element("article", undefined, "question-card");
    row.append(element("p", `${item.questionId} — ${item.assessmentStatus || "ASSESSED"}`), element("p", `Score: ${item.score === null ? "Not assessed" : item.score}`), element("p", item.evidenceSummary || ""));
    section.append(row);
  }
  section.append(element("h2", "Competency evaluations"));
  for (const item of payload.competencyEvaluations || []) section.append(element("p", `${item.competencyKey}: ${item.summary || ""}`));
}

async function renderEvaluation(caseId) {
  setState({ currentCaseId: caseId });
  const section = panel("4. Đánh giá AI", "Kết quả chỉ hỗ trợ HĐCM; hệ thống không tự đưa ra PASS/FAIL.");
  let snapshot;
  try {
    snapshot = (await apiFetch(`/api/v1/interview-cases/${caseId}/assessment-snapshots/current`)).snapshot;
    setState({ currentSnapshotId: snapshot.id });
  } catch (error) {
    if (error.status !== 404) throw error;
  }
  if (!snapshot) {
    section.append(element("p", "Chưa có workbook đã import.", "muted"), link("Nhập workbook", `#/cases/${caseId}/answers`));
    main.replaceChildren(section);
    return;
  }
  section.append(element("p", `Snapshot: ${snapshot.id} — ${snapshot.refinedFlowStatus}`, "badge"));
  let result = null;
  try {
    result = (await apiFetch(`/api/v1/interview-cases/${caseId}/ai/evaluation`)).result;
  } catch (error) {
    if (error.status !== 404) throw error;
  }
  if (result && result.assessmentSnapshotId !== snapshot.id) result = null;
  if (!result || snapshot.refinedFlowStatus === "ANSWERS_IMPORTED" || snapshot.refinedFlowStatus === "AI_ANALYSIS_FAILED") {
    section.append(button("Bắt đầu đánh giá bằng AI", async () => {
      const task = await apiFetch(`/api/v1/interview-cases/${caseId}/ai/evaluate`, {
        method: "POST", body: JSON.stringify({ snapshotId: snapshot.id }),
      });
      const completed = await waitForTask(task.taskId);
      if (completed.task.status !== "COMPLETED") throw new Error("AI evaluation thất bại; hãy dùng manual review.");
      await renderEvaluation(caseId);
    }, "primary"));
  }
  if (result) {
    section.append(element("p", `Result v${result.versionNo} · ${result.payload.schemaVersion}`, "badge"));
    renderEvaluationPayload(section, result.payload);
  }
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
