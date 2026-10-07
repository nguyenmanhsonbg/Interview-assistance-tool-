import { apiDownload, apiFetch, apiUpload } from "./api.js";
import { currentRoute, registerRoute, startRouter } from "./router.js";
import { clearSensitiveState, getState, setState } from "./store.js";

const appRoot = document.querySelector("#app");
const skipLink = document.querySelector(".skip-link");
skipLink?.addEventListener("click", (event) => {
  event.preventDefault();
  document.querySelector("#main-content")?.focus();
});
const MAX_WORKBOOK_BYTES = 10 * 1024 * 1024;
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
    element("span", safeText(item.job?.targetLevel)),
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
      positionCell.append(element("div", safeText(item.job?.targetLevel), "muted"));
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
    field("Level", "targetLevel", { required: true }),
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
    const draftKey = [values.candidateCode, values.positionTitle, values.targetLevel].join("|");
    const cached = pendingCaseCreation?.key === draftKey ? pendingCaseCreation : null;
    const job = cached?.job || (await apiFetch("/api/v1/jobs", {
      method: "POST",
      body: JSON.stringify({ positionTitle: values.positionTitle, targetLevel: values.targetLevel }),
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

async function renderDocuments(caseId) {
  await renderCasePage(caseId, "documents", async (item) => {
    const data = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/documents");
    const current = (type) => data.items?.find((document) => document.documentType === type && document.isCurrent);
    const view = element("div", undefined, "stack");
    view.append(element("div", "Chỉ tài liệu hiện hành đã xác nhận mới được dùng để sinh câu hỏi.", "notice"));
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

async function waitForTask(taskId, host) {
  if (taskPollers.has(taskId)) return taskPollers.get(taskId);
  const promise = (async () => {
    if (!getState().committeeSession) return null;
    const panel = element("div", "Đang xử lý tác vụ AI…", "notice");
    panel.setAttribute("aria-live", "polite");
    if (host?.isConnected) host.append(panel);
    for (let attempt = 0; attempt < 150; attempt += 1) {
      if (!getState().committeeSession) return null;
      const result = await apiFetch("/api/v1/tasks/" + encodeURIComponent(taskId));
      const task = result.task;
      panel.textContent = "Tác vụ AI: " + safeText(task.status);
      if (task.status === "COMPLETED") return result;
      if (task.status === "FAILED") throw new Error(task.errorCode || "Tác vụ AI thất bại");
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error("Tác vụ AI quá thời gian chờ; hãy mở lại màn hình để kiểm tra trạng thái");
  })().finally(() => taskPollers.delete(taskId));
  taskPollers.set(taskId, promise);
  return promise;
}

function resumeTask(caseId, step, taskId, host, refresh) {
  window.setTimeout(() => {
    waitForTask(taskId, host)
      .then((result) => {
        if (result && isActiveCaseStep(caseId, step)) return refresh();
        return null;
      })
      .catch((error) => {
        if (isActiveCaseStep(caseId, step)) showError(error, host);
      });
  }, 0);
}

function categoryLabel(value) {
  return { FOUNDATION: "Nền tảng", APPLICATION: "Ứng dụng", DEEP_DIVE: "Chuyên sâu" }[value] || safeText(value);
}

function questionGroups(questions) {
  const hasCategory = questions.length > 0 && questions.every((question) => typeof question.questionCategory === "string" && question.questionCategory.trim());
  if (!hasCategory) return [{ key: "ALL", label: "Tất cả câu hỏi", items: questions }];
  const order = ["FOUNDATION", "APPLICATION", "DEEP_DIVE"];
  const groups = [];
  for (const key of order) {
    const items = questions.filter((question) => question.questionCategory === key);
    if (items.length) groups.push({ key, label: categoryLabel(key), items });
  }
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

function renderQuestionDetail(question, questionSet, caseId, onRefresh) {
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
  if (questionSet.status !== "APPROVED") {
    const edit = element("details");
    const summary = element("summary", "Chỉnh sửa nội dung câu hỏi");
    const form = element("form", undefined, "stack");
    const text = field("Nội dung câu hỏi", "questionText", { type: "textarea", value: question.questionText, required: true });
    const purpose = field("Mục đích", "purpose", { type: "textarea", value: question.purpose, required: true });
    const objective = field("Mục tiêu bước tiếp theo", "nextStepObjective", { type: "textarea", value: question.nextStepObjective, required: true });
    const evidence = field("Bằng chứng cần tìm", "expectedEvidence", { type: "textarea", value: question.expectedEvidence, required: true });
    const save = element("button", "Lưu chỉnh sửa", "primary");
    save.type = "submit";
    form.append(text.label, purpose.label, objective.label, evidence.label, save);
    formSubmit(form, async () => {
      const questions = questionSet.questions.map((item) => item.id === question.id ? {
        ...item,
        questionText: text.input.value.trim(),
        purpose: purpose.input.value.trim(),
        nextStepObjective: objective.input.value.trim(),
        expectedEvidence: evidence.input.value.trim(),
      } : item);
      await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/question-set", {
        method: "PATCH",
        body: JSON.stringify({ questionSetId: questionSet.id, questions }),
      });
      await onRefresh();
    });
    edit.append(summary, form);
    detail.append(edit);
  }
  return detail;
}

function renderQuestionWorkspace(questionSet, caseId, onRefresh) {
  const questions = [...(questionSet.questions || [])].sort((a, b) => a.displayOrder - b.displayOrder);
  const workspace = element("div", undefined, "master-detail");
  const master = element("div", undefined, "master-list");
  const detailHost = element("div", undefined, "detail-panel");
  master.setAttribute("role", "tablist");
  detailHost.id = "question-detail-panel";
  detailHost.setAttribute("role", "tabpanel");
  workspace.append(master, detailHost);
  let selectedId = questions[0]?.id;
  let restoreFocusId = null;
  const redraw = () => {
    master.replaceChildren();
    for (const group of questionGroups(questions)) {
      if (group.key !== "ALL") master.append(element("h3", group.label));
      for (const question of group.items) {
        const item = button("", () => {
          selectedId = question.id;
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
        master.append(item);
      }
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
    }) : element("p", "Chưa có câu hỏi.", "muted"));
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
      if (item.activeTaskId && item.refinedFlowStatus === "QUESTIONS_GENERATING") {
        resumeTask(caseId, "questions", item.activeTaskId, taskHost, () => renderQuestions(caseId));
      }
      const generate = button("Sinh bộ câu hỏi bằng AI", async () => {
        const task = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/question-set", {
          method: "POST",
          body: JSON.stringify({ operation: "GENERATE" }),
        });
        setState({ activeTaskId: task.taskId });
        await waitForTask(task.taskId, taskHost);
        if (!isActiveCaseStep(caseId, "questions")) return;
        await renderQuestions(caseId);
      }, "primary");
      const canGenerate = ["DOCUMENTS_READY", "QUESTION_GENERATION_FAILED"].includes(item.refinedFlowStatus);
      generate.disabled = !canGenerate;
      const manual = button("Tạo bản nháp thủ công", () => renderManualDraft(caseId), "secondary");
      manual.disabled = !canGenerate;
      empty.append(generate, manual, taskHost);
      if (!canGenerate) empty.append(element("p", "Cần xác nhận đủ JD và CV trước khi tạo Question Set.", "muted"));
      view.append(empty);
      return view;
    }

    const overview = element("section", undefined, "card stack");
    const overviewTop = element("div", undefined, "actions");
    overviewTop.append(element("span", "Version " + questionSet.versionNo, "badge"), statusBadge(questionSet.status), element("span", questionSet.questions.length + " câu", "badge"), element("span", formatDuration(questionSet.durationSeconds), "badge"));
    const questionPolicy = questionSet.questionPolicy || {};
    overview.append(overviewTop, element("p", "Số lượng hiển thị lấy trực tiếp từ dữ liệu question set; không hardcode theo layout.", "muted"));
    if (questionPolicy.confidence !== undefined || questionPolicy.limitations?.length) {
      const quality = element("div", undefined, "notice");
      quality.append(element("span", "AI confidence: " + formatConfidence(questionPolicy.confidence)));
      if (questionPolicy.limitations?.length) quality.append(element("p", "Giới hạn: " + questionPolicy.limitations.join("; "), "muted"));
      overview.append(quality);
    }
    view.append(overview, renderQuestionWorkspace(questionSet, caseId, async () => renderQuestions(caseId)));

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
    const exportButton = button("Excel fallback: xuất bộ câu hỏi", async () => {
      const downloaded = await apiDownload("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/question-set/export", { method: "POST" });
      saveDownload(downloaded.blob, downloaded.response.headers.get("Content-Disposition") || "question-answer.xlsx");
      location.hash = stepHref(caseId, "answers").slice(1);
    }, "secondary");
    actions.append(exportHtmlButton, exportButton, link("Tiếp: Câu trả lời", stepHref(caseId, "answers"), "link-button"));
    view.append(actions);
    return view;
  });
}

function saveDownload(blob, contentDisposition) {
  const match = /filename="?([^";]+)"?/i.exec(contentDisposition || "");
  const filename = match ? match[1] : "question-answer.xlsx";
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
    const importCard = element("section", undefined, "card stack transfer-card");
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

    const excelFallback = element("section", undefined, "card stack transfer-fallback");
    excelFallback.append(element("h2", "Excel fallback"), element("p", "Dùng khi cần xử lý thủ công bằng workbook .xlsx.", "muted"));
    const file = document.createElement("input");
    file.type = "file";
    file.accept = ".xlsx";
    file.name = "question-answer-workbook";
    let importIdempotencyKey = null;
    file.addEventListener("change", () => { importIdempotencyKey = null; });
    const label = element("label", "Excel fallback .xlsx");
    label.append(file);
    const taskNote = element("div", undefined, "stack");
    const importButton = button("Import workbook", async () => {
      const workbook = file.files?.[0];
      if (!workbook) throw new Error("Hãy chọn file .xlsx");
      if (!workbook.name.toLowerCase().endsWith(".xlsx")) throw new Error("Chỉ hỗ trợ file .xlsx");
      if (workbook.size > MAX_WORKBOOK_BYTES) throw new Error("Workbook vượt quá 10 MB");
      importIdempotencyKey ||= globalThis.crypto?.randomUUID?.() || "ui-upload-" + Date.now() + "-" + Math.random().toString(16).slice(2);
      const result = await apiUpload("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/assessment-snapshots/import", workbook, {
        headers: { "X-Idempotency-Key": importIdempotencyKey },
      });
      setState({ currentSnapshotId: result.snapshot.id });
      await renderAnswers(caseId);
    }, "primary");
    excelFallback.append(label, importButton, taskNote);
    view.append(importCard, excelFallback);
    if (snapshot) {
      view.append(renderSnapshotWorkspace(snapshot));
      view.append(element("div", "Snapshot là immutable; AI sẽ đánh giá đúng snapshot đang hiển thị.", "notice"));
      view.append(link("Tiếp: Đánh giá AI", stepHref(caseId, "ai"), "link-button"));
    } else {
      view.append(element("section", "Chưa có assessment snapshot. Hãy import candidate HTML hoặc dùng Excel fallback.", "empty-state"));
    }
    return view;
  });
}

function renderListSection(title, values) {
  const section = element("section", undefined, "stack");
  section.append(element("h2", title));
  const list = document.createElement("ul");
  for (const value of values || []) list.append(element("li", safeText(value)));
  section.append(list);
  return section;
}

function renderEvaluationResult(result, snapshot) {
  const payload = result.payload || {};
  const section = element("div", undefined, "stack");
  const header = element("section", undefined, "card stack");
  const meta = element("div", undefined, "actions");
  meta.append(element("span", "Result v" + safeText(result.versionNo), "badge success"), element("span", safeText(payload.schemaVersion), "badge"), element("span", "Confidence: " + formatConfidence(result.confidence ?? payload.confidence), "badge"));
  if (result.provider) meta.append(element("span", safeText(result.provider), "badge"));
  if (result.model) meta.append(element("span", safeText(result.model), "badge"));
  header.append(meta, element("p", "Kết quả AI chỉ là thông tin hỗ trợ; HĐCM là bên đưa ra đánh giá cuối cùng.", "notice warning"));
  section.append(header);

  const answeredCount = (snapshot.answers || []).filter((answer) => answer.isAnswered).length;
  const metricGrid = element("div", undefined, "metric-grid");
  for (const metric of [["Đã trả lời", answeredCount + "/" + snapshot.questions.length], ["Độ tin cậy", formatConfidence(result.confidence ?? payload.confidence)], ["Snapshot", "v" + snapshot.versionNo]]) {
    const card = element("div", undefined, "metric");
    card.append(element("span", metric[0], "muted"), element("span", metric[1], "metric-value"));
    metricGrid.append(card);
  }
  section.append(metricGrid);
  const summaryGrid = element("div", undefined, "content-grid");
  summaryGrid.append(renderListSection("Điểm mạnh", payload.strengths), renderListSection("Khoảng trống", payload.gaps));
  section.append(summaryGrid);
  const signalsGrid = element("div", undefined, "content-grid");
  signalsGrid.append(renderListSection("Mâu thuẫn cần xem xét", payload.conflicts), renderListSection("Rủi ro", payload.risks));
  section.append(signalsGrid);

  const competencies = element("section", undefined, "card stack");
  competencies.append(element("h2", "Ma trận năng lực"));
  const competencyTable = element("div", undefined, "table-wrap");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const row = document.createElement("tr");
  for (const label of ["Năng lực", "Tóm tắt", "Bằng chứng", "Confidence"]) row.append(element("th", label));
  head.append(row);
  const body = document.createElement("tbody");
  for (const item of payload.competencyEvaluations || []) {
    const line = document.createElement("tr");
    line.append(element("td", item.competencyKey), element("td", item.summary), element("td", item.evidenceStatus), element("td", formatConfidence(item.confidence)));
    body.append(line);
  }
  table.append(head, body);
  competencyTable.append(table);
  competencies.append(competencyTable);
  section.append(competencies);

  const answers = element("section", undefined, "stack");
  answers.append(element("h2", "Chi tiết theo câu trả lời"));
  const sourceAnswers = new Map((snapshot.answers || []).map((answer) => [answer.questionId, answer]));
  const sourceQuestions = new Map((snapshot.questions || []).map((question) => [question.questionId, question]));
  for (const item of payload.perAnswerEvaluations || []) {
    const original = sourceAnswers.get(item.questionId);
    const question = sourceQuestions.get(item.questionId);
    const card = element("article", undefined, "card stack");
    const scoreLabel = item.score === null ? "NOT_ASSESSED" : "Score: " + safeText(item.score);
    card.append(element("h3", safeText(question?.displayOrder) + ". " + safeText(question?.questionText)), element("span", safeText(item.evidenceStatus), "badge " + (item.evidenceStatus === "NOT_ASSESSED" ? "warning" : "success")), element("span", scoreLabel, "badge"));
    const columns = element("div", undefined, "answer-columns");
    columns.append(
      element("div", undefined, "stack"),
      element("div", undefined, "stack"),
    );
    columns.children[0].append(element("strong", "Câu trả lời gốc"), element("div", original?.answerText || "NOT_ASSESSED", "answer-text"));
    columns.children[1].append(element("strong", "Reasoning / Evidence"), element("div", safeText(item.reasoning), "answer-text"), element("p", "Evidence: " + safeText((item.evidenceFound || []).join(", "))), element("p", "CV consistency: " + safeText(item.cvConsistency)));
    if (item.concerns?.length) columns.children[1].append(renderListSection("Concerns", item.concerns));
    card.append(columns);
    answers.append(card);
  }
  section.append(answers);
  if (payload.limitations?.length) section.append(renderListSection("Giới hạn của kết quả", payload.limitations));
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
    const actionCard = element("section", undefined, "card stack");
    actionCard.append(element("h2", "Đánh giá dựa trên snapshot v" + snapshot.versionNo), element("p", "AI nhận JD/CV đã xác nhận và nội dung snapshot; không tự đưa ra PASS/FAIL.", "muted"));
    if (resultUsesOlderSnapshot) {
      actionCard.append(element("div", "Đang hiển thị kết quả AI của snapshot v" + resultSnapshot.versionNo + "; snapshot hiện hành là v" + snapshot.versionNo + ".", "notice warning"));
    }
    const taskHost = element("div", undefined, "stack");
    if (item.activeTaskId && item.refinedFlowStatus === "AI_ANALYZING" && !result) {
      resumeTask(caseId, "ai", item.activeTaskId, taskHost, () => renderAI(caseId));
    }
    const action = button(result ? "Chạy đánh giá lại" : "Bắt đầu đánh giá bằng AI", async () => {
      const task = await apiFetch("/api/v1/interview-cases/" + encodeURIComponent(caseId) + "/ai/evaluate", {
        method: "POST",
        body: JSON.stringify({ snapshotId: snapshot.id, forceRerun: Boolean(result) }),
      });
      setState({ activeTaskId: task.taskId });
      await waitForTask(task.taskId, taskHost);
      if (!isActiveCaseStep(caseId, "ai")) return;
      await renderAI(caseId);
    }, "primary");
    if (item.refinedFlowStatus === "AI_ANALYZING" && !result) {
      actionCard.append(element("div", "AI task đang chạy hoặc đang được materialize. Không tạo task mới; hãy refresh để kiểm tra.", "notice warning"));
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
