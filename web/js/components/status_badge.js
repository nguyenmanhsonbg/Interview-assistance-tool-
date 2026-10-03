export function createStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = "status-badge";
  badge.textContent = String(status || "UNKNOWN");
  return badge;
}
