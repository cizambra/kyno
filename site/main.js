// Copy buttons: write the command, confirm briefly, never navigate.
(function () {
  "use strict";
  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(btn.getAttribute("data-copy")).then(function () {
        var was = btn.textContent;
        btn.textContent = "copied";
        setTimeout(function () { btn.textContent = was; }, 1400);
      });
    });
  });
})();
