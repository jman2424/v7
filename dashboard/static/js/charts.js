/* static/js/charts.js
   Charts controller for Admin dashboard.
   Exposes: window.DashChartsReload()
*/

(function () {
  const S = window.__ADMIN__ || {};
  const $ = (sel, root = document) => root.querySelector(sel);

  let chart = null;

  function minutesFromSelect() {
    const v = $("#period-select")?.value || "1440";
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : 1440;
  }

  async function apiJSON(path) {
    const csrf = S.csrfToken || "";
    const headers = Object.assign(
      {},
      csrf ? { "X-CSRF-Token": csrf } : {}
    );

    const res = await fetch(path, { headers, credentials: "include" });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
    }
    return res.json();
  }

  function normalizeTimeseriesPayload(payload) {
    // We accept a few common shapes:
    // A) { points: [{t, inbound, outbound}, ...] }
    // B) { items:  [{t, inbound, outbound}, ...] }
    // C) { labels: [...], inbound: [...], outbound: [...] }
    // D) [{t, inbound, outbound}, ...]  (raw array)

    if (Array.isArray(payload)) {
      return payload.map(p => ({
        t: p.t ?? p.ts ?? p.time ?? p.label,
        inbound: Number(p.inbound ?? p.in ?? 0),
        outbound: Number(p.outbound ?? p.out ?? 0),
      }));
    }

    const points = payload?.points || payload?.items;
    if (Array.isArray(points)) {
      return points.map(p => ({
        t: p.t ?? p.ts ?? p.time ?? p.label,
        inbound: Number(p.inbound ?? p.in ?? 0),
        outbound: Number(p.outbound ?? p.out ?? 0),
      }));
    }

    const labels = payload?.labels;
    const inboundArr = payload?.inbound;
    const outboundArr = payload?.outbound;
    if (Array.isArray(labels) && Array.isArray(inboundArr) && Array.isArray(outboundArr)) {
      const out = [];
      for (let i = 0; i < labels.length; i++) {
        out.push({
          t: labels[i],
          inbound: Number(inboundArr[i] ?? 0),
          outbound: Number(outboundArr[i] ?? 0),
        });
      }
      return out;
    }

    return [];
  }

  function fmtLabel(t) {
    if (!t) return "";
    // If it's ISO, make it shorter.
    const s = String(t);
    // 2026-01-12T03:52:41Z -> 03:52
    const m = s.match(/T(\d{2}:\d{2})/);
    if (m) return m[1];
    return s.length > 16 ? s.slice(0, 16) : s;
  }

  function ensureChart() {
    const canvas = $("#chart-main");
    if (!canvas) return null;

    if (!window.Chart) {
      console.warn("Chart.js not loaded");
      return null;
    }

    if (chart) return chart;

    const ctx = canvas.getContext("2d");
    chart = new window.Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "Inbound", data: [], tension: 0.25 },
          { label: "Outbound", data: [], tension: 0.25 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: true }
        },
        scales: {
          x: { ticks: { maxTicksLimit: 12 } },
          y: { beginAtZero: true }
        }
      }
    });

    return chart;
  }

  async function reload() {
    const minutes = minutesFromSelect();
    const url = `/admin/api/timeseries?minutes=${minutes}`;

    const payload = await apiJSON(url);
    const rows = normalizeTimeseriesPayload(payload);

    const c = ensureChart();
    if (!c) return;

    const labels = rows.map(r => fmtLabel(r.t));
    const inbound = rows.map(r => r.inbound);
    const outbound = rows.map(r => r.outbound);

    c.data.labels = labels;
    c.data.datasets[0].data = inbound;
    c.data.datasets[1].data = outbound;

    // Force update
    c.update();
    return { labels: labels.length, points: rows.length };
  }

  // Expose for admin.js
  window.DashChartsReload = async function () {
    try {
      return await reload();
    } catch (e) {
      console.error("DashChartsReload failed:", e);
      // don’t throw, admin.js might call it inside Promise.all
      return null;
    }
  };

  // Auto init
  window.addEventListener("DOMContentLoaded", () => {
    // Create chart immediately so canvas isn’t blank forever
    ensureChart();
    window.DashChartsReload();
  });
})();
