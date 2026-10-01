import assert from "node:assert/strict";
import test from "node:test";
import { AssistantWidget } from "../index.js";

test("widget only accepts messages from its configured iframe and origin", () => {
  globalThis.window = {addEventListener() {}, removeEventListener() {}};
  globalThis.document = {body: {}};
  const widget = new AssistantWidget({baseUrl: "https://chat.example.test"});
  const sent = [];
  const source = {postMessage: (...args) => sent.push(args)};
  widget.iframe = {contentWindow: source};
  const received = [];
  widget.on("message", data => received.push(data));
  const data = {__asa: "ASA_WIDGET:iframe->client", payload: {type: "chat:reply", data: {reply: "hello"}}};
  widget._onMessage({source, origin: "https://attacker.test", data});
  widget._onMessage({source: {}, origin: "https://chat.example.test", data});
  assert.deepEqual(received, []);
  widget._onMessage({source, origin: "https://chat.example.test", data});
  assert.deepEqual(received, [{reply: "hello"}]);
  widget._post({text: "private customer text"});
  assert.equal(sent[0][1], "https://chat.example.test");
  widget.destroy();
});
