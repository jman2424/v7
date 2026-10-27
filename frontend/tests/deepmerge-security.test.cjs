const test = require('node:test');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
// Exercise exactly the dependency resolved by the console's build plugin.
const pluginRequire = createRequire(require.resolve('@sveltejs/vite-plugin-svelte'));
const merge = pluginRequire('deepmerge');

test('console config keeps nested options, function values and array replacement', () => {
  const first = () => 'first';
  const second = () => 'second';
  const defaults = { compilerOptions: { dev: false, css: 'external' }, preprocess: [first] };
  const override = { compilerOptions: { dev: true }, preprocess: [second] };
  const result = merge(defaults, override, { arrayMerge: (target, source) => source ?? target });
  assert.deepEqual(result.compilerOptions, { dev: true, css: 'external' });
  assert.strictEqual(result.preprocess, override.preprocess);
  assert.strictEqual(result.preprocess[0], second);
  assert.deepEqual(defaults.compilerOptions, { dev: false, css: 'external' });
  assert.strictEqual(defaults.preprocess[0], first);
});

test('source keys cannot poison a normal or null-prototype config result', () => {
  const source = JSON.parse('{"__proto__":{"injectedBuildFlag":true},"valid":7}');
  for (const target of [{}, Object.create(null)]) {
    const result = merge(target, source);
    assert.strictEqual(Object.getPrototypeOf(result), Object.prototype);
    assert.equal(result.injectedBuildFlag, undefined);
    assert.equal(Object.hasOwn(result, '__proto__'), false);
    assert.equal(result.valid, 7);
  }
  assert.equal({}.injectedBuildFlag, undefined);
});

test('target-copy and nested placeholder branches reject prototype poisoning', () => {
  const poisonedTarget = JSON.parse('{"__proto__":{"injectedBuildFlag":true},"valid":1}');
  const targetResult = merge(poisonedTarget, { other: 2 });
  assert.strictEqual(Object.getPrototypeOf(targetResult), Object.prototype);
  assert.equal(targetResult.injectedBuildFlag, undefined);
  assert.deepEqual(targetResult, { valid: 1, other: 2 });
  const nested = merge({ session: null }, JSON.parse('{"session":{"__proto__":{"injectedBuildFlag":true},"valid":3}}'));
  assert.strictEqual(Object.getPrototypeOf(nested.session), Object.prototype);
  assert.equal(nested.session.injectedBuildFlag, undefined);
  assert.equal(nested.session.valid, 3);
});

test('constructor/prototype objects cannot modify shared global prototypes', () => {
  const result = merge({}, JSON.parse('{"constructor":{"prototype":{"injectedBuildFlag":true}}}'));
  assert.equal({}.injectedBuildFlag, undefined);
  assert.equal(Object.hasOwn(result, 'constructor'), false);
});
