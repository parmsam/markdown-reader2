// Light/dark theme toggle, shared across every page (unlike player.js/
// library.js this isn't page-specific). components.py's _head() already sets
// data-theme from localStorage before first paint to avoid a flash of the
// wrong theme; this file just owns the toggle button's click handling and
// icon afterward. Cycle: system default -> light -> dark -> system default.
(function () {
  "use strict";

  const STORAGE_KEY = "theme";
  const root = document.documentElement;
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;

  function systemPrefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function effectiveTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return systemPrefersDark() ? "dark" : "light";
  }

  function updateIcon() {
    btn.textContent = effectiveTheme() === "dark" ? "☀️" : "🌙";
  }

  function setTheme(theme) {
    if (theme === "light" || theme === "dark") {
      localStorage.setItem(STORAGE_KEY, theme);
      root.setAttribute("data-theme", theme);
    } else {
      localStorage.removeItem(STORAGE_KEY);
      root.removeAttribute("data-theme");
    }
    updateIcon();
  }

  btn.addEventListener("click", () => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light") setTheme("dark");
    else if (stored === "dark") setTheme(null);
    else setTheme("light");
  });

  updateIcon();
})();
