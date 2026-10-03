const routes = [];

export function registerRoute(pattern, render) {
  const keys = [];
  const expression = pattern.replace(/:([A-Za-z0-9_]+)/g, (_, key) => {
    keys.push(key);
    return "([^/]+)";
  });
  routes.push({ regex: new RegExp(`^${expression}$`), keys, render });
}

export function startRouter(fallback) {
  const run = async () => {
    const route = location.hash.slice(1).split("?", 1)[0] || "/cases";
    for (const item of routes) {
      const match = item.regex.exec(route);
      if (match) {
        const params = Object.fromEntries(item.keys.map((key, index) => [key, decodeURIComponent(match[index + 1])]));
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
  const main = document.querySelector("#main-content");
  const message = document.createElement("p");
  message.className = "error card";
  message.textContent = `${error.code || "ERROR"}: ${error.message}`;
  main.replaceChildren(message);
}
