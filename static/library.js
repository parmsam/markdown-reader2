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

  // Move-to-folder <select> per article row. The select itself has no
  // name= (see components.py's _folder_move_form) so it can't submit an
  // option value the browser doesn't already know about -- a sibling
  // hidden input carries whatever the actual target folder ends up being,
  // including a freshly-typed new folder name.
  document.addEventListener("change", (e) => {
    const select = e.target.closest(".folder-select");
    if (!select) return;
    const form = select.closest("form");
    const hidden = form.querySelector('input[name="folder"]');

    if (select.value === "__new__") {
      const name = window.prompt('New folder name (use "/" for nested, e.g. Notes/Work):');
      if (!name || !name.trim()) {
        select.value = hidden.value; // revert the visual selection
        return;
      }
      hidden.value = name.trim();
    } else {
      hidden.value = select.value;
    }
    form.submit();
  });

  // Rename a folder (and all its sub-folders, see db.py's rename_folder).
  // Lives on the <summary> row, so stop the click from also toggling the
  // <details> open/closed the way any other click inside a <summary> would.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".folder-rename-btn");
    if (!btn) return;
    e.preventDefault();

    const oldPath = btn.getAttribute("data-folder-path");
    const newPath = window.prompt(`Rename folder "${oldPath}" to:`, oldPath);
    if (!newPath || !newPath.trim() || newPath.trim() === oldPath) return;

    try {
      const resp = await fetch("/folders/rename", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `old_path=${encodeURIComponent(oldPath)}&new_path=${encodeURIComponent(newPath.trim())}`,
      });
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      location.reload();
    } catch (err) {
      console.error("Folder rename failed:", err);
      alert("Failed to rename folder.");
    }
  });

  // Delete a folder -- a folder is just a path string on an article (see
  // db.py's delete_folder), not a real container, so this only ever
  // dissolves the grouping: articles move back to the library root, never
  // deleted. The confirm() is explicit about that since "Delete" alone
  // could otherwise read as destroying the articles too.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".folder-delete-btn");
    if (!btn) return;
    e.preventDefault(); // don't also toggle the <details> open/closed

    const path = btn.getAttribute("data-folder-path");
    if (!confirm(`Remove folder "${path}"? Its articles move back to the library root -- they will NOT be deleted.`)) return;

    try {
      const resp = await fetch("/folders/delete", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `path=${encodeURIComponent(path)}`,
      });
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      window.location = resp.url; // fetch follows the redirect to /?notice=... itself
    } catch (err) {
      console.error("Folder delete failed:", err);
      alert("Failed to delete folder.");
    }
  });

  const sortSelect = document.getElementById("sort-select");
  if (sortSelect) sortSelect.addEventListener("change", () => sortSelect.form.submit());

  // Per-folder sort <select>, lives in a folder's <summary> just like the
  // Rename/Delete buttons -- same reason for the click guard: any click
  // inside a <summary> (including one to open this dropdown) otherwise also
  // toggles the <details> open/closed.
  document.addEventListener("click", (e) => {
    if (e.target.closest(".folder-sort-select")) e.preventDefault();
  });
  document.addEventListener("change", (e) => {
    const select = e.target.closest(".folder-sort-select");
    if (select) select.form.submit();
  });
})();
