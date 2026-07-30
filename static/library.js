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

  // Manual "check for updates" -- lives in the navbar so it's available on
  // every page (unlike the passive library-page banner, see components.py's
  // library_page). A hit turns the link itself into a link to the release;
  // a miss/failure just flashes a status before reverting.
  document.addEventListener("click", async (e) => {
    const link = e.target.closest("#check-update-link");
    if (!link) return;
    e.preventDefault();

    const original = link.textContent;
    link.textContent = "Checking…";
    try {
      const resp = await fetch("/api/check-update");
      const data = await resp.json();
      if (data.update) {
        link.textContent = `v${data.update} available`;
        link.href = data.url;
        link.target = "_blank";
        link.rel = "noopener";
        return;
      }
      link.textContent = "Up to date";
    } catch (err) {
      console.error("Update check failed:", err);
      link.textContent = "Check failed";
    }
    setTimeout(() => { link.textContent = original; }, 2000);
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
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".folder-rename-btn");
    if (!btn) return;

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

  // Delete a folder -- Finder-style: this permanently deletes every article
  // (and cached audio) inside the folder and its sub-folders, not just the
  // grouping. The confirm() names the article count so this reads as
  // clearly destructive before it happens.
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".folder-delete-btn");
    if (!btn) return;

    const path = btn.getAttribute("data-folder-path");
    const count = btn.getAttribute("data-folder-count");
    if (!confirm(`Delete folder "${path}" and permanently delete ${count} article${count === "1" ? "" : "s"} inside it (including cached audio)? This cannot be undone.`)) return;

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

  document.addEventListener("change", (e) => {
    const select = e.target.closest(".folder-sort-select");
    if (select) select.form.submit();
  });

  // ---- kebab ("⋯") menus: article-row and folder-header actions, both
  // driven by the native Popover API (see components.py's _article_row /
  // _render_folder_node) ----

  // A folder's kebab button lives inside its <summary>, so a plain click
  // would also toggle the <details> open/closed the way any click inside a
  // <summary> does. stopPropagation() (not preventDefault()) is the fix --
  // preventDefault() on this click also cancels the popovertarget button's
  // own default action (showing the popover), since both are driven by the
  // same click event; stopPropagation() only keeps the click from ever
  // bubbling up to <summary>, leaving the popover's own behavior intact.
  // Harmless no-op for article-row kebabs, which aren't inside a <summary>.
  document.addEventListener("click", (e) => {
    if (e.target.closest(".kebab-btn")) e.stopPropagation();
  });

  // Position each popover menu near the button that opened it. There's no
  // cross-browser way to CSS-anchor a [popover] to its trigger yet (CSS
  // anchor positioning isn't in Safari), so this does it in JS instead, on
  // the (non-bubbling, hence the capture-phase listener) `toggle` event
  // every popover fires when its state changes.
  document.addEventListener("toggle", (e) => {
    const menu = e.target;
    if (!(menu instanceof Element) || !menu.hasAttribute("popover")) return;
    if (e.newState !== "open") return;
    const trigger = document.querySelector(`[popovertarget="${menu.id}"]`);
    if (!trigger) return;

    const btnRect = trigger.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const margin = 8;
    let left = btnRect.right - menuRect.width;
    left = Math.max(margin, Math.min(left, window.innerWidth - menuRect.width - margin));
    let top = btnRect.bottom + 4;
    if (top + menuRect.height > window.innerHeight - margin) {
      top = btnRect.top - menuRect.height - 4; // flip above if it wouldn't fit below
    }
    menu.style.left = `${left}px`;
    menu.style.top = `${Math.max(margin, top)}px`;
  }, true);
})();
