/* dashboard/static/js/charts.js
   Unified dashboard charts (Chart.js)

   FIXED (proper):
   - Tenant is taken from URL first (/admin/?tenant=TARIQ)
   - Also pushes tenant into fetch URL ALWAYS (no silent default)
   - Cache-bust param to avoid stale payloads (Render + CDN + browser)
   - Overview chart uses overview_daily (fallback to KPIs if empty)
*/

(function () {
  let abortCtl = null;

  const charts = {
    volume: null,
    channels: null,
    intents: null,
    fallbacks: null,
    overview: null, // uses chart-errors canvas id
    sessions: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function safeArray(v) {
    return Array.isArray(v) ? v : [];
  }

  // ---------------------------
  // Tenant resolver (URL param first)
  // ---------------------------
  function getTenant() {
    // 1) URL param beats everything
    try {
      const params = new URLSearchParams(window.location.search || "");
      const urlTenant = (params.get("tenant") || "").trim();
      if (urlTenant) return urlTenant;
    } catch (_) {}

    // 2) body dataset
    const bodyTenant = (document.body && document.body.dataset && document.body.dataset.tenant) ? document.body.dataset.tenant.trim() : "";
    if (bodyTenant) return bodyTenant;

    // 3) global (if present)
    const globalTenant = (window.__ADMIN__ && window.__ADMIN__.tenant) ? String(window.__ADMIN__.tenant).trim() : "";
    if (globalTenant) return globalTenant;

    return "default";
  }

  function getMinutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  // Cache bust and ALWAYS include tenant
  function endpoint(tenant, minutes) {
    const ts = Date.now();
    return `/admin/api/insights?tenant=${encodeURIComponent(tenant)}&minutes=${encodeURIComponent(
      minutes
    )}&bucket=60&top=10&limit=50&_=${ts}`;
  }

  async function fetchInsights(tenant, minutes) {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const url = endpoint(tenant, minutes);

    const res = await fetch(url, {
      credentials: "include",
      signal: abortCtl.signal,
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`Insights HTTP ${res.status}: ${txt.slice(0, 200)}`);
    }
    return res.json();
  }

  function destroyChart(key) {
    const c = charts[key];
    if (c && typeof c.destroy === "function") {
      try { c.destroy(); } catch (_) {}
    }
    charts[key] = null;
  }

  function setSubtext() {
    const el = $("kpi-sub");
    if (!el) return;
    const minutes = getMinutes();
    if (minutes === 60) el.textContent = "Last 60m";
    else if (minutes === 1440) el.textContent = "Last 24h";
    else if (minutes === 10080) el.textContent = "Last 7d";
    else if (minutes === 43200) el.textContent = "Last 30d";
    else el.textContent = `Last ${minutes}m`;
  }

  // ---------------------------
  // Normalizers
  // ---------------------------
  function normMessageVolume(payload) {
    const pts = safeArray(payload && payload.message_volume);
    return pts.map((p, i) => {
      const label = String((p && p.t) != null ? p.t : `#${i + 1}`);
      const inbound = Math.round(Number((p && p.inbound) != null ? p.inbound : 0)) || 0;
      const outbound = Math.round(Number((p && p.outbound) != null ? p.outbound : 0)) || 0;
      return { label, inbound, outbound };
    });
  }

  function normSessions(payload) {
    const pts = safeArray(payload && payload.sessions_per_bucket);
    return pts.map((p, i) => {
      const label = String((p && p.t) != null ? p.t : `#${i + 1}`);
      const sessions = Math.round(Number((p && p.sessions) != null ? p.sessions : 0)) || 0;
      return { label, sessions };
    });
  }

  function normChannelsTotal(payload) {
    const arr = safeArray(payload && payload.channels_total);
    if (arr.length) {
      return arr.map((x) => ({
        label: String((x && x.label) != null ? x.label : "unknown"),
        count: Math.round(Number((x && x.count) != null ? x.count : 0)) || 0,
      }));
    }
    const obj = payload && payload.channels && typeof payload.channels === "object" ? payload.channels : null;
    if (!obj) return [];
    return Object.keys(obj).map((k) => ({
      label: String(k),
      count: Math.round(Number((obj[k] && obj[k].total) != null ? obj[k].total : 0)) || 0,
    }));
  }

  function normTopList(payload, key) {
    const arr = safeArray(payload && payload[key]);
    return arr.map((x) => ({
      label: String((x && x.label) != null ? x.label : "unknown"),
      count: Math.round(Number((x && x.count) != null ? x.count : 0)) || 0,
    }));
  }

  function normOverviewDaily(payload) {
    const arr = safeArray(payload && payload.overview_daily);
    return arr.map((x, i) => ({
      label: String((x && x.d) != null ? x.d : `#${i + 1}`),
      inbound: Math.round(Number((x && x.inbound) != null ? x.inbound : 0)) || 0,
      outbound: Math.round(Number((x && x.outbound) != null ? x.outbound : 0)) || 0,
      fallbacks: Math.round(Number((x && x.fallbacks) != null ? x.fallbacks : 0)) || 0,
      errors: Math.round(Number((x && x.errors) != null ? x.errors : 0)) || 0,
      outboundNet: Math.round(Number((x && x.outbound_net) != null ? x.outbound_net : 0)) || 0,
    }));
  }

  function buildFallbackOverviewFromKPIs(payload) {
    const k = (payload && payload.kpis) ? payload.kpis : {};
    const inbound = Math.round(Number(k.inbound || 0)) || 0;
    const outbound = Math.round(Number(k.outbound || 0)) || 0;
    const fallbacks = Math.round(Number(k.fallbacks || 0)) || 0;
    const errors = Math.round(Number(k.errors || 0)) || 0;
    const outboundNet = Math.max(0, outbound - fallbacks - errors);
    return [{ label: "Window", inbound, outbound, fallbacks, errors, outboundNet }];
  }

  // ---------------------------
  // Chart builders
  // ---------------------------
  function buildBarVolume(canvasId, labels, inbound, outbound) {
    const canvas = $(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "Inbound", data: inbound, borderWidth: 1, borderRadius: 8 },
          { label: "Outbound", data: outbound, borderWidth: 1, borderRadius: 8 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildDoughnut(canvasId, labels, values) {
    const canvas = $(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");
    return new Chart(ctx, {
      type: "doughnut",
      data: { labels, datasets: [{ data: values, borderWidth: 1 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { position: "bottom" } },
        cutout: "65%",
      },
    });
  }

  function buildHorizontalBar(canvasId, labels, values, labelName) {
    const canvas = $(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");
    return new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ label: labelName, data: values, borderWidth: 1, borderRadius: 8 }] },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          y: { grid: { display: false } },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  function buildSimpleBar(canvasId, labels, values, labelName) {
    const canvas = $(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");
    return new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ label: labelName, data: values, borderWidth: 1, borderRadius: 8 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildLine(canvasId, labels, seriesLabel, values, fill) {
    const canvas = $(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");
    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{ label: seriesLabel, data: values, tension: 0.35, fill: !!fill, borderWidth: 2, pointRadius: 2 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildOverview(canvasId, points) {
    const canvas = $(canvasId);
    if (!canvas) return null;

    const ctx = canvas.getContext("2d");
    const labels = points.map((p) => p.label);

    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Inbound", data: points.map((p) => p.inbound), tension: 0.35, borderWidth: 2, pointRadius: 2, fill: false },
          { label: "Outbound (raw)", data: points.map((p) => p.outbound), tension: 0.35, borderWidth: 2, pointRadius: 2, fill: false },
          { label: "Fallbacks", data: points.map((p) => p.fallbacks), tension: 0.35, borderWidth: 2, pointRadius: 2, fill: false },
          { label: "Errors", data: points.map((p) => p.errors), tension: 0.35, borderWidth: 2, pointRadius: 2, fill: false },
          { label: "Outbound (net)", data: points.map((p) => p.outboundNet), tension: 0.35, borderWidth: 2, pointRadius: 2, fill: true },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  // ---------------------------
  // Main reload
  // ---------------------------
  async function reload() {
    setSubtext();

    const tenant = getTenant();
    const minutes = getMinutes();

    let payload;
    try {
      payload = await fetchInsights(tenant, minutes);
    } catch (err) {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] fetch insights failed:", err);
      const dbg = $("dbg-status");
      if (dbg) dbg.textContent = `Failed • tenant=${tenant}`;
      return;
    }

    // 1) Message Volume
    {
      const pts = normMessageVolume(payload);
      const labels = pts.map((p, i) => (p.label && p.label !== "undefined" ? p.label : `#${i + 1}`));
      destroyChart("volume");
      charts.volume = buildBarVolume("chart-volume", labels, pts.map(p => p.inbound), pts.map(p => p.outbound));
    }

    // 2) Channels
    {
      const ch = normChannelsTotal(payload);
      destroyChart("channels");
      charts.channels = buildDoughnut("chart-channels", ch.map(x => x.label), ch.map(x => x.count));
    }

    // 3) Top Intents
    {
      const intents = normTopList(payload, "top_intents");
      destroyChart("intents");
      charts.intents = buildHorizontalBar("chart-intents", intents.map(x => x.label), intents.map(x => x.count), "Intents");
    }

    // 4) Fallbacks
    {
      const fbs = normTopList(payload, "fallbacks");
      destroyChart("fallbacks");
      charts.fallbacks = buildSimpleBar("chart-fallbacks", fbs.map(x => x.label), fbs.map(x => x.count), "Fallbacks");
    }

    // 5) Overview (uses chart-errors canvas)
    {
      let ov = normOverviewDaily(payload);
      if (!ov.length) ov = buildFallbackOverviewFromKPIs(payload);

      ov = ov.map((p) => {
        const outboundNet = Math.max(0, (p.outbound || 0) - (p.fallbacks || 0) - (p.errors || 0));
        return { ...p, outboundNet };
      });

      destroyChart("overview");
      charts.overview = buildOverview("chart-errors", ov);
    }

    // 6) Sessions
    {
      const pts = normSessions(payload);
      const labels = pts.map((p, i) => (p.label && p.label !== "undefined" ? p.label : `#${i + 1}`));
      destroyChart("sessions");
      charts.sessions = buildLine("chart-sessions", labels, "Sessions", pts.map(p => p.sessions), true);
    }

    const raw = $("raw");
    if (raw) raw.textContent = JSON.stringify(payload, null, 2);
    const dbg = $("dbg-status");
    if (dbg) dbg.textContent = `Loaded • ${new Date().toLocaleString()} • tenant=${tenant}`;
  }

  window.DashChartsReload = function () {
    reload().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] reload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    const btn = $("refresh");
    if (btn) btn.addEventListener("click", () => window.DashChartsReload());

    const period = $("period");
    if (period) period.addEventListener("change", () => window.DashChartsReload());

    window.DashChartsReload();
  });
})();
