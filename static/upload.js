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
})();
