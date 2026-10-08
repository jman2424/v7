const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');

const root = path.resolve(__dirname, '../..');
const loader = fs.readFileSync(path.join(root, 'dashboard/static/js/public-analytics.js'), 'utf8');
const preferences = fs.readFileSync(path.join(root, 'dashboard/static/js/ui-i18n.js'), 'utf8');
const sveltePreferences = ts.transpileModule(fs.readFileSync(path.join(root, 'frontend/src/lib/i18n.ts'), 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true}
}).outputText;
const measurementId = 'G-ABC123DEF4';

function target() {
  const listeners = new Map();
  return {
    addEventListener(name, callback) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(callback);
    },
    dispatchEvent(event) { for (const callback of listeners.get(event.type) || []) callback(event); },
    emit(type, detail) { this.dispatchEvent({type, ...detail}); }
  };
}

function element() {
  return Object.assign(target(), {
    hidden: true, checked: false, dataset: {}, attributes: {}, focused: false,
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { this.focused = true; },
    remove() { this.removed = true; }
  });
}

function harness({cookies = {}, pathname = '/', config = {measurement_id: measurementId}, missingConfig = false} = {}) {
  const jar = new Map(Object.entries({session: 'synthetic-session', v7_trusted_device: 'synthetic-proof', ...cookies}));
  const writes = [], scripts = [], intervals = [], broadcasts = [];
  const banner = element(), opener = element(), close = element(), language = element(), analytics = element();
  const essential = element(), save = element();
  essential.dataset.preferences = 'essential'; save.dataset.preferences = 'all';
  banner.querySelector = selector => ({
    '[data-close-cookie-preferences]': close,
    '[data-consent-language]': language,
    '[data-consent-analytics]': analytics
  })[selector];
  const document = Object.assign(target(), {
    title: 'Public solution | V7', documentElement: {lang: 'en', dir: 'ltr'},
    currentScript: {src: 'https://vertex-seven.com/static/js/ui-i18n.js'},
    body: {style: {paddingBottom: '24px'}},
    head: {appendChild(script) { scripts.push(script); }},
    createElement() { return element(); },
    getElementById(id) {
      if (id === 'site-cookie-banner') return banner;
      if (id === 'v7-public-analytics-config' && !missingConfig) return {textContent: JSON.stringify(config)};
      return null;
    },
    querySelectorAll(selector) { return {
      '[data-open-cookie-preferences]': [opener], '[data-close-cookie-preferences]': [close],
      '[data-preferences]': [essential, save], '[data-language-picker]': [], '[data-i18n]': []
    }[selector] || []; }
  });
  Object.defineProperty(document, 'cookie', {
    get: () => [...jar].map(([name, value]) => `${name}=${value}`).join('; '),
    set: value => {
      writes.push(value);
      const [pair, ...attributes] = value.split('; ');
      const separator = pair.indexOf('=');
      const name = pair.slice(0, separator), content = pair.slice(separator + 1);
      if (attributes.includes('Max-Age=0')) jar.delete(name); else jar.set(name, content);
    }
  });
  const window = Object.assign(target(), {setInterval(callback) { intervals.push(callback); }});
  class Event { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } }
  class BroadcastChannel {
    constructor(name) { this.name = name; this.events = target(); broadcasts.push(this); }
    addEventListener(...args) { this.events.addEventListener(...args); }
    postMessage(value) { this.message = value; }
    close() { this.closed = true; }
  }
  const location = {protocol: 'https:', origin: 'https://vertex-seven.com', pathname,
    href: `https://vertex-seven.com${pathname}?email=private@example.test#private`, search: '?email=private@example.test', hash: '#private'};
  const context = vm.createContext({document, window, location, navigator: {language: 'en-GB'}, URL,
    CustomEvent: Event, Event, BroadcastChannel, fetch: async () => ({ok: false})});
  const runUI = () => vm.runInContext(preferences, context);
  const runLoader = () => vm.runInContext(loader, context);
  const runSveltePreferences = () => {
    const exports = {};
    context.exports = exports;
    context.require = name => {
      if (name === 'svelte/store') return {writable: value => ({set(next) { value = next; }}), derived: () => ({})};
      if (name.endsWith('.json')) return {};
      throw new Error(`Unexpected import: ${name}`);
    };
    vm.runInContext(sveltePreferences, context);
    return exports;
  };
  const calls = () => (window.dataLayer || []).map(item => Array.from(item));
  return {jar, writes, scripts, intervals, broadcasts, banner, opener, close, language, analytics, essential, save,
    document, window, location, runUI, runLoader, runSveltePreferences, calls};
}

test('absent, denied, malformed, legacy and expired consent make no Google requests', () => {
  for (const value of [undefined, 'v1%3Adenied', 'granted', 'v2%3Agranted', '%ZZ']) {
    const state = harness({cookies: {v7_preferences: 'all', ...(value ? {v7_analytics_consent: value} : {})}});
    state.runLoader();
    state.window.emit('focus');
    assert.equal(state.scripts.length, 0);
    assert.equal(state.window.dataLayer, undefined);
    assert.equal(state.window['ga-disable-' + measurementId], true);
  }
});

test('only nine public paths and valid configuration can load analytics', () => {
  for (const pathname of ['/console/', '/chat', '/privacy', '/cookies', '/solutions/unknown']) {
    const state = harness({pathname, cookies: {v7_analytics_consent: 'v1%3Agranted'}});
    state.runLoader();
    assert.equal(state.scripts.length, 0);
  }
  for (const config of [null, {}, {measurement_id: 'G-invalid'}, {measurement_id: 'G-ABC123DEF4<script>'}]) {
    const state = harness({config, cookies: {v7_analytics_consent: 'v1%3Agranted'}});
    assert.doesNotThrow(state.runLoader);
    assert.equal(state.scripts.length, 0);
  }
  const state = harness({missingConfig: true, cookies: {v7_analytics_consent: 'v1%3Agranted'}});
  state.runLoader();
  assert.equal(state.scripts.length, 0);
});

test('explicit consent loads once and sends one sanitized public page view', () => {
  const state = harness({pathname: '/solutions/website-chatbot'});
  state.runLoader();
  state.jar.set('v7_analytics_consent', 'v1%3Agranted');
  state.window.emit('v7-analytics-consent-changed', {detail: {granted: false}});
  assert.equal(state.scripts.length, 1);
  assert.equal(state.scripts[0].src, 'https://www.googletagmanager.com/gtag/js?id=G-ABC123DEF4');
  assert.equal(state.scripts[0].referrerPolicy, 'no-referrer');
  assert.equal(state.calls().some(call => call[0] === 'config' || call[0] === 'event'), false);
  state.scripts[0].onload();
  const configuration = state.calls().find(call => call[0] === 'config')[2];
  assert.equal(configuration.send_page_view, false);
  assert.equal(configuration.allow_google_signals, false);
  assert.equal(configuration.allow_ad_personalization_signals, false);
  assert.equal(configuration.cookie_domain, 'none');
  assert.equal(configuration.cookie_path, '/');
  assert.equal(configuration.cookie_expires, 180 * 86400);
  assert.equal(configuration.cookie_update, false);
  const update = state.calls().find(call => call[0] === 'consent' && call[1] === 'update')[2];
  for (const category of ['ad_storage', 'ad_user_data', 'ad_personalization']) assert.equal(update[category], 'denied');
  assert.equal(update.analytics_storage, 'granted');
  const view = state.calls().find(call => call[0] === 'event');
  assert.equal(view[1], 'page_view');
  assert.deepEqual(JSON.parse(JSON.stringify(view[2])), {
    page_location: 'https://vertex-seven.com/solutions/website-chatbot', page_referrer: '',
    page_title: 'Public solution | V7', send_to: measurementId
  });
  const callCount = state.calls().length;
  state.window.emit('focus'); state.window.emit('pageshow'); state.document.emit('visibilitychange');
  assert.equal(state.calls().length, callCount);
  assert.equal(state.scripts.length, 1);
});

test('withdrawal while tag is loading prevents configuration and page views', () => {
  const state = harness({cookies: {v7_analytics_consent: 'v1%3Agranted'}});
  state.runUI(); state.runLoader();
  state.jar.set('v7_analytics_consent', 'v1%3Adenied');
  state.window.emit('v7-analytics-consent-changed');
  state.scripts[0].onload();
  assert.equal(state.window['ga-disable-' + measurementId], true);
  assert.equal(state.calls().some(call => call[0] === 'config' || call[0] === 'event'), false);
});

test('withdrawal stops measurement, deletes only GA cookies and can be explicitly reversed', () => {
  const state = harness({cookies: {v7_preferences: 'all', v7_language: 'fr', v7_analytics_consent: 'v1%3Agranted'}});
  state.runUI(); state.runLoader(); state.scripts[0].onload();
  state.jar.set('_ga', 'synthetic-id'); state.jar.set('_ga_ABC123DEF4', 'synthetic-stream');
  state.jar.set('unrelated_cookie', 'preserved');
  state.opener.emit('click'); state.analytics.checked = false; state.save.emit('click');
  const count = state.calls().length;
  state.window.emit('focus'); state.intervals[0]();
  assert.equal(state.calls().length, count);
  assert.equal(state.window['ga-disable-' + measurementId], true);
  assert.equal(state.jar.has('_ga'), false); assert.equal(state.jar.has('_ga_ABC123DEF4'), false);
  for (const name of ['session', 'v7_trusted_device', 'unrelated_cookie', 'v7_language']) assert.ok(state.jar.has(name));
  state.opener.emit('click'); state.analytics.checked = true; state.save.emit('click');
  assert.equal(state.window['ga-disable-' + measurementId], false);
  assert.equal(state.scripts.length, 1);
  assert.equal(state.calls().filter(call => call[0] === 'event').length, 1);
});

test('expiration and cross-tab withdrawal fail closed after a permitted visit', () => {
  const state = harness({cookies: {v7_analytics_consent: 'v1%3Agranted'}});
  state.runLoader(); state.scripts[0].onload();
  state.jar.delete('v7_analytics_consent'); state.intervals[0]();
  assert.equal(state.window['ga-disable-' + measurementId], true);
  state.jar.set('v7_analytics_consent', 'v1%3Agranted');
  state.window.emit('focus'); assert.equal(state.window['ga-disable-' + measurementId], false);
  state.jar.set('v7_analytics_consent', 'v1%3Adenied');
  state.broadcasts[0].events.emit('message');
  assert.equal(state.window['ga-disable-' + measurementId], true);
});

test('close and Escape do not grant either optional category or alter page spacing', () => {
  const state = harness(); state.runUI();
  assert.equal(state.language.checked, false); assert.equal(state.analytics.checked, false);
  state.close.emit('click'); state.opener.emit('click'); state.document.emit('keydown', {key: 'Escape'});
  assert.equal(state.writes.length, 0); assert.equal(state.banner.hidden, true);
  assert.equal(state.opener.focused, true); assert.equal(state.document.body.style.paddingBottom, '24px');
});

test('legacy language opt-in never preselects or grants analytics', () => {
  const state = harness({cookies: {v7_preferences: 'all', v7_language: 'fr'}}); state.runUI();
  assert.equal(state.banner.hidden, false); assert.equal(state.language.checked, true); assert.equal(state.analytics.checked, false);
  state.save.emit('click');
  assert.equal(state.jar.get('v7_preferences'), 'all'); assert.equal(state.jar.get('v7_language'), 'fr');
  assert.equal(state.jar.get('v7_analytics_consent'), 'v1%3Adenied');
});

test('analytics opt-in does not require language storage', () => {
  const state = harness(); state.runUI(); state.analytics.checked = true; state.save.emit('click');
  assert.equal(state.jar.get('v7_preferences'), 'essential'); assert.equal(state.jar.has('v7_language'), false);
  assert.equal(state.jar.get('v7_analytics_consent'), 'v1%3Agranted');
  const record = state.writes.find(value => value.startsWith('v7_analytics_consent='));
  assert.match(record, /Max-Age=15552000; SameSite=Lax; Secure$/);
});

test('essential-only overrides both checked options and preserves security', () => {
  const state = harness({cookies: {v7_language: 'fr', _ga: 'synthetic-id'}}); state.runUI();
  state.language.checked = true; state.analytics.checked = true; state.essential.emit('click');
  assert.equal(state.jar.get('v7_preferences'), 'essential'); assert.equal(state.jar.has('v7_language'), false);
  assert.equal(state.jar.get('v7_analytics_consent'), 'v1%3Adenied'); assert.equal(state.jar.has('_ga'), false);
  assert.equal(state.jar.get('session'), 'synthetic-session'); assert.equal(state.jar.get('v7_trusted_device'), 'synthetic-proof');
});

test('Svelte preferences preserve the same independent analytics-only choice', () => {
  const state = harness(); const preferences = state.runSveltePreferences();
  preferences.choosePreferences('essential', true);
  assert.equal(state.jar.get('v7_preferences'), 'essential'); assert.equal(state.jar.has('v7_language'), false);
  assert.equal(state.jar.get('v7_analytics_consent'), 'v1%3Agranted');
  state.jar.set('_ga', 'synthetic-id'); state.jar.set('_ga_ABC123DEF4', 'synthetic-stream');
  preferences.choosePreferences('all', false);
  assert.equal(state.jar.get('v7_preferences'), 'all'); assert.equal(state.jar.get('v7_language'), 'en');
  assert.equal(state.jar.get('v7_analytics_consent'), 'v1%3Adenied');
  assert.equal(state.jar.has('_ga'), false); assert.equal(state.jar.has('_ga_ABC123DEF4'), false);
  assert.equal(state.jar.get('session'), 'synthetic-session');
});
