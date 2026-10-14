import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { compile } = require('svelte/compiler');

for (const name of ['EmailManagement', 'PasswordManagement']) {
  test(`${name} preserves the six-digit quantifier when Svelte compiles`, () => {
    const source = readFileSync(new URL(`../../frontend/src/lib/${name}.svelte`, import.meta.url), 'utf8');
    const output = compile(source, { generate: 'server' }).js.code;
    // Quoted Svelte attributes interpolate {6}; compile the real component
    // so this catches the regression that browser form validation exposed.
    assert.match(output, /pattern="\[0-9\]\{6\}"/);
    assert.doesNotMatch(output, /pattern="\[0-9\]6"/);
  });
}
