import { registerRoute, startRouter } from "./router.js";
import { renderHome } from "./views/home.js";

const main = document.querySelector("#main-content");
const navigation = document.querySelector("#primary-navigation");
const casesLink = document.createElement("a");
casesLink.href = "#/cases";
casesLink.textContent = "Interview Cases";
navigation.replaceChildren(casesLink);

registerRoute("/cases", () => renderHome(main));
startRouter((route) => {
  const message = document.createElement("p");
  message.textContent = `Không tìm thấy màn hình: ${route}`;
  main.replaceChildren(message);
});
