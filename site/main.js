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
// agent picks it up at its own next step. It is one story, replayed: the
// versions stay v7..v10 so nobody reads the counter as Kyno's own version.
// Without JavaScript, or under prefers-reduced-motion, the mid-flight still
// in the markup is the frame.
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var eventEl = document.getElementById("flow-event");
  var svg = document.querySelector(".flow-card svg");
  if (!eventEl || !svg || reduced.matches) return;

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

  function baseline() {
    setStore(9);
    agents.forEach(function (a) { setAgent(a, 9, true); });
    agents[3].chip.textContent = "v8 → pulls next";
    agents[3].group.setAttribute("class", "agent stale");
    agents[3].drop.setAttribute("class", "pull waiting");
    agents[3].drop.setAttribute("marker-end", "url(#arr-stale)");
    eventEl.textContent = "mid-flight: three agents already on v9, the reviewer picks it up at its next step";
  }

  function play() {
    later(function () {
      setAgent(agents[3], 9, true);
      eventEl.textContent = "every agent is on v9, ready for the next change";
    }, 2000);

    later(function () {
      setStore(10);
      eventEl.textContent = 'set_direction(note="pivot to SMB") → v10';
      agents.forEach(function (a) { setAgent(a, 9, false); });
      agents.forEach(function (a, n) {
        later(function () {
          setAgent(a, 10, true);
          if (n === agents.length - 1) {
            eventEl.textContent = "every agent is on v10. The demo replays from here.";
          }
        }, 1100 + n * 1100);
      });
    }, 4600);

    later(function () {
      svg.classList.add("replay");
      later(function () {
        baseline();
        svg.classList.remove("replay");
        play();
      }, 450);
    }, 14200);
  }

  play();

  var onChange = function (e) {
    if (!e.matches) return;
    timers.forEach(clearTimeout);
    timers = [];
    baseline();
  };
  if (reduced.addEventListener) reduced.addEventListener("change", onChange);
})();
