// The one motion moment: set_direction fires, and each agent chip flips
// v8 -> v9 on its own next pull. Under prefers-reduced-motion the final
// frame renders immediately and nothing animates.
(function () {
  "use strict";

  var CALL_HTML =
    '<span class="fn">set_direction</span>(mission="…", note="pivot to SMB")' +
    ' <span class="ret">→ v9</span>';
  var CALL_PLAIN = 'set_direction(mission="…", note="pivot to SMB") → v9';

  var ticker = document.getElementById("ticker");
  var callEl = document.getElementById("call-text");
  var chips = Array.prototype.slice.call(document.querySelectorAll("#chips .chip"));

  function finalFrame() {
    callEl.innerHTML = CALL_HTML;
    chips.forEach(function (chip) {
      chip.classList.add("fresh");
      chip.querySelector(".v").textContent = "v9";
    });
  }

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (reduced.matches) {
    finalFrame();
    return;
  }

  var timers = [];
  function later(fn, ms) { timers.push(setTimeout(fn, ms)); }

  function reset() {
    callEl.textContent = "";
    chips.forEach(function (chip) {
      chip.classList.remove("fresh");
      chip.querySelector(".v").textContent = "v8";
    });
  }

  function cycle() {
    reset();
    ticker.classList.add("typing");
    var i = 0;
    (function type() {
      if (i <= CALL_PLAIN.length) {
        callEl.textContent = CALL_PLAIN.slice(0, i);
        i += 2;
        later(type, 24);
        return;
      }
      ticker.classList.remove("typing");
      callEl.innerHTML = CALL_HTML;
      chips.forEach(function (chip, n) {
        later(function () {
          chip.classList.add("fresh");
          chip.querySelector(".v").textContent = "v9";
        }, 350 + n * 320);
      });
      // Hold the settled state long enough to read before looping.
      later(cycle, 350 + chips.length * 320 + 6000);
    })();
  }

  cycle();

  // If the preference flips while the page is open, settle immediately.
  var onChange = function (e) {
    if (!e.matches) return;
    timers.forEach(clearTimeout);
    ticker.classList.remove("typing");
    finalFrame();
  };
  if (reduced.addEventListener) reduced.addEventListener("change", onChange);
})();

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
