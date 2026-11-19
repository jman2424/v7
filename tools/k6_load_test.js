/**
 * k6 load test for /chat_api
 *
 * Usage:
 *   k6 run tools/k6_load_test.js --env BASE_URL=http://localhost:10000 --env TENANT=EXAMPLE
 *
 * Executors:
 * - default: constant-arrival-rate hitting target RPS for a steady window.
 */

import http from 'k6/http';
import exec from 'k6/execution';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:10000';
const tenants = (__ENV.TENANTS || __ENV.TENANT || 'EXAMPLE').split(',').map(key => key.trim());
if (tenants.some(key => !key) || new Set(tenants).size !== tenants.length) {
  throw new Error('Supply distinct, non-empty business keys in TENANTS.');
}
const RPS = parseInt(__ENV.RPS || '20', 10);          // target requests per second
const DURATION = __ENV.DURATION || '2m';               // test duration
const MAX_VUS = parseInt(__ENV.MAX_VUS || '50', 10);  // upper bound for executors

export const options = {
  discardResponseBodies: false,
  thresholds: {
    http_req_failed: ['rate<0.01'],                         // <1% errors
    http_req_duration: ['p(95)<500', 'p(99)<900'],          // latency targets
    'chat_ok_rate': ['rate>0.99'],
    dropped_iterations: ['count==0'],
    ...Object.fromEntries(tenants.map(key => [`chat_ok_rate{tenant:${key}}`, ['rate>0.99']])),
    ...Object.fromEntries(tenants.map(key => [`chat_requests{tenant:${key}}`, ['count>0']]))
  },
  scenarios: {
    steady_chat: {
      executor: 'constant-arrival-rate',
      rate: RPS,
      timeUnit: __ENV.TIME_UNIT || '1s',
      duration: DURATION,
      preAllocatedVUs: Math.min(RPS, MAX_VUS),
      maxVUs: MAX_VUS
    }
  }
};

const requests = new Counter('chat_requests');
const okRate = new Rate('chat_ok_rate');
const durTrend = new Trend('chat_req_duration_ms');

const MESSAGES = [
  'What are your hours today?',
  'Do you deliver to E6 1AA?',
  'Price for chicken wings?',
  'BBQ pack for 6 people?',
  'Where is the nearest branch to E7 8AA?',
  'Are you open on bank holidays?',
  'Do you have halal certification?',
  'Can I pick up at 5pm today?',
];

function sessionId() {
  return 'asa_' + Math.random().toString(16).slice(2) + Date.now().toString(16);
}

export default function () {
  const tenant = tenants[exec.scenario.iterationInTest % tenants.length];
  const msg = MESSAGES[Math.floor(Math.random() * MESSAGES.length)];
  const payload = JSON.stringify({
    message: msg,
    session_id: sessionId(),
    channel: 'web',
    tenant,
    metadata: { source: 'k6' }
  });

  const params = {
    headers: { 'Content-Type': 'application/json' },
    tags: { endpoint: '/chat_api', tenant }
  };

  const t0 = Date.now();
  const res = http.post(`${BASE_URL}/chat_api`, payload, params);
  const dt = Date.now() - t0;
  durTrend.add(dt);

  const good =
    check(res, {
      'status 200': (r) => r.status === 200,
      'JSON chat reply exists': (r) => {
        try {
          const j = r.json();
          return typeof j.reply === 'string' && j.reply.length > 0;
        } catch (_) {
          return false;
        }
      }
    });

  requests.add(1, {tenant});
  okRate.add(good, {tenant});
  // small random sleep to avoid perfect sync
  sleep(Math.random() * 0.2);
}
