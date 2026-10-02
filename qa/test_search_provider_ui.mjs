import assert from "node:assert/strict";
import { test } from "node:test";

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.hidden = false; this.textContent = ""; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  remove() { this.removed = true; }
  click() { return this.listeners.click?.(); }
}

globalThis.document = { body: new Element("body"), createElement: (tag) => new Element(tag) };
const { ensureSearchProvider } = await import("../product/app/design/sala-v2/search-provider.js");
const headers = (base) => base;
const buttons = (dialog) => dialog.children.find((node) => node.className === "sv-search-provider-choices").children;

test("provider prompt only follows the invoked capability, and Cancel is clean", async () => {
  const calls = [];
  globalThis.fetch = async (url) => { calls.push(url); return { ok: true, json: async () => ({ configured: false }) }; };
  assert.equal(document.body.children.length, 0);
  assert.equal(calls.length, 0);
  const pending = ensureSearchProvider(headers);
  await new Promise(setImmediate);
  assert.equal(await ensureSearchProvider(headers), false);
  assert.equal(document.body.children.length, 1);
  const dialog = document.body.children.at(-1);
  assert.equal(dialog.children[0].textContent, "Web search requires a search provider.");
  assert.deepEqual(buttons(dialog).map((button) => button.textContent), [
    "Connect existing SearXNG instance", "Install SearXNG locally", "Cancel",
  ]);
  buttons(dialog)[2].click();
  assert.equal(await pending, false);
  assert.equal(dialog.removed, true);
  assert.deepEqual(calls, ["/v1/sala/search-provider"]);
});

test("local-install option is disclosure and upstream guidance, never a silent install", async () => {
  const calls = [];
  globalThis.fetch = async (url) => { calls.push(url); return { ok: true, json: async () => ({ configured: false }) }; };
  const pending = ensureSearchProvider(headers);
  await new Promise(setImmediate);
  const dialog = document.body.children.at(-1);
  buttons(dialog)[1].click();
  const details = dialog.children.at(-1);
  assert.match(details.children[0].textContent, /AGPL-3\.0-or-later/);
  assert.match(details.children[0].textContent, /not owned or installed by Aleph/);
  assert.equal(details.children.filter((node) => node.tag === "a").length, 3);
  assert.deepEqual(calls, ["/v1/sala/search-provider"]);
  buttons(dialog)[2].click();
  assert.equal(await pending, false);
});

test("an available external provider proceeds without a prompt", async () => {
  const previous = document.body.children.length;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ configured: true }) });
  assert.equal(await ensureSearchProvider(headers), true);
  assert.equal(document.body.children.length, previous);
});

test("connect option submits the chosen URL and continues only after validation", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, json: async () => url.endsWith("search-provider") && options.method === "PUT"
      ? { configured: true } : { configured: false } };
  };
  const pending = ensureSearchProvider(headers);
  await new Promise(setImmediate);
  const dialog = document.body.children.at(-1);
  buttons(dialog)[0].click();
  const details = dialog.children.at(-1);
  details.children.find((node) => node.tag === "input").value = "http://127.0.0.1:8888";
  await details.children.find((node) => node.textContent === "Connect and continue").click();
  assert.equal(await pending, true);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.method, "PUT");
  assert.equal(JSON.parse(calls[1].options.body).url, "http://127.0.0.1:8888");
});
