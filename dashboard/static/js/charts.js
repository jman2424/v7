/* dashboard/static/js/charts.js
   Dashboard charts (Chart.js)
   Canvas IDs used by dashboard.html:
     - chart-volume     (line: inbound/outbound)
     - chart-channels   (doughnut: web vs whatsapp total)
     - chart-intents    (horizontal bar: top intents)
     - chart-fallbacks  (bar: fallbacks by intent)
     - chart-errors     (bar: errors by code)
     - chart-sessions   (line: sessions per bucket)

   Data source:
     GET /admin/api/insights?tenant=...&minutes=...&bucket=60&top=10&limit=50

   Exposes:
     window.DashChartsReload()
*/

(function () {
  let abortCtl = null;

  const charts = {
    volume: null,
    channels: null,
    intents: null,
    fallbacks: null,
    errors: null,
    sessions: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function getTenant() {
    return (
      window.__ADMIN__?.tenant ||
      document.body?.dataset?.tenant ||
      "default"
    );
  }

  function getMinutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  function endpoint() {
    const tenant = getTenant();
    const minutes = getMinutes();
    return `/admin/api/insights?tenant=${encodeURIComponent(tenant)}&minutes=${encodeURIComponent(
      minutes
    )}&bucket=60&top=10&limit=50`;
  }

  async function fetchInsights() {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const res = await fetch(endpoint(), {
      credentials: "include",
      signal: abortCtl.signal,
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      const t = await res.text().catch(() => "");
      throw new Error(`Insights HTTP ${res.status}: ${t.slice(0, 200)}`);
    }
    return res.json();
  }

  function destroyIfExists(key) {
    const c = charts[key];
    if (c && typeof c.destroy === "function") {
      c.destroy();
    }
    charts[key] = null;
  }

  function ensureChart(key, buildFn) {
    // if canvas missing, just skip
    if (!buildFn) return;
    destroyIfExists(key);
    charts[key] = buildFn();
  }

  function safeArray(x) {
    return Array.isArray(x) ? x : [];
  }

  // ---------- Normalizers ----------
  function normMessageVolume(payload) {
    const pts =
      payload?.message_volume ||
      payload?.points ||
      payload?.data?.message_volume ||
      payload?.data?.points ||
      [];

    const arr = safeArray(pts).map((p, i) => {
      const label = String(p?.t ?? p?.bucket ?? p?.time ?? p?.ts ?? `#${i + 1}`);
      const inbound = Math.round(Number(p?.inbound ?? 0)) || 0;
      const outbound = Math.round(Number(p?.outbound ?? 0)) || 0;
      return { label, inbound, outbound };
    });

    return arr;
  }

  function normSessions(payload) {
    const pts =
      payload?.sessions_per_bucket ||
      payload?.sessions ||
      payload?.data?.sessions_per_bucket ||
      payload?.data?.sessions ||
      [];

    const arr = safeArray(pts).map((p, i) => {
      const label = String(p?.t ?? p?.bucket ?? p?.time ?? p?.ts ?? `#${i + 1}`);
      const sessions = Math.round(Number(p?.sessions ?? 0)) || 0;
      return { label, sessions };
    });

    return arr;
  }

  function normChannels(payload) {
    // prefer the API-built totals array if present
    const totals = safeArray(payload?.channels_total);

    if (totals.length) {
      return totals.map((x) => ({
        label: String(x?.label ?? "unknown"),
        count: Math.round(Number(x?.count ?? 0)) || 0,
      }));
    }

    // fallback: build from payload.channels
    const ch = payload?.channels || {};
    const out = [];
    for (const [k, v] of Object.entries(ch)) {
      const total = Math.round(Number(v?.total ?? 0)) || 0;
      out.push({ label: String(k), count: total });
    }
    return out;
  }

  function normTopList(payload, key) {
    const arr = safeArray(payload?.[key]);
    return arr.map((x) => ({
      label: String(x?.label ?? "unknown"),
      count: Math.round(Number(x?.count ?? 0)) || 0,
    }));
  }

  // ---------- Chart Builders ----------
  function buildVolumeChart(points) {
    const canvas = $("chart-volume");
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const labels = points.map((p) => p.label);
    const inbound = points.map((p) => p.inbound);
    const outbound = points.map((p) => p.outbound);

    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Inbound",
            data: inbound,
            fill: true,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
          },
          {
            label: "Outbound",
            data: outbound,
            fill: true,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { stepSize: 1, precision: 0 },
          },
          x: {
            ticks: { maxRotation: 0, autoSkip: true },
            grid: { display: false },
          },
        },
        plugins: {
          legend: { display: true },
          tooltip: { enabled: true },
        },
      },
    });
  }

  function buildSessionsChart(points) {
    const canvas = $("chart-sessions");
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const labels = points.map((p) => p.label);
    const data = points.map((p) => p.sessions);

    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Sessions",
            data,
            fill: true,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { ticks: { maxRotation: 0, autoSkip: true }, grid: { display: false } },
        },
        plugins: { legend: { display: true } },
      },
    });
  }

  function buildChannelsChart(rows) {
    const canvas = $("chart-channels");
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const labels = rows.map((r) => r.label);
    const data = rows.map((r) => r.count);

    return new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            label: "Channel share",
            data,
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: { enabled: true },
        },
        cutout: "62%",
      },
    });
  }

  function buildHorizontalBar(canvasId, title, rows) {
    const canvas = $(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const labels = rows.map((r) => r.label);
    const data = rows.map((r) => r.count);

    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: title,
            data,
            borderWidth: 1,
            borderRadius: 8,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          y: { grid: { display: false } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: true },
        },
      },
    });
  }

  function buildBar(canvasId, title, rows) {
    const canvas = $(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");

    const labels = rows.map((r) => r.label);
    const data = rows.map((r) => r.count);

    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: title,
            data,
            borderWidth: 1,
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { ticks: { maxRotation: 0, autoSkip: true }, grid: { display: false } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: true },
        },
      },
    });
  }

  // ---------- Reload ----------
  async function reload() {
    let payload;
    try {
      payload = await fetchInsights();
    } catch (err) {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] fetchInsights failed:", err);
      return;
    }

    // message volume stays as the “nice left chart”
    const volumePts = normMessageVolume(payload);
    const sessionsPts = normSessions(payload);

    const intents = normTopList(payload, "top_intents");
    const fallbacks = normTopList(payload, "fallbacks");
    const errors = normTopList(payload, "errors");
    const channels = normChannels(payload);

    // Build/replace charts (cleanly)
    ensureChart("volume", () => buildVolumeChart(volumePts));
    ensureChart("channels", () => buildChannelsChart(channels));

    // Top intents: horizontal bar (NOT another normal bar)
    ensureChart("intents", () => buildHorizontalBar("chart-intents", "Intents", intents));

    // Fallbacks: bar chart (as you requested)
    ensureChart("fallbacks", () => buildBar("chart-fallbacks", "Fallbacks", fallbacks));

    // Errors: bar chart
    ensureChart("errors", () => buildBar("chart-errors", "Errors", errors));

    // Sessions: line chart
    ensureChart("sessions", () => buildSessionsChart(sessionsPts));
  }

  // Expose to admin.js
  window.DashChartsReload = function () {
    reload().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] reload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    reload().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] init failed:", err);
    });
  });
})();
