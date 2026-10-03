import { getState } from "./store.js";

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function apiFetch(path, options = {}) {
  const state = getState();
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (state.committeeSession && !headers["X-Candidate-Token"]) {
    headers["X-Committee-Session"] = state.committeeSession;
  }
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && state.startupToken) {
    headers["X-Startup-Token"] = state.startupToken;
    headers["X-Idempotency-Key"] ||= headers["Idempotency-Key"] || crypto.randomUUID();
  }
  const response = await fetch(path, { ...options, method, headers, cache: "no-store" });
  const payload = response.status === 204 ? null : await response.json();
  if (!response.ok || (payload && !payload.success)) {
    const error = payload?.error || { code: "NETWORK_ERROR", message: "Không thể hoàn tất yêu cầu" };
    throw new ApiError(error.code, error.message, response.status);
  }
  return payload?.data;
}
