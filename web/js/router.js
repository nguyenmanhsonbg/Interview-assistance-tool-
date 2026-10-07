const routes = [];
let started = false;

export function registerRoute(pattern, render) {
  const keys = [];
  const expression = pattern.replace(/:([A-Za-z0-9_]+)/g, (_, key) => {
    keys.push(key);
    return "([^/]+)";
  });
  routes.push({ regex: new RegExp("^" + expression + "$"), keys, render });
}

export function currentRoute() {
  return location.hash.slice(1).split("?", 1)[0] || "/cases";
}

export function startRouter(fallback) {
  if (started) return;
  started = true;
  const run = async () => {
    const route = currentRoute();
    for (const item of routes) {
      const match = item.regex.exec(route);
      if (match) {
        const params = Object.fromEntries(
          item.keys.map((key, index) => [key, decodeURIComponent(match[index + 1])]),
        );
        await item.render(params);
        return;
      }
    }
    fallback(route);
  };
  window.addEventListener("hashchange", () => run().catch(showFatal));
  run().catch(showFatal);
}

function showFatal(error) {
  const app = document.querySelector("#app");
  const main = document.createElement("main");
  main.id = "main-content";
  main.className = "workspace-content";
  main.tabIndex = -1;
  const message = document.createElement("div");
  message.className = "notice error";
  message.setAttribute("role", "alert");
  message.textContent = (error.code || "ERROR") + ": " + (error.message || "Không thể tải màn hình");
  main.append(message);
  app.replaceChildren(main);
}
