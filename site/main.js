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

// The diagram plays the process: set_direction appends a version, and each
// agent picks it up at its own next step. Without JavaScript, or under
// prefers-reduced-motion, the mid-flight still in the markup is the frame.
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var eventEl = document.getElementById("flow-event");
  if (!eventEl || reduced.matches) return;

  var NOTES = ["pivot to SMB", "add the EU line", "focus on retention", "cut scope to core"];
  var version = 9;
  var agents = [1, 2, 3, 4].map(function (i) {
    return {
      group: document.getElementById("agent-" + i),
      chip: document.getElementById("agent-v-" + i),
      drop: document.getElementById("drop-" + i),
    };
  });
  var timers = [];
  function later(fn, ms) { timers.push(setTimeout(fn, ms)); }

  function setAgent(a, v, fresh) {
    a.chip.textContent = fresh ? "v" + v : "v" + v + " so far";
    a.group.setAttribute("class", fresh ? "agent fresh" : "agent stale");
    a.drop.setAttribute("class", fresh ? "pull" : "pull waiting");
    a.drop.setAttribute("marker-end", fresh ? "url(#arr)" : "url(#arr-stale)");
  }

  function setStore(v) {
    document.getElementById("ver-old1").textContent = "v" + (v - 2);
    document.getElementById("ver-old2").textContent = "v" + (v - 1);
    document.getElementById("ver-new").textContent = "v" + v + " new";
  }

  function cycle() {
    version += 1;
    setStore(version);
    eventEl.textContent =
      'set_direction(note="' + NOTES[version % NOTES.length] + '") → v' + version;
    agents.forEach(function (a) { setAgent(a, version - 1, false); });
    agents.forEach(function (a, n) {
      later(function () {
        setAgent(a, version, true);
        if (n === agents.length - 1) {
          later(function () {
            eventEl.textContent = "every agent is on v" + version + ", ready for the next change";
          }, 900);
          later(cycle, 5200);
        }
      }, 1100 + n * 1100);
    });
  }

  // Finish the frame the markup starts on: the reviewer pulls v9.
  later(function () {
    setAgent(agents[3], 9, true);
    eventEl.textContent = "every agent is on v9, ready for the next change";
  }, 1800);
  later(cycle, 4200);

  var onChange = function (e) {
    if (!e.matches) return;
    timers.forEach(clearTimeout);
  };
  if (reduced.addEventListener) reduced.addEventListener("change", onChange);
})();
