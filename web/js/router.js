const routes = new Map();

export function registerRoute(path, render) { routes.set(path, render); }

export function startRouter(fallback) {
  const render = () => {
    const route = location.hash.slice(1) || "/cases";
    (routes.get(route) || fallback)(route);
  };
  window.addEventListener("hashchange", render);
  render();
}
