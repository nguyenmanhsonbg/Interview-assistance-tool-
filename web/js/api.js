export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    cache: "no-store",
  });
  const payload = response.status === 204 ? null : await response.json();
  if (!response.ok || (payload && !payload.success)) {
    const error = payload?.error || { code: "NETWORK_ERROR", message: "Không thể hoàn tất yêu cầu" };
    throw new ApiError(error.code, error.message, response.status);
  }
  return payload?.data;
}
