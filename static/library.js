// Library page interactions (delete, copy-LAN-url). Plain fetch()/DOM -- no
// htmx, no build step, consistent with player.js and the rest of this app's
// no-external-JS approach (this app is meant to run fully on-device with no
// CDN dependency).
(function () {
  "use strict";

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-delete-id]");
    if (!btn) return;

    if (!confirm("Delete this article and its cached audio?")) return;

    const id = btn.getAttribute("data-delete-id");
    try {
      const resp = await fetch(`/article/${id}`, { method: "DELETE" });
      if (!resp.ok) {
        alert("Failed to delete article.");
        return;
      }
      const row = btn.closest(".article-row");
      if (row) row.remove();
    } catch (err) {
      console.error("Delete failed:", err);
      alert("Failed to delete article.");
    }
  });

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("#copy-lan-url");
    if (!btn) return;

    const url = btn.getAttribute("data-url");
    const original = btn.textContent;
    try {
      await navigator.clipboard.writeText(url);
      btn.textContent = "Copied!";
    } catch (err) {
      console.error("Clipboard copy failed:", err);
      btn.textContent = "Copy failed";
    }
    setTimeout(() => { btn.textContent = original; }, 1500);
  });
})();
