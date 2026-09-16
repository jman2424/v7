import test from 'node:test';
import assert from 'node:assert/strict';
import { AssistantWidget } from './index.js';

globalThis.window = { addEventListener() {}, removeEventListener() {} };
globalThis.document = { body: {} };

function fixture() {
  const widget = new AssistantWidget({ baseUrl: 'https://chat.example.test' });
  const sent = [];
  const frame = { postMessage: (...args) => sent.push(args) };
  widget.iframe = { contentWindow: frame };
  return { widget, frame, sent };
}

test('only the configured origin and current frame can send widget events', () => {
  const { widget, frame } = fixture();
  const messages = [];
  widget.on('message', data => messages.push(data));
  const data = { __asa: 'ASA_WIDGET:iframe->client', payload: { type: 'chat:reply', data: 'reply' } };
  widget._onMessage({ source: {}, origin: 'https://chat.example.test', data });
  widget._onMessage({ source: frame, origin: 'https://attacker.example', data });
  widget._onMessage({ source: frame, origin: 'null', data });
  assert.deepEqual(messages, []);
  widget._onMessage({ source: frame, origin: 'https://chat.example.test', data });
  assert.deepEqual(messages, ['reply']);
  widget.close();
  widget._onMessage({ source: frame, origin: 'https://chat.example.test', data });
  assert.deepEqual(messages, ['reply']);
});

test('private messages target an exact origin even if the frame navigates', () => {
  const { widget, sent } = fixture();
  widget.iframe.src = 'https://attacker.example';
  widget.sendMessage('private text', { private: true });
  assert.equal(sent.length, 1);
  assert.equal(sent[0][1], 'https://chat.example.test');
});

test('unsafe widget URL schemes and embedded credentials are rejected', () => {
  for (const chatUiPath of ['javascript:alert(1)', 'data:text/html,test', 'https://user:pass@example.test/chat']) {
    assert.throws(() => new AssistantWidget({ baseUrl: 'https://chat.example.test', chatUiPath }));
  }
});
