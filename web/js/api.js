import { getState } from "./store.js";

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const MUTATION_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function requestHeaders(options, method, contentType) {
  const state = getState();
  const headers = { ...(options.headers || {}) };
  if (contentType && !headers["Content-Type"]) headers["Content-Type"] = contentType;
  if (state.committeeSession && !headers["X-Committee-Session"]) {
    headers["X-Committee-Session"] = state.committeeSession;
  }
  if (MUTATION_METHODS.has(method) && state.startupToken) {
    headers["X-Startup-Token"] = state.startupToken;
    headers["X-Idempotency-Key"] ||= headers["Idempotency-Key"] || makeIdempotencyKey();
  }
  return headers;
}

function makeIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "ui-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

async function parseResponse(response) {
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function throwResponseError(response, payload) {
  if (response.ok && (!payload || payload.success !== false)) return;
  if ((response.status === 401 || response.status === 403) && getState().committeeSession) {
    window.dispatchEvent(new CustomEvent("committee-session-expired"));
  }
  const error = payload?.error || { code: "NETWORK_ERROR", message: "Không thể hoàn tất yêu cầu" };
  throw new ApiError(error.code, error.message, response.status);
}

export async function apiFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const body = options.body;
  const headers = requestHeaders(options, method, body === undefined ? null : "application/json");
  const response = await fetch(path, { ...options, method, headers, cache: "no-store" });
  const payload = await parseResponse(response);
  throwResponseError(response, payload);
  return payload?.data;
}

export async function apiDownload(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = requestHeaders(options, method, null);
  const response = await fetch(path, { ...options, method, headers, cache: "no-store" });
  if (!response.ok) {
    const payload = await parseResponse(response);
    throwResponseError(response, payload);
  }
  return { blob: await response.blob(), response };
}

export async function apiUpload(path, blob, options = {}) {
  const method = (options.method || "POST").toUpperCase();
  const headers = requestHeaders(
    options,
    method,
    options.contentType || blob.type || "application/octet-stream",
  );
  const response = await fetch(path, { ...options, method, body: blob, headers, cache: "no-store" });
  const payload = await parseResponse(response);
  throwResponseError(response, payload);
  return payload?.data;
}
