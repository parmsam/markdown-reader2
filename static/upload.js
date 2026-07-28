// "Add an article" -> upload-a-file dropzone. Guarded on element presence
// like library.js/theme.js, so it's harmless to load on every page. The
// native <input type="file"> covers the whole dropzone (see style.css) and
// stays fully functional -- browsers already accept a dropped file directly
// on a file input and open the native picker on click/tap -- this file only
// adds the visual drag-over state and a friendly "selected: <name>" label.
(function () {
  "use strict";

  document.querySelectorAll(".file-dropzone").forEach((zone) => {
    const input = zone.querySelector('input[type="file"]');
    const hint = zone.querySelector(".file-drop-hint");
    const nameEl = zone.querySelector(".file-drop-name");
    if (!input || !hint || !nameEl) return;
    // The folder-upload dropzone (below) handles its own change/count/hint
    // display and doesn't support drag-drop the way a single-file input
    // does (browsers don't reliably accept a dropped *directory* on a
    // webkitdirectory input without separate directory-walking code) --
    // skip it here rather than fight over the same elements.
    if (input.webkitdirectory) return;

    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (file) {
        nameEl.textContent = file.name;
        nameEl.hidden = false;
        hint.textContent = "Selected -- tap/click to change";
      } else {
        nameEl.hidden = true;
        hint.textContent = "Drop a file here, or tap to browse";
      }
    });

    ["dragenter", "dragover"].forEach((evt) => {
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((evt) => {
      zone.addEventListener(evt, () => zone.classList.remove("dragover"));
    });
  });

  // Folder upload: multi-file summary + auto-suggested folder-name prefix +
  // fetch()-based submission. A plain native <form> submission of a
  // webkitdirectory input only sends each file's bare basename to the
  // server -- webkitRelativePath is a JS-only File property -- so the only
  // way to preserve the picked folder's structure server-side is to build
  // the multipart request by hand here, explicitly setting each part's
  // filename to file.webkitRelativePath (see app.py's
  // post_articles_upload_folder docstring for the server side of this).
  const folderInput = document.getElementById("folder-upload-input");
  const folderForm = document.getElementById("folder-upload-form");
  if (folderInput && folderForm) {
    const prefixInput = document.getElementById("folder-prefix-input");
    const zone = folderInput.closest(".file-dropzone");
    const hint = zone.querySelector(".file-drop-hint");
    const nameEl = zone.querySelector(".file-drop-name");

    folderInput.addEventListener("change", () => {
      const files = Array.from(folderInput.files || []);
      if (!files.length) {
        nameEl.hidden = true;
        hint.textContent = "Tap to choose a folder";
        return;
      }
      const topFolder = (files[0].webkitRelativePath || files[0].name).split("/")[0];
      nameEl.textContent = `${topFolder} (${files.length} file${files.length === 1 ? "" : "s"})`;
      nameEl.hidden = false;
      hint.textContent = "Selected -- tap/click to change";
      if (!prefixInput.value) prefixInput.placeholder = topFolder;
    });

    folderForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const files = Array.from(folderInput.files || []);
      if (!files.length) return;

      const formData = new FormData();
      for (const file of files) {
        formData.append("file", file, file.webkitRelativePath || file.name);
      }
      formData.append("folder_prefix", prefixInput.value);

      const submitBtn = folderForm.querySelector('button[type="submit"]');
      const originalLabel = submitBtn.textContent;
      submitBtn.disabled = true;
      submitBtn.textContent = "Uploading…";
      try {
        const resp = await fetch(folderForm.action, { method: "POST", body: formData });
        window.location = resp.url; // fetch follows the 303 redirect itself
      } catch (err) {
        console.error("Folder upload failed:", err);
        submitBtn.disabled = false;
        submitBtn.textContent = originalLabel;
        alert("Folder upload failed -- check your connection and try again.");
      }
    });
  }
})();
