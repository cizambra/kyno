const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");

const rootPath = process.argv[2];
const scenario = process.argv[3];
const html = fs.readFileSync(path.join(rootPath, "site/demo/index.html"), "utf8");
const script = fs.readFileSync(path.join(rootPath, "site/demo/walkthrough.js"), "utf8");
class Element {
  constructor() {
    this.hidden = false;
    this.disabled = false;
    this.dataset = {};
    this.attributes = {};
    this.handlers = {};
  }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  click() { if (!this.disabled) this.handlers.click(); }
}
const elements = Object.fromEntries(Array.from(html.matchAll(/id="([^"]+)"/g), m => [m[1], new Element()]));
const screens = Array.from(html.matchAll(/data-walkthrough-screen="(\d+)" data-next-label="([^"]+)"/g), m => {
  const element = new Element();
  element.dataset.walkthroughScreen = m[1];
  element.dataset.nextLabel = m[2];
  return element;
});
const steps = Array.from(html.matchAll(/data-walkthrough-step="(\d+)"/g), m => {
  const element = new Element();
  element.dataset.walkthroughStep = m[1];
  return element;
});
const controls = Array.from(html.matchAll(/data-walkthrough-controls hidden/g), () => {
  const element = new Element(); element.hidden = true; return element;
});
const root = elements.walkthrough;
root.classList = { add(value) { this.value = value; } };
root.querySelector = selector => elements[selector.slice(1)];
root.querySelectorAll = selector => ({
  "[data-walkthrough-screen]": screens,
  "[data-walkthrough-step]": steps,
  "[data-walkthrough-controls]": controls,
})[selector];
const document = { getElementById: id => elements[id] };
vm.runInNewContext(script, { document });
const back = elements["walkthrough-back"];
const next = elements["walkthrough-next"];
const picker = elements["walkthrough-picker"];
const counter = elements["walkthrough-counter"];

function current() {
  const visible = screens.map((screen, i) => screen.hidden ? null : i).filter(i => i !== null);
  assert.equal(visible.length, 1);
  return visible[0];
}

if (scenario === "sequence") {
  assert.equal(screens.length, 8);
  for (let i = 0; i < screens.length; i++) {
    assert.equal(current(), i);
    assert.equal(counter.textContent, `Step ${i + 1} of 8`);
    assert.equal(picker.value, String(i));
    assert.equal(steps[i].attributes["aria-current"], "step");
    if (i < 7) assert.equal(next.textContent, `Next: ${screens[i + 1].dataset.nextLabel}`);
    if (i < 7) next.click();
  }
} else if (scenario === "previous") {
  steps[7].click(); back.click(); assert.equal(current(), 6);
} else if (scenario === "picker") {
  picker.value = "4"; picker.handlers.change(); assert.equal(current(), 4);
} else if (scenario === "step-button") {
  steps[6].click(); assert.equal(current(), 6);
} else if (scenario === "restart") {
  steps[7].click(); assert.equal(next.textContent, "Start again");
  next.click(); assert.equal(current(), 0); assert.equal(back.disabled, true);
} else if (scenario === "invalid-step") {
  steps[4].click(); picker.value = "99"; picker.handlers.change(); assert.equal(current(), 4);
} else if (scenario === "initialization") {
  assert.equal(root.classList.value, "is-interactive");
  assert.ok(controls.every(control => !control.hidden));
  assert.equal(current(), 0);
} else if (scenario === "missing-page") {
  vm.runInNewContext(script, { document: { getElementById: () => null } });
} else {
  throw new Error(`Unknown scenario: ${scenario}`);
}
