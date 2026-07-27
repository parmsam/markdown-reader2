// Library page interactions (delete). Plain fetch()/DOM -- no htmx, no build
// step, consistent with player.js and the rest of this app's no-external-JS
// approach (this app is meant to run fully on-device with no CDN dependency).
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
})();
