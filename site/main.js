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
// agent picks it up at its own next step. One bounded story on a loop:
// everyone starts on v7, the operator appends v8, then v9, then v10, and
// the demo replays. Versions never leave v7..v10, so nobody reads the
// counter as Kyno's own version. Without JavaScript, or under
// prefers-reduced-motion, the mid-flight still in the markup is the frame.
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var eventEl = document.getElementById("flow-event");
  var svg = document.querySelector(".flow-card svg");
  var opArrow = document.getElementById("op-arrow");
  var operator = document.getElementById("operator");
  if (!eventEl || !svg || reduced.matches) return;

  var CHANGES = {
    8: 'principle added: "Say the hard number first"',
    9: "mission rewritten for the EU launch",
    10: 'principle dropped: "Growth first"',
  };
  var agents = [1, 2, 3, 4].map(function (i) {
    return {
      group: document.getElementById("agent-" + i),
      chip: document.getElementById("agent-v-" + i),
      drop: document.getElementById("drop-" + i),
    };
  });
  var timers = [];

  function setAgent(a, v, fresh) {
    a.chip.textContent = fresh ? "v" + v : "v" + v + " so far";
    a.group.setAttribute("class", fresh ? "agent fresh" : "agent stale");
    a.drop.setAttribute("class", fresh ? "pull" : "pull waiting");
    a.drop.setAttribute("marker-end", fresh ? "url(#arr)" : "url(#arr-stale)");
  }

  function setStore(current, isNew) {
    var old1 = current - 2, old2 = current - 1;
    document.getElementById("ver-old1").textContent = old1 >= 7 ? "v" + old1 : "";
    document.getElementById("ver-old2").textContent = old2 >= 7 ? "v" + old2 : "";
    document.getElementById("ver-new").textContent = "v" + current + (isNew ? " new" : "");
  }

  // One timeline, replayed: [seconds from start, what happens].
  var steps = [];
  function at(sec, fn) { steps.push([sec * 1000, fn]); }

  at(0, function () {
    setStore(7, false);
    agents.forEach(function (a) { setAgent(a, 7, true); });
    eventEl.textContent = "four agents at work, every one of them on v7";
  });

  [8, 9, 10].forEach(function (v, round) {
    var base = 2.4 + round * 8.2;
    at(base, function () {
      operator.classList.add("acting");
      opArrow.classList.add("sending");
      eventEl.textContent = "operator: " + CHANGES[v];
    });
    at(base + 2.2, function () {
      setStore(v, true);
      eventEl.textContent = "kyno appends v" + v + ", every agent pulls it at its next step";
      agents.forEach(function (a) { setAgent(a, v - 1, false); });
    });
    at(base + 2.8, function () {
      operator.classList.remove("acting");
      opArrow.classList.remove("sending");
    });
    agents.forEach(function (a, n) {
      at(base + 3.0 + n * 0.9, function () { setAgent(a, v, true); });
    });
    at(base + 3.0 + agents.length * 0.9, function () {
      eventEl.textContent = "every agent is on v" + v;
    });
  });

  var CYCLE = 27.5 * 1000;

  function play() {
    steps.forEach(function (s) { timers.push(setTimeout(s[1], s[0])); });
    timers.push(setTimeout(function () {
      svg.classList.add("replay");
      timers.push(setTimeout(function () {
        svg.classList.remove("replay");
        timers = [];
        play();
      }, 450));
    }, CYCLE));
  }

  play();

  var onChange = function (e) {
    if (!e.matches) return;
    timers.forEach(clearTimeout);
    timers = [];
    svg.classList.remove("replay");
    setStore(9, true);
    agents.forEach(function (a) { setAgent(a, 9, true); });
    agents[3].chip.textContent = "v8 → pulls next";
    agents[3].group.setAttribute("class", "agent stale");
    agents[3].drop.setAttribute("class", "pull waiting");
    agents[3].drop.setAttribute("marker-end", "url(#arr-stale)");
    eventEl.textContent = "mid-flight: three agents already on v9, the reviewer picks it up at its next step";
  };
  if (reduced.addEventListener) reduced.addEventListener("change", onChange);
})();
