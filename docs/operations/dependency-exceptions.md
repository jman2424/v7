# Temporary console build dependency exception

Reviewed 18 November 2026. Expires at 00:00 UTC on 18 December 2026.

The owner delegated the release decision after being told about the failed
security check and the option of a 30-day, build-only exception.

The only accepted advisory is [GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf),
the repeated-extglob ReDoS in picomatch 4.0.7. On review, the official npm release
was 4.0.7 and the advisory listed no patched release. This is an accepted risk,
not a claim that the package is fixed.

Vite, Svelte tooling, tinyglobby and fdir use it while building/checking the
console with repository-controlled patterns. The production Docker image runs
Python/Gunicorn and serves the generated static console. The Node build stage
and frontend/node_modules are not copied into production. Customer requests
cannot supply glob patterns to that build stage. This assessment does not cover
running Vite's development server or a Node SSR server in production.

The audit still queries npm for the complete lockfile, including development
dependencies. Its reviewer rejects all other advisories, unknown or cyclic
dependency chains, runtime dependencies, an unexpected picomatch version,
audit/network failures and use after the expiry date. It also checks the
Docker runtime and node_modules exclusion conditions. Python auditing, CodeQL,
secret scanning, dependency review and reliability tests remain enabled.

Before expiry, check the upstream release/advisory, update the lockfile when a
patched version is available, rerun the console checks/build/tests and remove
this exception. CI fails at expiry if affected findings remain; renewal requires
a fresh review. Do not expand the allowed advisory or runtime scope to obtain a
green check.
