// Loaded as a plain blocking script in <head>, so the page never flashes the wrong theme.
// The choice (system, light or dark) is remembered per browser; "system" follows the device.
(function () {
  const KEY = "pata-theme";
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const listeners = new Set();

  function stored() {
    try { return localStorage.getItem(KEY) || "system"; } catch { return "system"; }
  }
  function resolve(choice) {
    return choice === "system" ? (media.matches ? "dark" : "light") : choice;
  }
  function apply() {
    const theme = resolve(stored());
    if (document.documentElement.dataset.theme !== theme) {
      document.documentElement.dataset.theme = theme;
      listeners.forEach((fn) => fn(theme));
    }
  }

  window.pataTheme = {
    choice: stored,
    current: () => resolve(stored()),
    set(choice) {
      try { localStorage.setItem(KEY, choice); } catch { /* private mode: still switch for this page */ }
      document.documentElement.dataset.themeChoice = choice;
      apply();
      listeners.forEach((fn) => fn(resolve(choice)));
    },
    onChange(fn) { listeners.add(fn); },
  };

  document.documentElement.dataset.themeChoice = stored();
  media.addEventListener("change", apply);
  // Another tab (the other phone window on the same laptop) changed the theme.
  window.addEventListener("storage", (event) => {
    if (event.key !== KEY) return;
    document.documentElement.dataset.themeChoice = stored();
    apply();
    listeners.forEach((fn) => fn(resolve(stored())));
  });
  apply();
})();
