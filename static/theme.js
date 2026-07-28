// Light/dark theme toggle, shared across every page (unlike player.js/
// library.js this isn't page-specific). components.py's _head() already sets
// data-theme from localStorage before first paint to avoid a flash of the
// wrong theme; this file just owns the toggle button's click handling and
// icon afterward. Cycle: system default -> light -> dark -> system default.
(function () {
  "use strict";

  const STORAGE_KEY = "theme";
  // Mirrors style.css's --bg for light/dark -- keeps the browser's address
  // bar / status bar tint (Android Chrome, and standalone-mode iOS) in sync
  // with the effective theme, since a <meta name="theme-color"> can't
  // itself react to our data-theme override the way CSS custom properties do.
  const BG_BY_THEME = { light: "#ffffff", dark: "#16181d" };
  const root = document.documentElement;
  const btn = document.getElementById("theme-toggle");
  const themeColorMeta = document.getElementById("theme-color-meta");

  function systemPrefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function effectiveTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return systemPrefersDark() ? "dark" : "light";
  }

  function updateThemeUI() {
    const theme = effectiveTheme();
    if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";
    if (themeColorMeta) themeColorMeta.setAttribute("content", BG_BY_THEME[theme]);
  }

  function setTheme(theme) {
    if (theme === "light" || theme === "dark") {
      localStorage.setItem(STORAGE_KEY, theme);
      root.setAttribute("data-theme", theme);
    } else {
      localStorage.removeItem(STORAGE_KEY);
      root.removeAttribute("data-theme");
    }
    updateThemeUI();
  }

  if (btn) {
    btn.addEventListener("click", () => {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "light") setTheme("dark");
      else if (stored === "dark") setTheme(null);
      else setTheme("light");
    });
  }

  updateThemeUI();
})();
