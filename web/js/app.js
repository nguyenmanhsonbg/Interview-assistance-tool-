import { apiDownload, apiFetch, apiUpload } from "./api.js";
import { currentRoute, registerRoute, startRouter } from "./router.js";
import { clearSensitiveState, getState, setState } from "./store.js";

const appRoot = document.querySelector("#app");
const skipLink = document.querySelector(".skip-link");
skipLink?.addEventListener("click", (event) => {
  event.preventDefault();
  document.querySelector("#main-content")?.focus();
});
const MAX_HTML_PACKAGE_BYTES = 10 * 1024 * 1024;
const HTML_PACKAGE_FORMAT = "candidate-html.v1";
const MAX_DOCUMENT_BYTES = 7_500_000;
const taskPollers = new Map();
let routerStarted = false;
let renderRevision = 0;
let errorSequence = 0;

const WORKFLOW_LABELS = {
  DRAFT: "Chuẩn bị tài liệu",
  DOCUMENT_PARSE_FAILED: "Cần xử lý tài liệu",
  DOCUMENTS_READY: "Tài liệu sẵn sàng",
  QUESTIONS_GENERATING: "Đang sinh câu hỏi",
  QUESTION_GENERATION_FAILED: "Sinh câu hỏi thất bại",
  QUESTIONS_GENERATED: "Bộ câu hỏi đã tạo",
  QUESTIONS_APPROVED: "Bộ câu hỏi đã duyệt",
  QUESTIONS_EXPORTED: "Chờ nhập câu trả lời",
  ANSWERS_IMPORTED: "Đã nhập câu trả lời",
  AI_ANALYZING: "Đang đánh giá AI",
  AI_ANALYSIS_FAILED: "Đánh giá AI thất bại",
  AI_EVALUATED: "AI đã đánh giá",
};

const STEP_DEFINITIONS = [
  { key: "documents", label: "JD & CV", short: "Tài liệu" },
  { key: "questions", label: "Bộ câu hỏi", short: "Câu hỏi" },
  { key: "answers", label: "Câu trả lời", short: "Trả lời" },
  { key: "ai", label: "Đánh giá AI", short: "AI" },
];

const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
};

function link(label, href, className = "") {
  const node = element("a", label, className);
  node.href = href;
  return node;
}

function button(label, action, className = "") {
  const node = element("button", label, className);
  node.type = "button";
  node.addEventListener("click", async () => {
    if (node.disabled) return;
    node.disabled = true;
    try {
      await action();
    } catch (error) {
      showError(error);
    } finally {
      node.disabled = false;
    }
  });
  return node;
}

function field(labelText, name, options = {}) {
  const { type = "text", value = "", required = false, placeholder = "" } = options;
  const label = element("label", labelText);
  const input = element(type === "textarea" ? "textarea" : "input");
  if (type !== "textarea") input.type = type;
  input.name = name;
  input.value = value ?? "";
  input.placeholder = placeholder;
  input.required = required;
  label.append(input);
  return { label, input };
}

function selectField(labelText, name, options, value = "") {
  const label = element("label", labelText);
  const select = element("select");
  select.name = name;
  for (const option of options) {
    const node = element("option", option.label, undefined);
    node.value = option.value;
    node.selected = option.value === value;
    select.append(node);
  }
  label.append(select);
  return { label, input: select };
}

function formSubmit(form, action) {
  let submitting = false;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    const controls = [...form.querySelectorAll("button, input, select, textarea")];
    const disabled = controls.map((control) => control.disabled);
    controls.forEach((control) => { control.disabled = true; });
    try {
      await action();
    } catch (error) {
      showError(error);
    } finally {
      submitting = false;
      controls.forEach((control, index) => { control.disabled = disabled[index]; });
    }
  });
}

function mainElement() {
  return document.querySelector("#main-content");
}

function safeText(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "—";
  const minutes = Math.floor(value / 60);
  const remainder = value % 60;
  return remainder ? minutes + " phút " + remainder + " giây" : minutes + " phút";
}

function formatConfidence(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number * 100) + "%" : "Chưa cung cấp";
}

function workflowLabel(status) {
  return WORKFLOW_LABELS[status] || safeText(status, "Chưa xác định");
}

function statusTone(status) {
  if (["AI_EVALUATED", "QUESTIONS_APPROVED", "DOCUMENTS_READY"].includes(status)) return "success";
  if (["QUESTIONS_GENERATING", "AI_ANALYZING", "QUESTIONS_EXPORTED"].includes(status)) return "warning";
  if (["DOCUMENT_PARSE_FAILED", "QUESTION_GENERATION_FAILED", "AI_ANALYSIS_FAILED"].includes(status)) return "danger";
  return "";
}

function statusBadge(status) {
  return element("span", workflowLabel(status), "badge " + statusTone(status));
}

function showError(error, host = mainElement()) {
  const message = element(
    "div",
    (error?.code || "ERROR") + ": " + (error?.message || "Không thể hoàn tất yêu cầu"),
    "notice error",
  );
  const errorId = "ui-error-" + (++errorSequence);
  message.id = errorId;
  message.setAttribute("role", "alert");
  if (host) {
    host.setAttribute("aria-describedby", errorId);
    host.prepend(message);
  }
  else appRoot.replaceChildren(message);
}

function renderAppShell(activeHref = "") {
  const shell = element("div", undefined, "workspace-shell");
  const sidebar = element("aside", undefined, "sidebar");
  const brand = link("ClawCV", "#/cases", "brand");
  brand.append(element("span", "Interview Assistant", "brand-subtitle"));
  sidebar.append(brand);

  const nav = element("nav", undefined, "sidebar-nav");
  nav.setAttribute("aria-label", "Điều hướng chính");
  for (const item of [
    ["Hồ sơ phỏng vấn", "#/cases"],
    ["Cấu hình", "#/settings"],
    ["Sao lưu", "#/backups"],
  ]) {
    const itemLink = link(item[0], item[1]);
    if (activeHref === item[1] || (item[1] === "#/cases" && activeHref.startsWith("#/cases"))) {
      itemLink.className = "active";
      itemLink.setAttribute("aria-current", "page");
    }
    nav.append(itemLink);
  }
  sidebar.append(nav);

  const footer = element("div", undefined, "sidebar-footer");
  footer.append(element("span", "Phiên HĐCM đang mở", "session-state"));
  footer.append(button("Khóa phiên", lockCommittee, "danger"));
  sidebar.append(footer);

  const workspaceMain = element("div", undefined, "workspace-main");
  const topbar = element("header", undefined, "topbar");
  const breadcrumb = element("nav", undefined, "breadcrumb");
  breadcrumb.setAttribute("aria-label", "Breadcrumb");
  breadcrumb.append(element("strong", activeHref.startsWith("#/cases/") ? "Hồ sơ phỏng vấn" : activeHref === "#/cases" ? "Hồ sơ phỏng vấn" : activeHref === "#/settings" ? "Cấu hình" : "Sao lưu"));
  topbar.append(breadcrumb);
  const connection = element("span", undefined, "connection-state");
  connection.append(element("span", undefined, "connection-dot"), element("span", "Local service"));
  topbar.append(connection);
  workspaceMain.append(topbar);
  const main = element("main", undefined, "workspace-content");
  main.id = "main-content";
  main.tabIndex = -1;
  main.setAttribute("aria-live", "polite");
  workspaceMain.append(main);
  shell.append(sidebar, workspaceMain);
  appRoot.replaceChildren(shell);
  return main;
}

function renderAuthentication(pinConfigured) {
  const shell = element("main", undefined, "auth-shell");
  shell.id = "main-content";
  shell.tabIndex = -1;
  const card = element("section", undefined, "auth-card stack");
  card.append(element("span", "ClawCV", "brand-name"));
  card.append(element("h1", pinConfigured ? "Mở Committee Mode" : "Thiết lập Committee PIN"));
  card.append(element("p", "Phiên làm việc chỉ chạy trên máy local và không lưu PIN trong trình duyệt.", "muted"));
  const form = element("form", undefined, "stack");
  const pin = field("Committee PIN", "pin", { type: "password", required: true, placeholder: "Nhập PIN" });
  const submit = element("button", pinConfigured ? "Đăng nhập" : "Lưu PIN", "primary");
  submit.type = "submit";
  form.append(pin.label, submit);
  card.append(form);
  shell.append(card);
  appRoot.replaceChildren(shell);
  pin.input.focus();
  formSubmit(form, async () => {
    if (pinConfigured) {
      const result = await apiFetch("/api/v1/auth/committee-session", {
        method: "POST",
        body: JSON.stringify({ pin: pin.input.value }),
      });
      setState({ committeeSession: result.committeeSession, mode: "COMMITTEE" });
      launchCommittee();
    } else {
      await apiFetch("/api/v1/auth/committee-pin", {
        method: "POST",
        body: JSON.stringify({ pin: pin.input.value }),
      });
      renderAuthentication(true);
    }
  });
}

async function lockCommittee() {
  try {
    await apiFetch("/api/v1/auth/lock", { method: "POST", body: JSON.stringify({}) });
  } finally {
    renderRevision += 1;
    clearSensitiveState();
    renderAuthentication(true);
  }
}

function launchCommittee() {
  if (!routerStarted) {
    registerRoute("/cases", () => renderCases());
    registerRoute("/cases/new", () => renderNewCase());
    registerRoute("/cases/:caseId", ({ caseId }) => renderCase(caseId));
    registerRoute("/cases/:caseId/documents", ({ caseId }) => renderDocuments(caseId));
    registerRoute("/cases/:caseId/questions", ({ caseId }) => renderQuestions(caseId));
    registerRoute("/cases/:caseId/answers", ({ caseId }) => renderAnswers(caseId));
    registerRoute("/cases/:caseId/ai", ({ caseId }) => renderAI(caseId));
    registerRoute("/cases/:caseId/evaluation", ({ caseId }) => {
      location.hash = "/cases/" + encodeURIComponent(caseId) + "/ai";
    });
    registerRoute("/settings", () => renderSettings());
    registerRoute("/backups", () => renderBackups());
    routerStarted = true;
    startRouter((route) => renderNotFound(route));
  } else {
    location.hash = "/cases";
  }
}

function renderNotFound(route) {
  const main = renderAppShell();
  const content = element("section", undefined, "card empty-state");
  content.append(element("h1", "Không tìm thấy màn hình"), element("p", route, "muted"), link("Về danh sách hồ sơ", "#/cases", "link-button"));
  main.append(content);
}

function renderPageHeading(title, subtitle, actions = []) {
  const heading = element("div", undefined, "page-heading");
  const copy = element("div", undefined, "page-heading-copy");
  copy.append(element("h1", title));
  if (subtitle) copy.append(element("p", subtitle, "muted"));
  heading.append(copy);
  if (actions.length) {
    const actionGroup = element("div", undefined, "actions");
    actionGroup.append(...actions);
    heading.append(actionGroup);
  }
  return heading;
}

function renderLoading() {
  const card = element("section", undefined, "card stack");
  card.append(element("div", undefined, "skeleton"), element("div", undefined, "skeleton"), element("div", undefined, "skeleton"));
  return card;
}

function renderWorkspacePage(activeHref, title, subtitle, actions = []) {
  const main = renderAppShell(activeHref);
  const content = element("div", undefined, "workspace-content");
  content.append(renderPageHeading(title, subtitle, actions));
  main.replaceChildren(content);
  return { main, content };
}

function stepHref(caseId, step) {
  return "#/cases/" + encodeURIComponent(caseId) + "/" + step;
}

function isActiveCaseStep(caseId, step) {
  return Boolean(getState().committeeSession) && currentRoute() === stepHref(caseId, step).slice(1);
}

function caseStepComplete(status, key) {
  if (key === "documents") return !["DRAFT", "DOCUMENT_PARSE_FAILED"].includes(status);
  if (key === "questions") return ["QUESTIONS_GENERATED", "QUESTIONS_APPROVED", "QUESTIONS_EXPORTED", "ANSWERS_IMPORTED", "AI_ANALYZING", "AI_ANALYSIS_FAILED", "AI_EVALUATED"].includes(status);
  if (key === "answers") return ["ANSWERS_IMPORTED", "AI_ANALYZING", "AI_ANALYSIS_FAILED", "AI_EVALUATED"].includes(status);
  return status === "AI_EVALUATED";
}

function jobLevelLabel(job) {
  if (job?.targetLevelStatus === "READY") return safeText(job.targetLevel, "Đã xác định từ JD");
  if (job?.targetLevelStatus === "EXTRACTING") return "Đang xác định level từ JD";
  if (job?.targetLevelStatus === "FAILED") return "Chưa xác định level từ JD";
  return "Level lấy từ JD";
}

function renderCaseStepper(item, activeStep, step) {
  const status = item.refinedFlowStatus || item.status;
  return {
    complete: caseStepComplete(status, step.key),
    active: activeStep === step.key,
  };
}

function renderCaseHeader(item, activeStep) {
  const header = element("section", undefined, "case-header");
  const main = element("div", undefined, "case-header-main");
  const identity = element("div", undefined, "case-identity");
  identity.append(element("h1", safeText(item.candidate?.fullName, "Ứng viên chưa có tên")));
  const meta = element("div", undefined, "case-meta");
  const lead = item.committeeMembers?.find((member) => member.role === "LEAD");
  meta.append(
    element("span", safeText(item.candidate?.candidateCode)),
    element("span", safeText(item.job?.positionTitle)),
    element("span", jobLevelLabel(item.job)),
    element("span", "Lead HĐCM: " + safeText(lead?.displayName, "Chưa có")),
  );
  identity.append(meta);
  main.append(identity, statusBadge(item.refinedFlowStatus || item.status));
  header.append(main);

  const stepper = element("nav", undefined, "case-stepper");
  stepper.setAttribute("aria-label", "Các bước hồ sơ");
  for (const [index, step] of STEP_DEFINITIONS.entries()) {
    const stepState = renderCaseStepper(item, activeStep, step);
    const complete = stepState.complete;
    const active = stepState.active;
    const stepLink = link("", stepHref(item.id, step.key), "step-link" + (active ? " active" : "") + (complete ? " complete" : ""));
    if (active) stepLink.setAttribute("aria-current", "step");
    stepLink.append(
      element("span", complete ? "✓" : String(index + 1), "step-number"),
      element("span", undefined, "step-label"),
    );
    const label = stepLink.lastElementChild;
    label.append(element("span", step.label), element("span", complete ? "Hoàn tất" : active ? "Đang mở" : "Chưa sẵn sàng", "step-state"));
    stepper.append(stepLink);
  }
  header.append(stepper);
  return header;
}

async function renderCasePage(caseId, activeStep, builder) {
  if (!getState().committeeSession) return;
  const revision = ++renderRevision;
  const main = renderAppShell(stepHref(caseId, activeStep));
  main.append(renderLoading());
  try {
    const response = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId));
    if (revision !== renderRevision) return;
    const item = response.case;
    setState({ currentCaseId: caseId });
    const content = element("div", undefined, "workspace-content");
    content.append(renderCaseHeader(item, activeStep));
    const view = await builder(item, revision);
    if (revision !== renderRevision) return;
    content.append(view);
    main.replaceChildren(content);
  } catch (error) {
    if (revision === renderRevision) showError(error, main);
  }
}

async function renderCases() {
  const revision = ++renderRevision;
  const createLink = link("Tạo hồ sơ", "#/cases/new", "primary-link");
  const page = renderWorkspacePage("#/cases", "Hồ sơ phỏng vấn", "Theo dõi flow JD/CV → câu hỏi → Excel → đánh giá AI.", [createLink]);
  const filters = element("div", undefined, "actions");
  const status = selectField("Lọc trạng thái", "status", [
    { value: "", label: "Tất cả trạng thái" },
    { value: "DRAFT", label: "Chuẩn bị tài liệu" },
    { value: "DOCUMENTS_READY", label: "Tài liệu sẵn sàng" },
    { value: "QUESTIONS_GENERATED", label: "Bộ câu hỏi đã tạo" },
    { value: "QUESTIONS_EXPORTED", label: "Chờ nhập câu trả lời" },
    { value: "ANSWERS_IMPORTED", label: "Đã nhập câu trả lời" },
    { value: "AI_EVALUATED", label: "AI đã đánh giá" },
  ]);
  const listHost = element("div");
  status.input.addEventListener("change", () => renderCasesWithStatus(status.input.value, listHost, revision).catch((error) => showError(error, listHost)));
  filters.append(status.label);
  page.content.append(filters, listHost);
  listHost.append(renderLoading());
  try {
    await renderCasesWithStatus("", listHost, revision);
  } catch (error) {
    if (revision === renderRevision) showError(error, page.main);
  }
}

async function renderCasesWithStatus(statusValue = "", host = null, revision = renderRevision) {
  const data = await apiFetch("/api/v1/interview-cases");
  if (revision !== renderRevision && host) return;
  const items = statusValue
    ? (data.items || []).filter((item) => (item.refinedFlowStatus || item.status) === statusValue)
    : (data.items || []);
  const container = element("section", undefined, "card stack");
  if (!items.length) {
    container.append(element("h2", "Chưa có hồ sơ"), element("p", "Tạo hồ sơ đầu tiên để bắt đầu import JD và CV.", "muted"), link("Tạo hồ sơ", "#/cases/new", "link-button"));
  } else {
    const wrap = element("div", undefined, "table-wrap");
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const label of ["Ứng viên", "Vị trí", "Trạng thái", "Bước tiếp theo"]) headRow.append(element("th", label));
    head.append(headRow);
    const body = document.createElement("tbody");
    for (const item of items) {
      const row = document.createElement("tr");
      const caseLink = link(safeText(item.candidate?.fullName), "#/cases/" + encodeURIComponent(item.id));
      const candidateCell = document.createElement("td");
      candidateCell.append(caseLink, element("div", safeText(item.candidate?.candidateCode), "muted"));
      const positionCell = element("td", safeText(item.job?.positionTitle));
      positionCell.append(element("div", jobLevelLabel(item.job), "muted"));
      const workflow = item.refinedFlowStatus || item.status;
      const statusCell = document.createElement("td");
      statusCell.append(statusBadge(workflow));
      const nextCell = element("td", nextStepLabel(workflow));
      row.append(candidateCell, positionCell, statusCell, nextCell);
      body.append(row);
    }
    table.append(head, body);
    wrap.append(table);
    container.append(wrap);
  }
  if (host) {
    const old = host.querySelector(".card.stack:last-child");
    if (old) old.replaceWith(container);
    else host.append(container);
  }
  return container;
}

function nextStepLabel(status) {
  if (["DRAFT", "DOCUMENT_PARSE_FAILED"].includes(status)) return "Import JD/CV";
  if (["DOCUMENTS_READY", "QUESTIONS_GENERATING", "QUESTION_GENERATION_FAILED", "QUESTIONS_GENERATED", "QUESTIONS_APPROVED"].includes(status)) return "Bộ câu hỏi";
  if (status === "QUESTIONS_EXPORTED") return "Nhập Excel";
  if (["ANSWERS_IMPORTED", "AI_ANALYZING", "AI_ANALYSIS_FAILED"].includes(status)) return "Đánh giá AI";
  return "Xem kết quả";
}

let pendingCaseCreation = null;

async function findOrCreate(url, query, key, body, resultKey) {
  const page = query ? await apiFetch(url + "?query=" + encodeURIComponent(query)) : { items: [] };
  const existing = (page.items || []).find((item) => item[key] === query);
  if (existing) return existing;
  const created = await apiFetch(url, { method: "POST", body: JSON.stringify(body) });
  return created[resultKey];
}

function generateCandidateCode() {
  const datePart = new Date().toISOString().slice(0, 10).replaceAll("-", "");
  const randomPart = globalThis.crypto?.randomUUID?.().replaceAll("-", "").slice(0, 8).toUpperCase()
    || Math.random().toString(36).slice(2, 10).toUpperCase();
  return "CAND-" + datePart + "-" + randomPart;
}

async function renderNewCase() {
  const page = renderWorkspacePage("#/cases", "Tạo hồ sơ phỏng vấn", "Tạo một hồ sơ mới trước khi import JD và CV.");
  const form = element("form", undefined, "card stack");
  const candidateCode = field("Mã ứng viên (tự sinh)", "candidateCode", { value: generateCandidateCode(), required: true });
  candidateCode.input.readOnly = true;
  const fields = [
    candidateCode,
    field("Tên ứng viên", "fullName", { required: true }),
    field("Vị trí", "positionTitle", { required: true }),
    field("Tên Lead HĐCM", "leadName", { required: true }),
  ];
  const grid = element("div", undefined, "field-grid");
  for (const item of fields) grid.append(item.label);
  form.append(grid);
  const note = element("div", "Thời lượng đánh giá mặc định: 900 giây. Có thể tiếp tục retry mà không tạo trùng Job/Candidate.", "notice");
  const actions = element("div", undefined, "actions");
  const submit = element("button", "Tạo hồ sơ", "primary");
  submit.type = "submit";
  actions.append(submit, link("Huỷ", "#/cases", "link-button"));
  form.append(note, actions);
  page.content.append(form);

  formSubmit(form, async () => {
    const values = Object.fromEntries(fields.map((item) => [item.input.name, item.input.value.trim()]));
    const draftKey = [values.candidateCode, values.positionTitle].join("|");
    const cached = pendingCaseCreation?.key === draftKey ? pendingCaseCreation : null;
    const job = cached?.job || (await apiFetch("/api/v1/jobs", {
      method: "POST",
      body: JSON.stringify({ positionTitle: values.positionTitle }),
    })).job;
    pendingCaseCreation = { key: draftKey, job };
    const candidate = cached?.candidate || await findOrCreate(
      "/api/v1/candidates",
      values.candidateCode,
      "candidateCode",
      { candidateCode: values.candidateCode, fullName: values.fullName },
      "candidate",
    );
    pendingCaseCreation = { key: draftKey, job, candidate };
    const committeeMembers = [{ displayName: values.leadName, role: "LEAD" }];
    const created = await apiFetch("/api/v1/interview-cases", {
      method: "POST",
      body: JSON.stringify({
        candidateId: candidate.id,
        jobId: job.id,
        assessmentDurationSeconds: 900,
        committeeMembers,
      }),
    });
    pendingCaseCreation = null;
    setState({ currentCaseId: created.case.id, currentSnapshotId: null });
    location.hash = "/cases/" + encodeURIComponent(created.case.id) + "/documents";
  });
}

function nextStepForCase(item) {
  const status = item.refinedFlowStatus || item.status;
  if (["DRAFT", "DOCUMENT_PARSE_FAILED"].includes(status)) return "documents";
  if (["DOCUMENTS_READY", "QUESTIONS_GENERATING", "QUESTION_GENERATION_FAILED", "QUESTIONS_GENERATED", "QUESTIONS_APPROVED"].includes(status)) return "questions";
  if (status === "QUESTIONS_EXPORTED") return "answers";
  return "ai";
}

async function renderCase(caseId) {
  const revision = ++renderRevision;
  const main = renderAppShell();
  main.append(renderLoading());
  try {
    const response = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId));
    if (revision !== renderRevision) return;
    location.hash = stepHref(caseId, nextStepForCase(response.case)).slice(1);
  } catch (error) {
    showError(error, main);
  }
}

async function fileToBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function mimeForFile(file) {
  const extension = file.name.toLowerCase().split(".").pop();
  if (extension === "pdf") return "application/pdf";
  if (extension === "docx") return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  if (extension === "md" || extension === "markdown") return file.type || "text/markdown";
  return file.type || "text/plain";
}

function openDocumentEditor(caseId, title, type, text) {
  const opener = document.activeElement;
  const backdrop = element("div", undefined, "modal-backdrop");
  const modal = element("section", undefined, "modal");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");

  const titleId = "document-modal-title";
  const editorId = "document-editor-text";
  const heading = element("h2", title + " — Chỉnh sửa");
  heading.id = titleId;
  const description = element("p", "Cập nhật nội dung và lưu để tạo phiên bản tài liệu mới.", "muted");
  const editor = field("Nội dung " + type, editorId, { type: "textarea", value: text || "" });
  editor.input.id = editorId;
  editor.input.className = "document-editor-text";
  modal.setAttribute("aria-labelledby", titleId);
  description.id = "document-modal-description";
  modal.setAttribute("aria-describedby", description.id);

  let keydownHandler;
  const closeModal = () => {
    document.removeEventListener("keydown", keydownHandler);
    backdrop.remove();
    opener?.focus?.();
  };
  keydownHandler = (event) => {
    if (event.key === "Escape") closeModal();
  };
  const close = element("button", "Đóng", "secondary");
  close.type = "button";
  close.addEventListener("click", closeModal);
  const save = button("Lưu text và xác nhận", async () => {
    const created = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/documents", {
      method: "POST",
      body: JSON.stringify({ documentType: type, sourceKind: "MANUAL_TEXT", text: editor.input.value }),
    });
    await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/documents/" + encodeURIComponent(created.document.id) + "/confirm", {
      method: "POST",
      body: JSON.stringify({ confirmed: true, textSha256: created.document.contentSha256 }),
    });
    closeModal();
    await renderDocuments(caseId);
  }, "primary");
  const actions = element("div", undefined, "actions document-actions");
  actions.append(close, save);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  modal.append(heading, description, editor.label, actions);
  backdrop.append(modal);
  document.addEventListener("keydown", keydownHandler);
  document.body.append(backdrop);
  editor.input.focus();
}

function renderTextFileImport(caseId, type) {
  const file = field("Import file TXT, MD hoặc DOCX", type + "-file", { type: "file" });
  file.input.accept = ".txt,.md,.markdown,.docx";
  const importFile = button("Import file " + type, async () => {
    const selected = file.input.files?.[0];
    if (!selected) throw new Error("Hãy chọn file " + type);
    if (selected.size > MAX_DOCUMENT_BYTES) throw new Error("File vượt quá 7.5 MB");
    const extension = selected.name.toLowerCase().split(".").pop();
    if (!["txt", "md", "markdown", "docx"].includes(extension)) throw new Error("Định dạng file không được hỗ trợ");
    const created = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/documents", {
      method: "POST",
      body: JSON.stringify({
        documentType: type,
        sourceKind: "IMPORTED_FILE",
        originalFilename: selected.name,
        mimeType: mimeForFile(selected),
        contentBase64: await fileToBase64(selected),
      }),
    });
    if (created.document.extractionStatus !== "SUCCEEDED") throw new Error("Không thể trích xuất nội dung file");
    await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/documents/" + encodeURIComponent(created.document.id) + "/confirm", {
      method: "POST",
      body: JSON.stringify({ confirmed: true, textSha256: created.document.contentSha256 }),
    });
    await renderDocuments(caseId);
  });
  return [file.label, importFile];
}

function buildDocumentCard(caseId, type, current) {
  const card = element("section", undefined, "card stack");
  const title = type === "JD" ? "Job Description" : "Curriculum Vitae";
  card.append(element("h2", title), element("p", type === "JD" ? "Nguồn yêu cầu của vị trí." : "Nguồn kinh nghiệm và bằng chứng của ứng viên.", "muted"));
  const fullText = current?.extractedText || "";
  if (current) {
    const meta = element("div", undefined, "actions");
    meta.append(element("span", "Version " + current.versionNo, "badge"), statusBadge(current.extractionStatus));
    if (current.isAiEligible) meta.append(element("span", "Đã xác nhận", "badge success"));
    card.append(meta);
  } else {
    card.append(element("p", "Chưa có tài liệu hiện hành. Bạn có thể nhập nội dung trong popup.", "muted"));
  }
  const previewText = fullText.length > 600 ? fullText.slice(0, 600).trimEnd() + "…" : fullText;
  const preview = element("button", previewText || "Nhập nội dung " + type, "document-preview");
  preview.type = "button";
  preview.setAttribute("aria-label", "Mở popup chỉnh sửa nội dung " + type);
  preview.addEventListener("click", () => openDocumentEditor(caseId, title, type, fullText));
  card.append(preview);

  if (type === "JD") {
    card.append(...renderTextFileImport(caseId, type));
  }

  if (type === "CV") {
    const pdf = field("Import CV PDF", "cvPdf", { type: "file" });
    pdf.input.accept = ".pdf,application/pdf";
    const importPdf = button("Đọc và import CV PDF", async () => {
      const file = pdf.input.files?.[0];
      if (!file) throw new Error("Hãy chọn file CV PDF");
      if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && file.type !== "application/pdf")) {
        throw new Error("Chỉ hỗ trợ file PDF");
      }
      if (file.size > MAX_DOCUMENT_BYTES) throw new Error("CV vượt quá 7.5 MB");
      const created = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/documents", {
        method: "POST",
        body: JSON.stringify({
          documentType: "CV",
          sourceKind: "IMPORTED_FILE",
          originalFilename: file.name,
          mimeType: "application/pdf",
          contentBase64: await fileToBase64(file),
        }),
      });
      if (created.document.extractionStatus !== "SUCCEEDED" || !created.document.isAiEligible) {
        throw new Error("Không đọc được nội dung CV PDF. Hãy nhập text CV thủ công.");
      }
      await renderDocuments(caseId);
    });
    card.append(pdf.label, importPdf);
  }
  return card;
}

function renderJobLevelStatus(caseId, item) {
  const job = item.job || {};
  const status = job.targetLevelStatus || "PENDING";
  const panel = element("section", undefined, "job-level-status notice stack");
  const heading = element("div", undefined, "actions");
  heading.append(element("strong", "Level từ JD"));

  if (status === "READY") {
    heading.append(element("span", safeText(job.targetLevel), "badge success"));
    if (job.targetLevelConfidence !== null && job.targetLevelConfidence !== undefined) {
      heading.append(element("span", "Độ tin cậy " + formatConfidence(job.targetLevelConfidence), "badge"));
    }
    panel.append(heading, element("p", "Level được lấy từ nội dung JD đã xác nhận.", "muted"));
    return panel;
  }

  if (status === "EXTRACTING") {
    heading.append(element("span", "Đang xác định level từ JD", "badge warning"));
    panel.append(heading, element("p", "AI đang đọc JD để xác định level. Có thể tiếp tục theo dõi tại đây.", "muted"));
    const taskHost = element("div", undefined, "stack");
    panel.append(taskHost);
    if (item.activeTaskId) {
      resumeTask(caseId, "documents", item.activeTaskId, taskHost, () => renderDocuments(caseId), "AI đang xác định level từ JD");
    }
    return panel;
  }

  if (status === "FAILED") {
    heading.append(element("span", "Xác định level từ JD thất bại", "badge danger"));
    const retry = button("Thử lại xác định level", async () => {
      await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/job-level/extract", {
        method: "POST",
        body: JSON.stringify({ retry: true }),
      });
      await renderDocuments(caseId);
    }, "secondary");
    panel.append(heading, element("p", "Không thể xác định level từ JD hiện tại. Hãy kiểm tra nội dung JD rồi thử lại.", "muted"), retry);
    return panel;
  }

  panel.append(heading, element("p", "Level sẽ được lấy từ JD sau khi JD được xác nhận.", "muted"));
  return panel;
}

async function renderDocuments(caseId) {
  await renderCasePage(caseId, "documents", async (item) => {
    const data = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/documents");
    const current = (type) => data.items?.find((document) => document.documentType === type && document.isCurrent);
    const view = element("div", undefined, "stack");
    view.append(element("div", "Chỉ tài liệu hiện hành đã xác nhận mới được dùng để sinh câu hỏi.", "notice"));
    view.append(renderJobLevelStatus(caseId, item));
    const grid = element("div", undefined, "content-grid");
    grid.append(buildDocumentCard(caseId, "JD", current("JD")), buildDocumentCard(caseId, "CV", current("CV")));
    view.append(grid);
    const ready = Boolean(current("JD")?.isAiEligible && current("CV")?.isAiEligible);
    const actions = element("div", undefined, "actions");
    const next = link("Tiếp: Bộ câu hỏi", stepHref(caseId, "questions"), "primary-link");
    next.setAttribute("aria-disabled", ready ? "false" : "true");
    next.addEventListener("click", (event) => {
      if (!ready) event.preventDefault();
    });
    actions.append(next);
    if (!ready) actions.append(element("span", "Cần xác nhận đủ JD và CV trước khi sinh câu hỏi.", "muted"));
    view.append(actions);
    return view;
  });
}

function taskPhaseLabel(phase) {
  return {
    EVIDENCE_ANALYSIS: "AI đang phân tích bằng chứng",
    EVALUATION_SYNTHESIS: "AI đang tổng hợp đánh giá",
  }[phase] || null;
}

function taskStatusLabel(status, phase) {
  return taskPhaseLabel(phase) || {
    PENDING: "Đang chờ AI bắt đầu xử lý",
    RUNNING: "AI đang xử lý",
    PENDING_RETRY: "AI đang chờ thử lại",
    COMPLETED: "Đã hoàn tất",
    FAILED: "Tác vụ thất bại",
  }[status] || "Đang kiểm tra trạng thái";
}

function createTaskProgress(label) {
  const panel = element("section", undefined, "task-progress notice");
  const heading = element("div", label, "task-progress-heading");
  const status = element("span", "Đang kiểm tra trạng thái", "task-progress-status");
  status.setAttribute("aria-live", "polite");
  heading.append(status);

  const track = element("div", undefined, "task-progress-track");
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-label", "Tiến trình " + label);
  track.setAttribute("aria-valuetext", "Đang kiểm tra trạng thái");
  track.append(element("div", undefined, "task-progress-bar"));

  panel.append(
    heading,
    track,
    element("p", "Hệ thống đang xử lý. Không tạo lại tác vụ trong lúc này.", "muted"),
  );
  return {
    panel,
    update(task) {
      const text = taskStatusLabel(task.status, task.phase);
      status.textContent = text;
      track.setAttribute("aria-valuetext", text);
    },
  };
}

async function waitForTask(taskId, host, label = "Tác vụ AI") {
  if (taskPollers.has(taskId)) return taskPollers.get(taskId);
  const promise = (async () => {
    if (!getState().committeeSession) return null;
    const progress = createTaskProgress(label);
    if (host?.isConnected) host.append(progress.panel);
    for (let attempt = 0; attempt < 150; attempt += 1) {
      if (!getState().committeeSession) return null;
      const result = await apiFetch("/api/v1/tasks/" + encodeURIComponent(taskId));
      const task = result.task;
      progress.update(task);
      if (task.status === "COMPLETED") return result;
      if (task.status === "FAILED") throw new Error(task.errorCode || "Tác vụ AI thất bại");
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error("Tác vụ AI quá thời gian chờ; hãy mở lại màn hình để kiểm tra trạng thái");
  })().finally(() => taskPollers.delete(taskId));
  taskPollers.set(taskId, promise);
  return promise;
}

function resumeTask(caseId, step, taskId, host, refresh, label = "Tác vụ AI", onCompleted = null, onFailed = null) {
  window.setTimeout(() => {
    waitForTask(taskId, host, label)
      .then((result) => {
        if (result && onCompleted) onCompleted(result);
        if (result && isActiveCaseStep(caseId, step)) return refresh();
        return null;
      })
      .catch(async (error) => {
        if (!isActiveCaseStep(caseId, step)) return;
        if (onFailed) {
          await onFailed(error);
          return;
        }
        showError(error, host);
      });
  }, 0);
}

function categoryLabel(value) {
  return { FOUNDATION: "Nền tảng", APPLICATION: "Ứng dụng", DEEP_DIVE: "Chuyên sâu" }[value] || safeText(value);
}

function questionGroups(questions) {
  const order = ["FOUNDATION", "APPLICATION", "DEEP_DIVE"];
  const groups = order.map((key) => ({
    key,
    label: categoryLabel(key),
    items: questions.filter((question) => question.questionCategory === key),
  }));
  for (const question of questions) {
    if (!order.includes(question.questionCategory)) {
      const existing = groups.find((group) => group.key === question.questionCategory);
      if (existing) existing.items.push(question);
      else groups.push({ key: question.questionCategory, label: categoryLabel(question.questionCategory), items: [question] });
    }
  }
  return groups;
}

function renderRubric(rubric) {
  const details = document.createElement("details");
  details.className = "rubric";
  const summary = element("summary", "Tiêu chí đánh giá");
  const list = element("div", undefined, "rubric-list");
  for (const score of ["score0", "score1", "score2", "score3", "score4"]) {
    const row = element("div", undefined, "detail-row");
    row.append(element("span", score.replace("score", "Mức "), "detail-label"), element("span", safeText(rubric?.[score])));
    list.append(row);
  }
  details.append(summary, list);
  return details;
}

const QUESTION_VARIANT_OPERATION = "GENERATE_QUESTION_VARIANT";
const QUESTION_VARIANT_SCHEMA = "question-variant.v1";
const MAX_VARIANT_PROMPT_CHARS = 2000;
const QUESTION_ADDITION_OPERATION = "GENERATE_QUESTION_ADDITION";
const QUESTION_ADDITION_SCHEMA = "question-addition.v1";
const MAX_ADDITION_PROMPT_CHARS = 2000;

function questionAdditionPath(caseId, proposalId = "") {
  const base = "/api/v1/interview-cases/" + encodeURIComponent(caseId)
    + "/question-set/question-additions";
  return proposalId ? base + "/" + encodeURIComponent(proposalId) : base;
}

function activeQuestionAddition(caseId, questionSetId, groupKey) {
  const addition = getState().activeQuestionAddition;
  return addition?.caseId === caseId
    && addition.questionSetId === questionSetId
    && addition.groupKey === groupKey
    ? addition
    : null;
}

function clearActiveQuestionAddition(caseId, questionSetId, groupKey) {
  if (activeQuestionAddition(caseId, questionSetId, groupKey)) {
    setState({ activeQuestionAddition: null });
  }
}

async function requestQuestionAddition(caseId, questionSetId, groupKey, mode, prompt) {
  const current = activeQuestionAddition(caseId, questionSetId, groupKey);
  if (current) return { taskId: current.taskId, status: "DUPLICATE_IGNORED" };
  const task = await apiFetch(questionAdditionPath(caseId), {
    method: "POST",
    body: JSON.stringify({
      questionSetId,
      questionCategory: groupKey,
      mode,
      ...(prompt ? { prompt } : {}),
    }),
  });
  setState({
    activeQuestionAddition: {
      caseId,
      questionSetId,
      groupKey,
      taskId: task.taskId,
      proposalId: null,
      mode,
    },
  });
  return task;
}

async function restoreActiveQuestionAdditionTask(caseId, questionSet, taskId) {
  if (!taskId) return;
  const current = getState().activeQuestionAddition;
  if (current?.taskId === taskId) return;
  const result = await apiFetch("/api/v1/tasks/" + encodeURIComponent(taskId));
  const task = result.task;
  if (task.taskType !== QUESTION_ADDITION_OPERATION || !task.targetQuestionCategory) return;
  if (!["PENDING", "RUNNING", "PENDING_RETRY"].includes(task.status)) return;
  setState({
    activeQuestionAddition: {
      caseId,
      questionSetId: questionSet.id,
      groupKey: task.targetQuestionCategory,
      taskId,
      proposalId: null,
      mode: null,
    },
  });
}

function openQuestionAdditionChoice(groupKey, handlers = {}) {
  const opener = document.activeElement;
  const backdrop = element("div", undefined, "modal-backdrop question-addition-choice");
  const modal = element("section", undefined, "modal");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  const heading = element("h2", "Thêm câu hỏi · " + categoryLabel(groupKey));
  const description = element("p", "Chọn cách tạo proposal cho group hiện tại.", "muted");
  const closeModal = () => {
    document.removeEventListener("keydown", keydownHandler);
    backdrop.remove();
    opener?.focus?.();
    handlers.onClose?.();
  };
  const keydownHandler = (event) => {
    if (event.key === "Escape") closeModal();
  };
  const prompt = button("Gen theo prompt", () => {
    closeModal();
    handlers.onPrompt?.();
  }, "primary");
  const automatic = button("Tự động gen", () => {
    closeModal();
    return handlers.onAuto?.();
  }, "secondary");
  const cancel = button("Hủy", closeModal, "secondary");
  const actions = element("div", undefined, "actions");
  actions.append(prompt, automatic, cancel);
  modal.append(heading, description, actions);
  backdrop.append(modal);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  document.addEventListener("keydown", keydownHandler);
  document.body.append(backdrop);
  prompt.focus();
}

function openQuestionAdditionPrompt(groupKey, handlers = {}) {
  const opener = document.activeElement;
  const backdrop = element("div", undefined, "modal-backdrop question-addition-prompt");
  const modal = element("section", undefined, "modal question-prompt-modal");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  const heading = element("h2", "Gen câu hỏi theo prompt · " + categoryLabel(groupKey));
  const description = element("p", "Prompt là yêu cầu bổ sung cho AI; group và quyền duyệt vẫn do HĐCM kiểm soát.", "muted");
  const prompt = field("Yêu cầu bổ sung", "question-addition-prompt", {
    type: "textarea",
    required: true,
    placeholder: "Ví dụ: Tìm thêm bằng chứng về cách xử lý incident...",
  });
  prompt.input.maxLength = MAX_ADDITION_PROMPT_CHARS;
  const counter = element("p", "0/" + MAX_ADDITION_PROMPT_CHARS + " ký tự", "muted");
  const validation = element("p", "", "notice error");
  validation.hidden = true;
  prompt.input.addEventListener("input", () => {
    counter.textContent = prompt.input.value.length + "/" + MAX_ADDITION_PROMPT_CHARS + " ký tự";
    validation.hidden = true;
  });
  let keydownHandler;
  const closeModal = () => {
    document.removeEventListener("keydown", keydownHandler);
    backdrop.remove();
    opener?.focus?.();
    handlers.onClose?.();
  };
  keydownHandler = (event) => {
    if (event.key === "Escape") closeModal();
  };
  const close = button("Hủy", closeModal, "secondary");
  const submit = element("button", "Gen theo prompt", "primary");
  submit.type = "submit";
  const form = element("form", undefined, "stack");
  form.append(prompt.label, counter, validation);
  const actions = element("div", undefined, "actions document-actions");
  actions.append(close, submit);
  form.append(actions);
  formSubmit(form, async () => {
    const value = prompt.input.value.trim();
    if (!value || value.length > MAX_ADDITION_PROMPT_CHARS) {
      validation.textContent = !value
        ? "Hãy nhập prompt trước khi tạo câu hỏi."
        : "Prompt không được vượt quá " + MAX_ADDITION_PROMPT_CHARS + " ký tự.";
      validation.hidden = false;
      prompt.input.focus();
      return;
    }
    closeModal();
    await handlers.onSubmit?.(value);
  });
  modal.append(heading, description, form);
  backdrop.append(modal);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  document.addEventListener("keydown", keydownHandler);
  document.body.append(backdrop);
  prompt.input.focus();
}

function renderQuestionAdditionFields(question) {
  const fields = element("div", undefined, "question-addition-fields");
  for (const [label, value] of [
    ["Mục đích", question?.purpose],
    ["Mục tiêu bước tiếp theo", question?.nextStepObjective],
    ["Bằng chứng cần tìm", question?.expectedEvidence],
  ]) {
    const row = element("div", undefined, "detail-row");
    row.append(element("span", label, "detail-label"), element("span", safeText(value)));
    fields.append(row);
  }
  return fields;
}

function openQuestionAdditionDetails(proposal, questionSet, caseId, onRefresh) {
  if (proposal.status !== "PROPOSED") return;
  const opener = document.activeElement;
  const backdrop = element("div", undefined, "modal-backdrop question-addition-detail");
  const modal = element("section", undefined, "modal question-addition-detail-modal");
  const errorHost = modal;
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  const closeModal = () => {
    document.removeEventListener("keydown", keydownHandler);
    backdrop.remove();
    opener?.focus?.();
  };
  const keydownHandler = (event) => {
    if (event.key === "Escape") closeModal();
  };
  const card = element("section", undefined, "card stack question-addition-proposal");
  const heading = element("div", undefined, "question-addition-status");
  heading.append(element("h3", "Câu hỏi mới đề xuất"), element("span", safeText(proposal.status), "badge warning"));
  const question = proposal.question || {};
  const meta = element("div", undefined, "actions");
  meta.append(
    element("span", categoryLabel(proposal.targetCategory), "badge"),
    element("span", safeText(question.sourceKind), "badge"),
    element("span", safeText(question.questionType), "badge"),
    element("span", safeText(question.difficulty), "badge"),
  );
  const suggested = element("div", undefined, "stack");
  suggested.append(element("strong", "Câu hỏi đề xuất"), element("div", safeText(question.questionText), "answer-text"));
  const questionInfo = element("section", undefined, "stack question-addition-question");
  questionInfo.append(suggested, renderQuestionAdditionFields(question));
  const rubric = renderRubric(question.rubric || {});
  rubric.classList.add("question-addition-rubric");
  rubric.open = false;
  const columns = element("div", undefined, "question-addition-columns");
  columns.append(questionInfo, rubric);
  const actions = element("div", undefined, "actions question-addition-actions");
  const apply = button("Dùng câu hỏi này", async () => {
    try {
      await apiFetch(questionAdditionPath(caseId, proposal.proposalId) + "/apply", {
        method: "POST",
        body: JSON.stringify({
          questionSetId: questionSet.id,
          expectedQuestionSetUpdatedAt: questionSet.updatedAt,
          expectedSourceFingerprint: proposal.sourceFingerprint,
        }),
      });
      clearActiveQuestionAddition(caseId, questionSet.id, proposal.targetCategory);
      await onRefresh();
      closeModal();
    } catch (error) {
      await onRefresh();
      if (["STATE_CONFLICT", "QUESTION_SET_STALE"].includes(error.code)) {
        showError({ code: error.code, message: "Question Set đã thay đổi. Hãy tải lại trước khi áp dụng đề xuất." }, errorHost);
        return;
      }
      throw error;
    }
  }, "primary");
  const regenerate = button("Tạo lại", async () => {
    await apiFetch(questionAdditionPath(caseId, proposal.proposalId) + "/discard", { method: "POST" });
    clearActiveQuestionAddition(caseId, questionSet.id, proposal.targetCategory);
    closeModal();
    if (proposal.mode === "USER_PROMPT") {
      openQuestionAdditionPrompt(proposal.targetCategory, {
        onSubmit: async (prompt) => {
          await requestQuestionAddition(caseId, questionSet.id, proposal.targetCategory, "USER_PROMPT", prompt);
          await onRefresh();
        },
      });
      return;
    }
    await requestQuestionAddition(caseId, questionSet.id, proposal.targetCategory, "AUTO_GROUP", null);
    await onRefresh();
  }, "secondary");
  const discard = button("Bỏ qua", async () => {
    await apiFetch(questionAdditionPath(caseId, proposal.proposalId) + "/discard", { method: "POST" });
    clearActiveQuestionAddition(caseId, questionSet.id, proposal.targetCategory);
    closeModal();
    await onRefresh();
  }, "secondary");
  actions.append(apply, regenerate, discard);
  card.append(heading, meta, columns, actions);
  modal.append(card);
  backdrop.append(modal);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  document.addEventListener("keydown", keydownHandler);
  document.body.append(backdrop);
  apply.focus();
}

function renderQuestionAdditionProposal(host, proposal, questionSet, caseId, onRefresh) {
  host.replaceChildren();
  if (proposal.status !== "PROPOSED") return;
  const question = proposal.question || {};
  const card = button("", () => openQuestionAdditionDetails(proposal, questionSet, caseId, onRefresh), "master-item question-addition-proposal question-addition-summary");
  card.setAttribute("aria-haspopup", "dialog");
  card.setAttribute("aria-label", "Xem chi tiết đề xuất câu hỏi");
  const heading = element("div", undefined, "question-addition-status");
  heading.append(element("h3", "Câu hỏi mới"), element("span", safeText(proposal.status), "badge warning"));
  const summary = element("div", undefined, "stack-sm");
  summary.append(element("span", safeText(question.questionText), "question-addition-summary-text"));
  const meta = element("div", undefined, "actions");
  meta.append(
    element("span", categoryLabel(proposal.targetCategory), "badge"),
    element("span", safeText(question.questionType), "badge"),
    element("span", safeText(question.difficulty), "badge"),
  );
  card.append(heading, summary, meta);
  host.append(card);
}

function loadQuestionAdditionState(host, groupKey, questionSet, caseId, onRefresh) {
  const state = activeQuestionAddition(caseId, questionSet.id, groupKey);
  if (state?.taskId) {
    resumeTask(
      caseId,
      "questions",
      state.taskId,
      host,
      onRefresh,
      "AI đang thêm câu hỏi",
      (result) => {
        const proposalId = result?.task?.additionProposalId;
        if (proposalId) setState({ activeQuestionAddition: { ...state, taskId: null, proposalId } });
      },
      async (error) => {
        clearActiveQuestionAddition(caseId, questionSet.id, groupKey);
        await onRefresh();
        showError(error);
      },
    );
    return;
  }
  if (state?.proposalId) {
    host.append(element("p", "Đang tải đề xuất đã tạo...", "muted"));
    apiFetch(questionAdditionPath(caseId, state.proposalId))
      .then((proposal) => renderQuestionAdditionProposal(host, proposal, questionSet, caseId, onRefresh))
      .catch((error) => showError(error, host));
    return;
  }
  host.append(element("p", "Đang kiểm tra đề xuất đã lưu...", "muted"));
  apiFetch(questionAdditionPath(caseId) + "?questionSetId=" + encodeURIComponent(questionSet.id) + "&questionCategory=" + encodeURIComponent(groupKey))
    .then((result) => {
      const current = activeQuestionAddition(caseId, questionSet.id, groupKey);
      if (current) return;
      const proposal = result.items?.[0];
      if (!proposal || proposal.status !== "PROPOSED") {
        host.replaceChildren();
        return;
      }
      setState({ activeQuestionAddition: {
        caseId,
        questionSetId: questionSet.id,
        groupKey,
        taskId: null,
        proposalId: proposal.proposalId,
        mode: proposal.mode,
      } });
      renderQuestionAdditionProposal(host, proposal, questionSet, caseId, onRefresh);
    })
    .catch((error) => showError(error, host));
}

function questionVariantPath(caseId, questionId, variantId = "") {
  const base = "/api/v1/interview-cases/" + encodeURIComponent(caseId)
    + "/question-set/questions/" + encodeURIComponent(questionId) + "/variants";
  return variantId ? base + "/" + encodeURIComponent(variantId) : base;
}

async function restoreActiveQuestionVariantTask(caseId, questionSet, taskId) {
  if (!taskId) return;
  const current = getState().activeQuestionVariant;
  if (current?.taskId === taskId) return;
  const result = await apiFetch("/api/v1/tasks/" + encodeURIComponent(taskId));
  const task = result.task;
  if (task.taskType !== QUESTION_VARIANT_OPERATION || !task.sourceQuestionId) return;
  if (!["PENDING", "RUNNING", "PENDING_RETRY"].includes(task.status)) return;
  setState({
    activeQuestionVariant: {
      caseId,
      questionSetId: questionSet.id,
      questionId: task.sourceQuestionId,
      taskId,
      proposalId: null,
      mode: null,
    },
  });
}

function activeQuestionVariant(caseId, questionSetId, questionId) {
  const variant = getState().activeQuestionVariant;
  return variant?.caseId === caseId
    && variant.questionSetId === questionSetId
    && variant.questionId === questionId
    ? variant
    : null;
}

function clearActiveQuestionVariant(caseId, questionSetId, questionId) {
  const variant = activeQuestionVariant(caseId, questionSetId, questionId);
  if (variant) setState({ activeQuestionVariant: null });
}

async function requestQuestionVariant(caseId, questionSet, question, mode, prompt, onRefresh) {
  const task = await apiFetch(questionVariantPath(caseId, question.id), {
    method: "POST",
    body: JSON.stringify({
      questionSetId: questionSet.id,
      operation: QUESTION_VARIANT_OPERATION,
      mode,
      ...(prompt ? { prompt } : {}),
    }),
  });
  setState({
    activeQuestionVariant: {
      caseId,
      questionSetId: questionSet.id,
      questionId: question.id,
      taskId: task.taskId,
      proposalId: null,
      mode,
    },
  });
  await onRefresh();
}

function openQuestionPromptModal(caseId, questionSet, question, onRefresh) {
  const opener = document.activeElement;
  const backdrop = element("div", undefined, "modal-backdrop");
  const modal = element("section", undefined, "modal question-prompt-modal");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  const titleId = "question-prompt-title-" + question.id;
  const descriptionId = "question-prompt-description-" + question.id;
  const heading = element("h2", "Gen câu hỏi theo prompt");
  heading.id = titleId;
  const description = element("p", "Prompt chỉ là yêu cầu bổ sung cho AI; không thay đổi nhóm, vị trí hoặc quyền duyệt của HĐCM.", "muted");
  description.id = descriptionId;
  modal.setAttribute("aria-labelledby", titleId);
  modal.setAttribute("aria-describedby", descriptionId);

  const prompt = field("Yêu cầu bổ sung", "question-variant-prompt", {
    type: "textarea",
    required: true,
    placeholder: "Ví dụ: Tập trung vào cách xử lý một tình huống thực tế...",
  });
  prompt.input.maxLength = MAX_VARIANT_PROMPT_CHARS;
  prompt.input.setAttribute("aria-describedby", descriptionId + " question-prompt-count");
  const counter = element("p", "0/" + MAX_VARIANT_PROMPT_CHARS + " ký tự", "muted");
  counter.id = "question-prompt-count";
  counter.setAttribute("aria-live", "polite");
  const validation = element("p", "", "notice error");
  validation.hidden = true;
  prompt.input.addEventListener("input", () => {
    counter.textContent = prompt.input.value.length + "/" + MAX_VARIANT_PROMPT_CHARS + " ký tự";
    validation.hidden = true;
  });

  let keydownHandler;
  const closeModal = () => {
    document.removeEventListener("keydown", keydownHandler);
    backdrop.remove();
    opener?.focus?.();
  };
  keydownHandler = (event) => {
    if (event.key === "Escape") closeModal();
  };
  const close = element("button", "Hủy", "secondary");
  close.type = "button";
  close.addEventListener("click", closeModal);
  const submit = element("button", "Gen theo prompt", "primary");
  submit.type = "submit";
  const form = element("form", undefined, "stack");
  form.append(prompt.label, counter, validation);
  const actions = element("div", undefined, "actions document-actions");
  actions.append(close, submit);
  form.append(actions);
  formSubmit(form, async () => {
    const value = prompt.input.value.trim();
    if (!value) {
      validation.textContent = "Hãy nhập prompt trước khi tạo câu hỏi.";
      validation.hidden = false;
      prompt.input.focus();
      return;
    }
    if (value.length > MAX_VARIANT_PROMPT_CHARS) {
      validation.textContent = "Prompt không được vượt quá " + MAX_VARIANT_PROMPT_CHARS + " ký tự.";
      validation.hidden = false;
      prompt.input.focus();
      return;
    }
    closeModal();
    await requestQuestionVariant(caseId, questionSet, question, "USER_PROMPT", value, onRefresh);
  });
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  modal.append(heading, description, form);
  backdrop.append(modal);
  document.addEventListener("keydown", keydownHandler);
  document.body.append(backdrop);
  prompt.input.focus();
}

function renderVariantFields(variant) {
  const fields = element("div", undefined, "question-variant-fields");
  for (const [label, value] of [
    ["Mục đích", variant?.purpose],
    ["Mục tiêu bước tiếp theo", variant?.nextStepObjective],
    ["Bằng chứng cần tìm", variant?.expectedEvidence],
  ]) {
    const row = element("div", undefined, "detail-row");
    row.append(element("span", label, "detail-label"), element("span", safeText(value)));
    fields.append(row);
  }
  if (variant?.rubric) fields.append(renderRubric(variant.rubric));
  return fields;
}

function renderQuestionVariantPreview(host, question, proposal, questionSet, caseId, onRefresh) {
  host.replaceChildren();
  if (proposal.status !== "PROPOSED") return;
  const card = element("section", undefined, "card stack question-variant-preview");
  const heading = element("div", undefined, "question-variant-status");
  heading.append(
    element("h3", "Câu hỏi đề xuất"),
    element("span", safeText(proposal.status), "badge warning"),
  );
  const meta = element("p", "Mode: " + safeText(proposal.mode) + " · Schema: " + QUESTION_VARIANT_SCHEMA, "muted");
  const columns = element("div", undefined, "question-variant-columns");
  const current = element("div", undefined, "stack");
  current.append(element("strong", "Câu hỏi hiện tại"), element("div", safeText(question.questionText), "answer-text"));
  const suggested = element("div", undefined, "stack");
  suggested.append(element("strong", "Câu hỏi đề xuất"), element("div", safeText(proposal.variant?.questionText), "answer-text"));
  columns.append(current, suggested);
  const preserved = element("p", "Giữ nguyên: competencyKey=" + safeText(question.competencyKey)
    + ", questionCategory=" + safeText(question.questionCategory)
    + ", questionType=" + safeText(question.questionType)
    + ", difficulty=" + safeText(question.difficulty)
    + ", displayOrder=" + safeText(question.displayOrder), "muted");
  const actions = element("div", undefined, "actions");
  const apply = button("Dùng câu này", async () => {
    try {
      await apiFetch(questionVariantPath(caseId, question.id, proposal.proposalId) + "/apply", {
        method: "POST",
        body: JSON.stringify({
          questionSetId: questionSet.id,
          expectedQuestionSetUpdatedAt: questionSet.updatedAt,
          expectedSourceFingerprint: proposal.sourceFingerprint,
        }),
      });
      clearActiveQuestionVariant(caseId, questionSet.id, question.id);
      await onRefresh();
    } catch (error) {
      if (["QUESTION_SET_STALE", "STATE_CONFLICT", "QUESTION_VARIANT_STALE"].includes(error.code)) {
        await onRefresh();
        showError(
          { code: error.code, message: "Question Set đã thay đổi. Hãy tải lại trước khi áp dụng đề xuất." },
          document.querySelector("#question-detail-panel") || mainElement(),
        );
        return;
      }
      throw error;
    }
  }, "primary");
  const regenerate = button("Tạo lại", async () => {
    await apiFetch(questionVariantPath(caseId, question.id, proposal.proposalId) + "/discard", { method: "POST" });
    clearActiveQuestionVariant(caseId, questionSet.id, question.id);
    if (proposal.mode === "USER_PROMPT") {
      openQuestionPromptModal(caseId, questionSet, question, onRefresh);
      return;
    }
    await requestQuestionVariant(caseId, questionSet, question, "SAME_GROUP", null, onRefresh);
  }, "secondary");
  const discard = button("Bỏ qua", async () => {
    await apiFetch(questionVariantPath(caseId, question.id, proposal.proposalId) + "/discard", { method: "POST" });
    clearActiveQuestionVariant(caseId, questionSet.id, question.id);
    await onRefresh();
  }, "secondary");
  actions.append(apply, regenerate, discard);
  card.append(heading, meta, columns, renderVariantFields(proposal.variant), preserved, actions);
  host.append(card);
}

function loadQuestionVariantState(host, question, questionSet, caseId, onRefresh) {
  const state = activeQuestionVariant(caseId, questionSet.id, question.id);
  if (state?.taskId) {
    resumeTask(
      caseId,
      "questions",
      state.taskId,
      host,
      onRefresh,
      "AI đang tạo câu thay thế",
      (result) => {
        const proposalId = result?.task?.proposalId;
        if (proposalId) {
          setState({ activeQuestionVariant: { ...state, taskId: null, proposalId } });
        }
      },
    );
    return;
  }
  if (state?.proposalId) {
    host.append(element("p", "Đang tải đề xuất đã tạo...", "muted"));
    apiFetch(questionVariantPath(caseId, question.id, state.proposalId))
      .then((proposal) => {
        if (proposal.status === "PROPOSED") renderQuestionVariantPreview(host, question, proposal, questionSet, caseId, onRefresh);
        else clearActiveQuestionVariant(caseId, questionSet.id, question.id);
      })
      .catch((error) => showError(error, host));
    return;
  }
  host.append(element("p", "Đang kiểm tra đề xuất đã lưu...", "muted"));
  apiFetch(questionVariantPath(caseId, question.id) + "?questionSetId=" + encodeURIComponent(questionSet.id))
    .then((proposal) => {
      const current = activeQuestionVariant(caseId, questionSet.id, question.id);
      if (current) return;
      const item = proposal.items?.[0];
      if (!item || item.status !== "PROPOSED") {
        host.replaceChildren();
        return;
      }
      setState({
        activeQuestionVariant: {
          caseId,
          questionSetId: questionSet.id,
          questionId: question.id,
          taskId: null,
          proposalId: item.proposalId,
          mode: item.mode,
        },
      });
      renderQuestionVariantPreview(host, question, item, questionSet, caseId, onRefresh);
    })
    .catch((error) => showError(error, host));
}

function renderQuestionDetail(question, questionSet, caseId, onRefresh, assessmentStarted = false) {
  const detail = element("section", undefined, "card detail-panel stack");
  detail.append(element("h2", safeText(question.displayOrder) + ". " + safeText(question.questionText)));
  const rows = [
    ["Năng lực", question.competencyKey],
    ["Nguồn", question.sourceKind],
    ["Nhóm", categoryLabel(question.questionCategory)],
    ["Loại câu hỏi", question.questionType],
    ["Độ khó", question.difficulty],
    ["Mục đích", question.purpose],
    ["Mục tiêu bước tiếp theo", question.nextStepObjective],
    ["Bằng chứng cần tìm", question.expectedEvidence],
    ["Bắt buộc", question.isRequired ? "Có" : "Không"],
    ["Thời lượng ước tính", formatDuration(question.estimatedSeconds)],
  ];
  for (const [label, value] of rows) {
    const row = element("div", undefined, "detail-row");
    row.append(element("span", label, "detail-label"), element("span", safeText(value)));
    detail.append(row);
  }
  detail.append(renderRubric(question.rubric));
  const mutationLocked = questionSet.status === "APPROVED" || assessmentStarted;
  const variantHost = element("div", undefined, "stack question-variant-status");
  detail.append(variantHost);
  if (!mutationLocked) {
    const questionActions = element("div", undefined, "actions question-actions");
    const activeVariant = activeQuestionVariant(caseId, questionSet.id, question.id);
    const hasPendingVariant = Boolean(activeVariant);
    const promptButton = button("Gen theo prompt", () => openQuestionPromptModal(caseId, questionSet, question, onRefresh), "secondary");
    const sameGroupButton = button("Tự động gen câu khác", async () => {
      await requestQuestionVariant(caseId, questionSet, question, "SAME_GROUP", null, onRefresh);
    }, "secondary");
    promptButton.disabled = hasPendingVariant;
    sameGroupButton.disabled = hasPendingVariant;
    questionActions.append(promptButton, sameGroupButton);
    detail.append(questionActions);
  } else {
    detail.append(element("div", "Câu hỏi đã khóa; không thể tạo proposal hoặc chỉnh sửa sau khi duyệt/bắt đầu assessment.", "notice warning"));
  }
  if (!mutationLocked) loadQuestionVariantState(variantHost, question, questionSet, caseId, onRefresh);
  return detail;
}

function renderQuestionWorkspace(questionSet, caseId, onRefresh, assessmentStarted = false) {
  const questions = [...(questionSet.questions || [])].sort((a, b) => a.displayOrder - b.displayOrder);
  const workspace = element("div", undefined, "master-detail");
  const master = element("div", undefined, "master-list");
  const detailHost = element("div", undefined, "detail-panel");
  master.setAttribute("role", "tablist");
  detailHost.id = "question-detail-panel";
  detailHost.setAttribute("role", "tabpanel");
  workspace.append(master, detailHost);
  const rememberedSelection = getState().selectedQuestion;
  let selectedId = rememberedSelection?.caseId === caseId
    && questions.some((question) => question.id === rememberedSelection.questionId)
    ? rememberedSelection.questionId
    : questions[0]?.id;
  if (selectedId) setState({ selectedQuestion: { caseId, questionId: selectedId } });
  let restoreFocusId = selectedId;
  const redraw = () => {
    master.replaceChildren();
    const mutationLocked = questionSet.status === "APPROVED" || assessmentStarted;
    for (const group of questionGroups(questions)) {
      const groupSection = element("section", undefined, "question-group");
      const groupTitle = element("div", undefined, "question-group-title");
      const groupCopy = element("div", undefined, "stack");
      groupCopy.append(element("h3", group.label));
      groupTitle.append(groupCopy);
      const isStandardGroup = ["FOUNDATION", "APPLICATION", "DEEP_DIVE"].includes(group.key);
      let addButton = null;
      if (isStandardGroup) {
        addButton = button("", () => {
          if (mutationLocked) return;
          openQuestionAdditionChoice(group.key, {
            onPrompt: () => openQuestionAdditionPrompt(group.key, {
              onSubmit: async (prompt) => {
                await requestQuestionAddition(caseId, questionSet.id, group.key, "USER_PROMPT", prompt);
                await onRefresh();
              },
            }),
            onAuto: async () => {
              await requestQuestionAddition(caseId, questionSet.id, group.key, "AUTO_GROUP", null);
              await onRefresh();
            },
          });
        }, "master-item question-add-card");
        addButton.dataset.questionCategory = group.key;
        addButton.setAttribute("aria-label", "ThÃªm cÃ¢u há»i vÃ o " + group.label);
        const plus = element("span", "+", "question-add-card-plus");
        plus.setAttribute("aria-hidden", "true");
        addButton.append(plus);
        addButton.disabled = mutationLocked || Boolean(activeQuestionAddition(caseId, questionSet.id, group.key));
      }
      groupSection.append(groupTitle);
      const additionHost = element("div", undefined, "question-addition-progress");
      for (const question of group.items) {
        const item = button("", () => {
          selectedId = question.id;
          setState({ selectedQuestion: { caseId, questionId: selectedId } });
          restoreFocusId = question.id;
          redraw();
        }, "master-item" + (selectedId === question.id ? " selected" : ""));
        item.id = "question-tab-" + question.id;
        item.dataset.questionId = question.id;
        item.setAttribute("role", "tab");
        item.setAttribute("aria-controls", "question-detail-panel");
        item.setAttribute("aria-selected", selectedId === question.id ? "true" : "false");
        item.append(element("span", question.displayOrder + ". " + safeText(question.questionText), "master-item-title"));
        item.append(element("span", categoryLabel(question.questionCategory) + " · " + safeText(question.difficulty), "master-item-meta"));
        groupSection.append(item);
      }
      if (isStandardGroup) {
        groupSection.append(additionHost);
        if (!mutationLocked) {
          loadQuestionAdditionState(additionHost, group.key, questionSet, caseId, async () => onRefresh());
        }
        groupSection.append(addButton);
      }
      master.append(groupSection);
    }
    const selected = questions.find((question) => question.id === selectedId) || questions[0];
    detailHost.setAttribute("aria-labelledby", selected ? "question-tab-" + selected.id : "");
    if (restoreFocusId) {
      const focusId = restoreFocusId;
      restoreFocusId = null;
      queueMicrotask(() => master.querySelector('[data-question-id="' + focusId + '"]')?.focus());
    }
    detailHost.replaceChildren(selected ? renderQuestionDetail(selected, questionSet, caseId, async () => {
      await onRefresh();
    }, assessmentStarted) : element("p", "Chưa có câu hỏi.", "muted"));
  };
  redraw();
  return workspace;
}

function createManualQuestionModel(order) {
  return {
    displayOrder: order,
    questionText: "",
    competencyKey: "",
    sourceKind: "MANUAL",
    questionCategory: "",
    purpose: "",
    nextStepObjective: "",
    expectedEvidence: "",
  };
}

async function renderManualDraft(caseId) {
  await renderCasePage(caseId, "questions", async () => {
    const view = element("div", undefined, "stack");
    view.append(element("div", "Bản nháp thủ công vẫn được backend kiểm tra theo framework hiện hành. Hãy nhập đủ các trường và nhóm câu hỏi trước khi lưu.", "notice warning"));
    const form = element("form", undefined, "card stack");
    const rows = [createManualQuestionModel(1)];
    const rowsHost = element("div", undefined, "stack");
    const redraw = () => {
      rowsHost.replaceChildren();
      rows.forEach((model, index) => {
        const card = element("section", undefined, "card stack");
        card.append(element("h2", "Câu " + (index + 1)));
        const grid = element("div", undefined, "field-grid");
        const text = field("Nội dung câu hỏi", "questionText", { type: "textarea", value: model.questionText, required: true });
        const competency = field("Năng lực", "competencyKey", { value: model.competencyKey, required: true });
        const category = selectField("Nhóm", "questionCategory", [
          { value: "", label: "Chọn nhóm" },
          { value: "FOUNDATION", label: "Nền tảng" },
          { value: "APPLICATION", label: "Ứng dụng" },
          { value: "DEEP_DIVE", label: "Chuyên sâu" },
        ], model.questionCategory);
        const purpose = field("Mục đích", "purpose", { type: "textarea", value: model.purpose, required: true });
        const objective = field("Mục tiêu bước tiếp theo", "nextStepObjective", { type: "textarea", value: model.nextStepObjective, required: true });
        const evidence = field("Bằng chứng cần tìm", "expectedEvidence", { type: "textarea", value: model.expectedEvidence, required: true });
        for (const pair of [[text, "questionText"], [competency, "competencyKey"], [category, "questionCategory"], [purpose, "purpose"], [objective, "nextStepObjective"], [evidence, "expectedEvidence"]]) {
          pair[0].input.addEventListener("input", () => { model[pair[1]] = pair[0].input.value; });
          grid.append(pair[0].label);
        }
        card.append(grid);
        rowsHost.append(card);
      });
    };
    redraw();
    const add = button("Thêm câu hỏi", () => {
      rows.push(createManualQuestionModel(rows.length + 1));
      redraw();
    }, "secondary");
    const save = element("button", "Lưu bản nháp", "primary");
    save.type = "submit";
    form.append(rowsHost, element("div", "Có thể thêm/bớt dòng; số lượng và tỷ lệ nhóm sẽ do backend xác nhận.", "muted"), element("div", undefined, "actions"));
    form.lastElementChild.append(add, save);
    formSubmit(form, async () => {
      const questions = rows.map((item) => ({
        ...item,
        rubric: {
          score0: "Chưa cung cấp bằng chứng",
          score1: "Bằng chứng rất hạn chế",
          score2: "Đáp ứng một phần",
          score3: "Đáp ứng yêu cầu",
          score4: "Vượt yêu cầu và có bằng chứng rõ",
        },
        questionType: "LONG_TEXT",
        difficulty: "MEDIUM",
        isRequired: true,
        estimatedSeconds: 120,
      }));
      await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/question-set", {
        method: "POST",
        body: JSON.stringify({ operation: "MANUAL", questions }),
      });
      await renderQuestions(caseId);
    });
    view.append(form);
    return view;
  });
}

async function renderQuestions(caseId) {
  await renderCasePage(caseId, "questions", async (item) => {
    const view = element("div", undefined, "stack");
    let questionSet = null;
    try {
      questionSet = (await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/question-set")).questionSet;
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    if (!questionSet) {
      const empty = element("section", undefined, "card empty-state");
      empty.append(element("h2", item.refinedFlowStatus === "QUESTIONS_GENERATING" ? "Đang sinh bộ câu hỏi" : "Chưa có bộ câu hỏi"));
      empty.append(element("p", item.refinedFlowStatus === "QUESTIONS_GENERATING" ? "Tác vụ đang được xử lý trên backend. Mở lại màn hình để kiểm tra, không tạo lại task nếu chưa có kết quả." : "Sinh câu hỏi dựa trên JD/CV đã xác nhận.", "muted"));
      const taskHost = element("div", undefined, "stack");
      const taskRunning = Boolean(item.activeTaskId && item.refinedFlowStatus === "QUESTIONS_GENERATING");
      if (taskRunning) {
        resumeTask(caseId, "questions", item.activeTaskId, taskHost, () => renderQuestions(caseId), "AI đang tạo bộ câu hỏi");
      }
      const generate = button("Sinh bộ câu hỏi bằng AI", async () => {
        const task = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/question-set", {
          method: "POST",
          body: JSON.stringify({ operation: "GENERATE" }),
        });
        setState({ activeTaskId: task.taskId });
        await waitForTask(task.taskId, taskHost, "AI đang tạo bộ câu hỏi");
        if (!isActiveCaseStep(caseId, "questions")) return;
        await renderQuestions(caseId);
      }, "primary");
      const levelReady = item.job?.targetLevelStatus === "READY";
      const canGenerate = levelReady && ["DOCUMENTS_READY", "QUESTION_GENERATION_FAILED"].includes(item.refinedFlowStatus);
      generate.disabled = !canGenerate;
      const manual = button("Tạo bản nháp thủ công", () => renderManualDraft(caseId), "secondary");
      manual.disabled = !canGenerate;
      empty.append(taskHost);
      if (!taskRunning) {
        empty.append(generate, manual);
        if (!levelReady) {
          empty.append(element("p", "Cần xác định level từ JD trước khi tạo Question Set.", "muted"));
        } else if (!canGenerate) {
          empty.append(element("p", "Cần xác nhận đủ JD và CV trước khi tạo Question Set.", "muted"));
        }
      }
      view.append(empty);
      return view;
    }

    const overview = element("section", undefined, "card stack");
    const overviewTop = element("div", undefined, "actions");
    overviewTop.append(element("span", "Version " + questionSet.versionNo, "badge"), statusBadge(questionSet.status), element("span", questionSet.questions.length + " câu", "badge"), element("span", formatDuration(questionSet.durationSeconds), "badge"));
    const questionPolicy = questionSet.questionPolicy || {};
    overview.append(overviewTop);
    if (questionPolicy.confidence !== undefined || questionPolicy.limitations?.length) {
      const quality = element("div", undefined, "notice");
      quality.append(element("span", "AI confidence: " + formatConfidence(questionPolicy.confidence)));
      if (questionPolicy.limitations?.length) quality.append(element("p", "Giới hạn: " + questionPolicy.limitations.join("; "), "muted"));
      overview.append(quality);
    }
    if (item.activeTaskId) {
      await restoreActiveQuestionVariantTask(caseId, questionSet, item.activeTaskId);
      await restoreActiveQuestionAdditionTask(caseId, questionSet, item.activeTaskId);
    }
    view.append(overview, renderQuestionWorkspace(
      questionSet,
      caseId,
      async () => renderQuestions(caseId),
      Boolean(item.assessmentAttemptId),
    ));

    const actions = element("div", undefined, "actions");
    if (questionSet.status !== "APPROVED") {
      const approve = button("Duyệt bộ câu hỏi", async () => {
        const member = item.committeeMembers?.[0];
        if (!member) throw new Error("Case chưa có thành viên HĐCM để duyệt");
        await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/question-set/approve", {
          method: "POST",
          body: JSON.stringify({ questionSetId: questionSet.id, memberId: member.id, confirmation: "APPROVE_QUESTION_SET" }),
        });
        await renderQuestions(caseId);
      }, "primary");
      actions.append(approve);
    }
    const exportHtmlButton = button("Xuất bộ câu hỏi HTML cho ứng viên", async () => {
      const downloaded = await apiDownload("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/candidate-package/export", { method: "POST" });
      saveDownload(downloaded.blob, downloaded.response.headers.get("Content-Disposition") || "candidate-assessment.html");
      location.hash = stepHref(caseId, "answers").slice(1);
    }, "primary");
    actions.append(exportHtmlButton, link("Tiếp: Câu trả lời", stepHref(caseId, "answers"), "link-button"));
    view.append(actions);
    return view;
  });
}

function saveDownload(blob, contentDisposition) {
  const match = /filename="?([^";]+)"?/i.exec(contentDisposition || "");
  const filename = match ? match[1] : "candidate-assessment.html";
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

function renderSnapshotWorkspace(snapshot) {
  const answersByQuestion = new Map((snapshot.answers || []).map((answer) => [answer.questionId, answer]));
  const questions = [...(snapshot.questions || [])].sort((a, b) => a.displayOrder - b.displayOrder);
  const section = element("section", undefined, "card stack");
  const summary = element("div", undefined, "actions");
  const answered = [...answersByQuestion.values()].filter((answer) => answer.isAnswered).length;
  summary.append(element("span", "Snapshot v" + snapshot.versionNo, "badge"), element("span", answered + "/" + questions.length + " câu đã trả lời", "badge"), element("span", safeText(snapshot.refinedFlowStatus), "badge"));
  section.append(summary);
  const tableWrap = element("div", undefined, "table-wrap");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["#", "Câu hỏi", "Trạng thái", "Câu trả lời"]) headRow.append(element("th", label));
  head.append(headRow);
  const body = document.createElement("tbody");
  let selectedId = questions[0]?.questionId;
  const detail = element("div", undefined, "answer-detail");
  const redraw = () => {
    body.replaceChildren();
    for (const question of questions) {
      const answer = answersByQuestion.get(question.questionId) || { answerText: "", isAnswered: false, assessmentStatus: "NOT_ASSESSED" };
      const row = document.createElement("tr");
      const buttonCell = document.createElement("td");
      const select = button(String(question.displayOrder), () => { selectedId = question.questionId; redraw(); }, "link-button");
      select.setAttribute("aria-selected", selectedId === question.questionId ? "true" : "false");
      buttonCell.append(select);
      row.append(buttonCell, element("td", question.questionText), element("td", undefined), element("td", answer.answerText || "Chưa có câu trả lời"));
      row.children[2].append(element("span", answer.isAnswered ? "ANSWERED" : "NOT_ASSESSED", "badge " + (answer.isAnswered ? "success" : "warning")));
      body.append(row);
    }
    const question = questions.find((item) => item.questionId === selectedId) || questions[0];
    const answer = question ? answersByQuestion.get(question.questionId) || { answerText: "", isAnswered: false, assessmentStatus: "NOT_ASSESSED" } : null;
    detail.replaceChildren();
    if (!question) {
      detail.append(element("p", "Snapshot chưa có câu hỏi.", "muted"));
      return;
    }
    detail.append(element("h2", question.displayOrder + ". " + question.questionText));
    const columns = element("div", undefined, "answer-columns");
    const original = element("section", undefined, "stack");
    original.append(element("h3", "Nội dung question/rubric"), element("p", question.expectedEvidence, "muted"), renderRubric(question.rubric));
    const answerCard = element("section", undefined, "stack");
    answerCard.append(element("h3", "Câu trả lời đã import"), element("span", answer.isAnswered ? "ANSWERED" : "NOT_ASSESSED", "badge " + (answer.isAnswered ? "success" : "warning")), element("div", answer.answerText || "Chưa có câu trả lời", "answer-text"));
    columns.append(original, answerCard);
    detail.append(columns);
  };
  redraw();
  table.append(head, body);
  tableWrap.append(table);
  section.append(tableWrap, detail);
  return section;
}

async function renderAnswers(caseId) {
  await renderCasePage(caseId, "answers", async () => {
    const view = element("div", undefined, "stack");
    let snapshot = null;
    try {
      snapshot = (await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/assessment-snapshots/current")).snapshot;
      setState({ currentSnapshotId: snapshot.id });
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    const importCard = element("section", undefined, "card stack transfer-card answer-import-card");
    importCard.append(element("h2", "Import câu trả lời từ máy ứng viên"), element("p", "Ứng viên mở file HTML offline, nộp bài và gửi lại file response cho HĐCM.", "muted"));
    const htmlFile = document.createElement("input");
    htmlFile.type = "file";
    htmlFile.accept = ".html,text/html";
    htmlFile.name = "candidate-response-package";
    let htmlImportIdempotencyKey = null;
    htmlFile.addEventListener("change", () => { htmlImportIdempotencyKey = null; });
    const htmlLabel = element("label", "Candidate response .html");
    htmlLabel.append(htmlFile);
    const htmlImportButton = button("Import candidate HTML", async () => {
      const responseFile = htmlFile.files?.[0];
      if (!responseFile) throw new Error("Hãy chọn file response .html");
      if (!responseFile.name.toLowerCase().endsWith(".html")) throw new Error("Chỉ hỗ trợ file .html");
      if (responseFile.size > MAX_HTML_PACKAGE_BYTES) throw new Error("HTML package vượt quá 10 MB");
      htmlImportIdempotencyKey ||= globalThis.crypto?.randomUUID?.() || "ui-html-upload-" + Date.now() + "-" + Math.random().toString(16).slice(2);
      const result = await apiUpload("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/candidate-package/import", responseFile, {
        contentType: "text/html",
        headers: { "X-Idempotency-Key": htmlImportIdempotencyKey },
      });
      setState({ currentSnapshotId: result.snapshot.id });
      await renderAnswers(caseId);
    }, "primary");
    importCard.append(htmlLabel, htmlImportButton);

    view.append(importCard);
    if (snapshot) {
      view.append(renderSnapshotWorkspace(snapshot));
      view.append(element("div", "Snapshot là immutable; AI sẽ đánh giá đúng snapshot đang hiển thị.", "notice"));
      view.append(link("Tiếp: Đánh giá AI", stepHref(caseId, "ai"), "link-button"));
    }
    return view;
  });
}

function renderListSection(title, values, className = "") {
  const section = element("section", undefined, "stack" + (className ? " " + className : ""));
  section.append(element("h2", title));
  const list = document.createElement("ul");
  if (values?.length) {
    for (const value of values) list.append(element("li", safeText(value)));
  } else {
    list.append(element("li", "Không có nội dung được ghi nhận", "muted"));
  }
  section.append(list);
  return section;
}

function renderEvaluationResult(result, snapshot) {
  const payload = result.payload || {};
  const section = element("div", undefined, "evaluation-result");
  const header = element("section", undefined, "card evaluation-header");
  const headerMain = element("div", undefined, "evaluation-header-main");
  const headerCopy = element("div", undefined, "evaluation-header-copy");
  headerCopy.append(element("h2", "Kết quả đánh giá AI"), element("p", "Tóm tắt kết quả phân tích để HĐCM đối chiếu theo từng nhóm bằng chứng.", "muted"));
  const meta = element("div", undefined, "actions evaluation-meta");
  meta.append(element("span", "Result v" + safeText(result.versionNo), "badge success"), element("span", safeText(payload.schemaVersion), "badge"), element("span", "Confidence: " + formatConfidence(result.confidence ?? payload.confidence), "badge"));
  if (result.provider) meta.append(element("span", safeText(result.provider), "badge"));
  if (result.model) meta.append(element("span", safeText(result.model), "badge"));
  meta.append(element("span", "Snapshot ID: " + safeText(result.assessmentSnapshotId || snapshot.id), "badge"));
  headerMain.append(headerCopy, meta);
  header.append(headerMain, element("p", "Kết quả AI chỉ là thông tin hỗ trợ; HĐCM là bên đưa ra đánh giá cuối cùng.", "notice warning"));
  section.append(header);

  const answeredCount = (snapshot.answers || []).filter((answer) => answer.isAnswered).length;
  const summary = element("section", undefined, "evaluation-summary");
  const metricGrid = element("div", undefined, "metric-grid");
  for (const metric of [["Đã trả lời", answeredCount + "/" + snapshot.questions.length], ["Độ tin cậy", formatConfidence(result.confidence ?? payload.confidence)], ["Snapshot", "v" + snapshot.versionNo]]) {
    const card = element("div", undefined, "metric");
    card.append(element("span", metric[0], "muted"), element("span", metric[1], "metric-value"));
    metricGrid.append(card);
  }
  summary.append(metricGrid);
  section.append(summary);

  const findings = element("section", undefined, "evaluation-findings");
  const summaryGrid = element("div", undefined, "content-grid");
  summaryGrid.append(renderListSection("Điểm mạnh", payload.strengths, "card evaluation-finding"), renderListSection("Khoảng trống", payload.gaps, "card evaluation-finding"));
  findings.append(summaryGrid);
  const signalsGrid = element("div", undefined, "content-grid");
  signalsGrid.append(renderListSection("Mâu thuẫn cần xem xét", payload.conflicts, "card evaluation-finding"), renderListSection("Rủi ro", payload.risks, "card evaluation-finding"));
  findings.append(signalsGrid);
  section.append(findings);

  const competencies = element("section", undefined, "card evaluation-competencies");
  competencies.append(element("h2", "Ma trận năng lực"));
  const competencyTable = element("div", undefined, "table-wrap");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const row = document.createElement("tr");
  for (const label of ["Năng lực", "Tóm tắt", "Bằng chứng", "Confidence"]) row.append(element("th", label));
  head.append(row);
  const body = document.createElement("tbody");
  const competencyItems = payload.competencyEvaluations || [];
  for (const item of competencyItems) {
    const line = document.createElement("tr");
    line.append(element("td", item.competencyKey), element("td", item.summary), element("td", item.evidenceStatus), element("td", formatConfidence(item.confidence)));
    body.append(line);
  }
  if (!competencyItems.length) {
    const line = document.createElement("tr");
    const empty = element("td", "Không có nội dung được ghi nhận", "muted");
    empty.colSpan = 4;
    line.append(empty);
    body.append(line);
  }
  table.append(head, body);
  competencyTable.append(table);
  competencies.append(competencyTable);
  section.append(competencies);

  const answers = element("section", undefined, "evaluation-answers");
  answers.append(element("h2", "Chi tiết theo câu trả lời"));
  const sourceAnswers = new Map((snapshot.answers || []).map((answer) => [answer.questionId, answer]));
  const sourceQuestions = new Map((snapshot.questions || []).map((question) => [question.questionId, question]));
  for (const [index, item] of (payload.perAnswerEvaluations || []).entries()) {
    const original = sourceAnswers.get(item.questionId);
    const question = sourceQuestions.get(item.questionId);
    const details = document.createElement("details");
    details.className = "card evaluation-answer";
    details.open = index === 0;
    const scoreLabel = item.score === null ? "NOT_ASSESSED" : "Score: " + safeText(item.score);
    const summary = document.createElement("summary");
    summary.className = "evaluation-answer-summary";
    const title = element("span", undefined, "evaluation-answer-title");
    title.append(element("strong", safeText(question?.displayOrder) + ". " + safeText(question?.questionText)), element("span", "Question " + safeText(question?.questionId || item.questionId), "muted"));
    const answerMeta = element("span", undefined, "evaluation-answer-meta");
    answerMeta.append(element("span", safeText(item.evidenceStatus), "badge " + (item.evidenceStatus === "NOT_ASSESSED" ? "warning" : "success")), element("span", scoreLabel, "badge"));
    summary.append(title, answerMeta);
    details.append(summary);
    const columns = element("div", undefined, "answer-columns evaluation-answer-grid");
    columns.append(
      element("div", undefined, "stack"),
      element("div", undefined, "stack"),
    );
    columns.children[0].append(element("strong", "Câu trả lời gốc"), element("div", original?.answerText || "NOT_ASSESSED", "answer-text"));
    columns.children[1].append(element("strong", "Reasoning / Evidence"), element("div", safeText(item.reasoning), "answer-text"), element("p", "Evidence: " + safeText((item.evidenceFound || []).join(", "))), element("p", "CV consistency: " + safeText(item.cvConsistency)));
    if (item.concerns?.length) columns.children[1].append(renderListSection("Concerns", item.concerns, "evaluation-concerns"));
    details.append(columns);
    answers.append(details);
  }
  section.append(answers);
  section.append(renderListSection("Giới hạn của kết quả", payload.limitations, "card evaluation-limitations"));
  section.append(element("p", "AI hỗ trợ đối chiếu bằng chứng. Quyết định tuyển dụng thuộc HĐCM.", "notice evaluation-footer"));
  return section;
}

async function renderAI(caseId) {
  await renderCasePage(caseId, "ai", async (item) => {
    const view = element("div", undefined, "stack");
    let snapshot = null;
    try {
      snapshot = (await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/assessment-snapshots/current")).snapshot;
      setState({ currentSnapshotId: snapshot.id });
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    if (!snapshot) {
      view.append(element("section", "Chưa có workbook câu trả lời.", "empty-state"), link("Đến bước nhập Excel", stepHref(caseId, "answers"), "link-button"));
      return view;
    }
    let result = null;
    try {
      result = (await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/ai/evaluation")).result;
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    let resultSnapshot = snapshot;
    const resultUsesOlderSnapshot = Boolean(result && result.assessmentSnapshotId && result.assessmentSnapshotId !== snapshot.id);
    if (resultUsesOlderSnapshot) {
      try {
        resultSnapshot = (await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/assessment-snapshots/" + encodeURIComponent(result.assessmentSnapshotId))).snapshot;
      } catch (error) {
        resultSnapshot = snapshot;
      }
    }
    const actionCard = element("section", undefined, "card stack evaluation-action");
    actionCard.append(element("h2", "Đánh giá dựa trên snapshot v" + snapshot.versionNo), element("p", "AI nhận JD/CV đã xác nhận và nội dung snapshot; không tự đưa ra PASS/FAIL.", "muted"));
    if (resultUsesOlderSnapshot) {
      actionCard.append(element("div", "Đang hiển thị kết quả AI của snapshot v" + resultSnapshot.versionNo + "; snapshot hiện hành là v" + snapshot.versionNo + ".", "notice warning"));
    }
    const taskHost = element("div", undefined, "stack");
    const evaluationRunning = Boolean(item.activeTaskId && item.refinedFlowStatus === "AI_ANALYZING");
    if (evaluationRunning) {
      resumeTask(caseId, "ai", item.activeTaskId, taskHost, () => renderAI(caseId), "AI đang đánh giá ứng viên");
    }
    const action = button(result ? "Chạy đánh giá lại" : "Bắt đầu đánh giá bằng AI", async () => {
      const task = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/ai/evaluate", {
        method: "POST",
        body: JSON.stringify({ snapshotId: snapshot.id, forceRerun: Boolean(result) }),
      });
      setState({ activeTaskId: task.taskId });
      await waitForTask(task.taskId, taskHost, "AI đang đánh giá ứng viên");
      if (!isActiveCaseStep(caseId, "ai")) return;
      await renderAI(caseId);
    }, "primary");
    if (evaluationRunning) {
      const runningMessage = result
        ? "Kết quả hiện tại vẫn là bản cũ (Result v" + safeText(result.versionNo) + ", snapshot v" + safeText(resultSnapshot.versionNo) + ") trong khi AI đang tạo phiên đánh giá mới."
        : "AI task đang chạy hoặc đang được materialize. Không tạo task mới; hãy refresh để kiểm tra.";
      actionCard.append(element("div", runningMessage, "notice warning"));
    } else {
      actionCard.append(action);
    }
    actionCard.append(taskHost);
    view.append(actionCard);
    if (result) view.append(renderEvaluationResult(result, resultSnapshot));
    else if (item.refinedFlowStatus === "AI_ANALYSIS_FAILED") view.append(element("div", "Đánh giá AI thất bại. Answers và snapshot vẫn được giữ để retry hoặc review thủ công.", "notice error"));
    return view;
  });
}

async function renderSettings() {
  const page = renderWorkspacePage("#/settings", "Cấu hình", "Thông tin an toàn từ backend; không hiển thị API key hoặc nội dung .env.");
  page.content.append(renderLoading());
  try {
    const data = await apiFetch("/api/v1/settings");
    const card = element("section", undefined, "card stack");
    card.append(element("h2", "Runtime configuration"));
    const tableWrap = element("div", undefined, "table-wrap");
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const row = document.createElement("tr");
    for (const label of ["Key", "Giá trị", "Cập nhật"]) row.append(element("th", label));
    head.append(row);
    const body = document.createElement("tbody");
    for (const item of data.items || []) {
      const line = document.createElement("tr");
      line.append(element("td", item.key), element("td", item.isSensitive ? "Ẩn" : safeText(item.value)), element("td", safeText(item.updatedAt)));
      body.append(line);
    }
    table.append(head, body);
    tableWrap.append(table);
    card.append(tableWrap, element("p", "Committee PIN đã cấu hình: " + (data.pinConfigured ? "Có" : "Chưa có"), "muted"));
    const old = page.content.querySelector(".card.stack");
    if (old) old.replaceWith(card);
  } catch (error) {
    showError(error, page.main);
  }
}

async function renderBackups() {
  const page = renderWorkspacePage("#/backups", "Sao lưu và export", "Chỉ dùng các thao tác backup/export do backend cung cấp; trình duyệt không tự restore dữ liệu.");
  const backup = element("section", undefined, "card stack");
  backup.append(element("h2", "Tạo backup SQLite"), element("p", "Backup trả về safe path summary, không hiển thị secret/token.", "muted"));
  const label = field("Nhãn backup", "label", { value: "manual-ui-backup", required: true });
  const include = field("Bao gồm tài liệu", "includeDocuments", { type: "checkbox" });
  const create = button("Tạo backup", async () => {
    const result = await apiFetch("/api/v1/backups", {
      method: "POST",
      body: JSON.stringify({ label: label.input.value.trim(), includeDocuments: include.input.checked }),
    });
    backup.append(element("div", "Backup: " + safeText(result.backup.status) + " · " + safeText(result.backup.safePathSummary), "notice success"));
  }, "primary");
  backup.append(label.label, include.label, create);

  const exportCard = element("section", undefined, "card stack");
  exportCard.append(element("h2", "Export một hồ sơ"), element("p", "Chọn case từ dữ liệu thật, không nhập path filesystem.", "muted"));
  const caseSelect = document.createElement("select");
  caseSelect.name = "caseId";
  caseSelect.append(element("option", "Đang tải hồ sơ…"));
  const exportInclude = field("Bao gồm tài liệu", "exportIncludeDocuments", { type: "checkbox" });
  const exportButton = button("Export hồ sơ", async () => {
    if (!caseSelect.value) throw new Error("Hãy chọn hồ sơ");
    const result = await apiFetch("/api/v1/exports", {
      method: "POST",
      body: JSON.stringify({ caseId: caseSelect.value, includeDocuments: exportInclude.input.checked }),
    });
    exportCard.append(element("div", "Export: " + safeText(result.export.status) + " · " + safeText(result.export.safePathSummary), "notice success"));
  }, "primary");
  const caseLabel = element("label", "Hồ sơ");
  caseLabel.append(caseSelect);
  exportCard.append(caseLabel, exportInclude.label, exportButton);
  page.content.append(backup, exportCard);
  try {
    const data = await apiFetch("/api/v1/interview-cases");
    caseSelect.replaceChildren();
    for (const item of data.items || []) {
      const option = element("option", safeText(item.candidate?.fullName) + " · " + safeText(item.job?.positionTitle));
      option.value = item.id;
      caseSelect.append(option);
    }
    exportButton.disabled = !(data.items || []).length;
  } catch (error) {
    showError(error, page.main);
  }
}

async function boot() {
  try {
    const bootstrap = await apiFetch("/api/v1/bootstrap");
    setState({ startupToken: bootstrap.startupToken });
    renderAuthentication(bootstrap.pinConfigured);
  } catch (error) {
    showError(error);
  }
}

window.addEventListener("committee-session-expired", () => {
  if (!getState().committeeSession) return;
  renderRevision += 1;
  clearSensitiveState();
  renderAuthentication(true);
});

boot();
