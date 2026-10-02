// Isolated contract check: no provider means no chat creation or model/tool run.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const path = new URL("../product/app/design/sala-v2/agui/aleph-agent.js", import.meta.url);
const source = readFileSync(path, "utf8")
  .replace(/import\s*\{[\s\S]*?\}\s*from\s*["'][^"']+["'];/g, "")
  .replace(/export class AlephAgent/, "class AlephAgent");
const events = [];
const context = {
  AbstractAgent: class { constructor() { this.messages = []; } },
  Observable: class { constructor(start) { this.start = start; } subscribe(observer) {
    return this.start({ next: (event) => observer(event), complete: () => {} });
  } },
  EventType: { RUN_STARTED: "RUN_STARTED", RUN_ERROR: "RUN_ERROR" },
  window: { AlephBrain: { resolve: async () => ({ id: "none", noUsable: true,
    detail: "No hay modelo utilizable.", action: { href: "/Modelos.dc.html" } }) } },
  AbortController,
  setTimeout,
  console,
};
vm.runInNewContext(source + "\nglobalThis.TestAgent = AlephAgent;", context);
const agent = new context.TestAgent({ contexto: () => ({}) });
agent._asegurarHilo = () => { throw new Error("created chat without provider"); };
agent._correrObra = () => { throw new Error("started model without provider"); };
agent.run({ messages: [{ role: "user", content: "task" }] }).subscribe((event) => events.push(event));
await new Promise((resolve) => setTimeout(resolve, 10));
assert.equal(events[0]?.type, "RUN_STARTED");
assert.equal(events.at(-1)?.type, "RUN_ERROR");
assert.equal(events.at(-1)?.code, "no_provider");
console.log("PASS Sala no-provider guard: visible typed error, no chat or model run");
