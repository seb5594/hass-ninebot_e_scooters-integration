"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function frontend() {
  const elements = [];
  const listeners = {};
  let receive;
  const connection = {
    connected: true,
    subscribeMessage(callback, request) {
      assert.equal(request.type, "persistent_notification/subscribe");
      receive = callback;
      return Promise.resolve(() => {});
    },
  };
  const document = {
    body: { append(element) { elements.push(element); } },
    visibilityState: "visible",
    querySelector() { return { hass: { connection } }; },
    addEventListener(type, callback) { listeners[type] = callback; },
    createElement(tag) {
      const events = {};
      return {
        tag, style: {}, open: false, children: [], attributes: {},
        setAttribute(key, value) { this.attributes[key] = value; },
        append(...children) { this.children.push(...children); },
        addEventListener(type, callback) { events[type] = callback; },
        showModal() { this.open = true; },
        close() { this.open = false; events.close?.(); },
        click() { events.click?.(); },
      };
    },
  };
  const filename = path.join(__dirname, "../../custom_components/ninebot_e_scooters/assets/pairing_dialog.js");
  vm.runInNewContext(fs.readFileSync(filename, "utf8"), { document, setInterval() {} });
  function notify(type, id, title = "Ninebot E-Scooters – Pairing jetzt bestätigen") {
    receive({ type, notifications: { [id]: { notification_id: id, title } } });
  }
  return { elements, document, notify, listeners };
}

test("pairing opens a centered accessible modal and dismisses on completion", () => {
  const view = frontend();
  view.notify("added", "other_integration");
  assert.equal(view.elements.length, 0);
  view.notify("current", "ninebot_e_scooters_pair_entry");
  const dialog = view.elements[0];
  assert.equal(dialog.open, true);
  assert.match(dialog.style.cssText, /position:fixed;inset:0;margin:auto/);
  assert.equal(dialog.attributes["aria-labelledby"], dialog.children[0].id);
  assert.equal(dialog.children[2].src, "/api/ninebot_e_scooters/power_button.gif");
  view.notify("removed", "ninebot_e_scooters_pair_entry");
  assert.equal(dialog.open, false);
});

test("hidden screens wait until visible and acknowledgements suppress repeat prompts", () => {
  const view = frontend();
  const id = "ninebot_e_scooters_pair_entry";
  view.document.visibilityState = "hidden";
  view.notify("added", id);
  assert.equal(view.elements.length, 0);
  view.document.visibilityState = "visible";
  view.listeners.visibilitychange();
  const dialog = view.elements[0];
  dialog.children[3].click();
  view.notify("updated", id);
  assert.equal(dialog.open, false);
  view.notify("updated", id, "Ninebot E-Scooters – Pairing nicht abgeschlossen");
  view.notify("updated", id, "Ninebot E-Scooters – Gespeicherten Schlüssel bestätigen");
  assert.equal(dialog.open, true);
});
