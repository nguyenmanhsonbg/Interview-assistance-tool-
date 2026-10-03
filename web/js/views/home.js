export function renderHome(container) {
  const section = document.createElement("section");
  section.className = "card";
  const heading = document.createElement("h1");
  heading.textContent = "Supervised Interview Workspace";
  const copy = document.createElement("p");
  copy.className = "muted";
  copy.textContent = "Tạo Interview Case để bắt đầu chuẩn bị phiên phỏng vấn.";
  section.append(heading, copy);
  container.replaceChildren(section);
}
