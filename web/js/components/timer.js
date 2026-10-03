export function createTimer(expiresAt, onExpired) {
  const element = document.createElement("p");
  element.setAttribute("role", "timer");
  element.setAttribute("aria-live", "polite");
  let interval = null;
  const update = () => {
    const remaining = Math.max(0, Math.ceil((Date.parse(expiresAt) - Date.now()) / 1000));
    const minutes = Math.floor(remaining / 60);
    const seconds = String(remaining % 60).padStart(2, "0");
    element.textContent = `Thời gian còn lại: ${minutes}:${seconds}`;
    if (remaining === 0 && interval !== null) {
      clearInterval(interval);
      interval = null;
      onExpired();
    }
  };
  update();
  interval = window.setInterval(update, 1000);
  return { element, stop: () => { if (interval !== null) clearInterval(interval); } };
}
