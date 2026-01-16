/* static/js/charts.js
   Admin charts controller (tenant-safe)
   Exposes: window.DashChartsReload()
*/
(function () {
  const S = window.__ADMIN__ || {};
  const $ = (sel, root = document) => root.querySelector(sel);

  let chart = null;

  function getTenant() {
    return (
      S.tenant ||
      document.body?.dataset?.tenant ||
      new URLSearchParams(window.location.search).get("tenant") ||
      "default"
    );
  }

  function minutesFromSelect() {
    const v = $("#period-select")?.value || "1440";
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : 1440;
  }

  async function apiJSON(path) {
    const csrf = S.csrfToken || "";
    const headers = csrf ? { "X-CSRF-Token": csrf } : {};
    const res = await fetch(path, { headers, credentials: "include" });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
    }
    return res.json();
  }

  function normalize(payload) {
    if (Array.isArray(payload)) return payload;

    if (Array.isArray(payload?.points)) return payload.points;
    if (Array.isArray(payload?.items)) return payload.items;

    if (Array.isArray(payload?.labels) && Array.isArray(payload?.inbound) && Array.isArray(payload?.outbound)) {
      const out = [];
      for (let i = 0; i < payload.labels.length; i++) {
        out.push({
          t: payload.labels[i],
          inbound: Number(payload.inbound[i] ?? 0),
          outbound: Number(payload.outbound[i] ?? 0),
        });
      }
      return out;
    }

    return [];
  }

  function fmtLabel(t) {
    if (!t) return "";
    const s = String(t);
    const m = s.match(/T(\d{2}:\d{2})/);
    if (m) return m[1];
    return s.length > 16 ? s.slice(0, 16) : s;
  }

  function ensureChart() {
    const canvas = $("#chart-main");
    if (!canvas) return null;
    if (!window.Chart) return null;

    if (chart) return chart;

    const ctx = canvas.getContext("2d");
    chart = new window.Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "Inbound", data: [], tension: 0.25 },
          { label: "Outbound", data: [], tension: 0.25 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: true } },
        scales: {
          x: { ticks: { maxTicksLimit: 12 } },
          y: { beginAtZero: true },
        },
      },
    });

    return chart;
  }

  async function reload() {
    const minutes = minutesFromSelect();
    const tenant = encodeURIComponent(getTenant());

    // IMPORTANT: tenant included
    const url = `/admin/api/timeseries?minutes=${minutes}&tenant=${tenant}`;
    const payload = await apiJSON(url);

    const rows = normalize(payload);

    const c = ensureChart();
    if (!c) return;

    const labels = rows.map((r) => fmtLabel(r.t ?? r.ts ?? r.time ?? r.label));
    const inbound = rows.map((r) => Number(r.inbound ?? r.in ?? 0));
    const outbound = rows.map((r) => Number(r.outbound ?? r.out ?? 0));

    c.data.labels = labels;
    c.data.datasets[0].data = inbound;
    c.data.datasets[1].data = outbound;
    c.update();
  }

  window.DashChartsReload = async function () {
    try {
      await reload();
      return true;
    } catch (e) {
      console.error("DashChartsReload failed:", e);
      return false;
    }
  };

  window.addEventListener("DOMContentLoaded", () => {
    ensureChart();
    window.DashChartsReload();
  });
})();
