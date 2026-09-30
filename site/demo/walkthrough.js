(() => {
  "use strict";
  const root = document.getElementById("walkthrough");
  if (!root) return;
  const screens = Array.from(root.querySelectorAll("[data-walkthrough-screen]"));
  const steps = Array.from(root.querySelectorAll("[data-walkthrough-step]"));
  const previous = root.querySelector("#walkthrough-back");
  const next = root.querySelector("#walkthrough-next");
  const picker = root.querySelector("#walkthrough-picker");
  const counter = root.querySelector("#walkthrough-counter");
  if (!screens.length || !previous || !next || !picker || !counter) return;
  let index = 0;

  function showStep(value) {
    if (!Number.isInteger(value) || value < 0 || value >= screens.length) return;
    index = value;
    screens.forEach((screen, position) => { screen.hidden = position !== index; });
    steps.forEach((button, position) => {
      if (position === index) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    previous.disabled = index === 0;
    picker.value = String(index);
    counter.textContent = `Step ${index + 1} of ${screens.length}`;
    next.textContent = index === screens.length - 1
      ? "Start again"
      : `Next: ${screens[index + 1].dataset.nextLabel}`;
  }

  previous.addEventListener("click", () => showStep(Math.max(0, index - 1)));
  next.addEventListener("click", () => showStep((index + 1) % screens.length));
  picker.addEventListener("change", () => showStep(Number(picker.value)));
  steps.forEach(button => button.addEventListener("click", () => {
    showStep(Number(button.dataset.walkthroughStep));
  }));
  showStep(0);
  root.classList.add("is-interactive");
  root.querySelectorAll("[data-walkthrough-controls]").forEach(control => {
    control.hidden = false;
  });
})();
