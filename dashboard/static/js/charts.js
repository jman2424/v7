/* dashboard/static/js/charts.js
   Unified dashboard charts (Chart.js)

   REMADE:
   - Tenant from URL first (/admin/?tenant=TARIQ)
   - Fetch ALWAYS includes tenant + cache-bust + no-store
   - Overview colors forced (distinct)
   - Fallbacks = web vs whatsapp (from payload.channel_breakdown)
   - Sessions = web vs whatsapp (from payload.sessions_by_channel)
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

  function num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  // ---------------------------
  // Tenant resolver (URL param first)
  // ---------------------------
  function getTenant() {
    try {
      const params = new URLSearchParams(window.location.search || "");
      const urlTenant = (params.get("tenant") || "").trim();
      if (urlTenant) return urlTenant;
    } catch (_) {}

    const bodyTenant =
      document.body && document.body.dataset && document.body.dataset.tenant
        ? String(document.body.dataset.tenant).trim()
        : "";
    if (bodyTenant) return bodyTenant;

    const globalTenant = window.__ADMIN__ && window.__ADMIN__.tenant ? String(window.__ADMIN__.tenant).trim() : "";
    if (globalTenant) return globalTenant;

    return "default";
  }

  function getMinutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

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
      try {
        c.destroy();
      } catch (_) {}
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
      const label = String(p && p.t ? p.t : `#${i + 1}`);
      return {
        label,
        inbound: Math.round(num(p && p.inbound)),
        outbound: Math.round(num(p && p.outbound)),
      };
    });
  }

  function normChannelsTotal(payload) {
    const arr = safeArray(payload && payload.channels_total);
    if (arr.length) {
      return arr.map((x) => ({
        label: String(x && x.label ? x.label : "unknown"),
        count: Math.round(num(x && x.count)),
      }));
    }
    const obj = payload && payload.channels && typeof payload.channels === "object" ? payload.channels : null;
    if (!obj) return [];
    return Object.keys(obj).map((k) => ({
      label: String(k),
      count: Math.round(num(obj[k] && obj[k].total)),
    }));
  }

  function normTopList(payload, key) {
    const arr = safeArray(payload && payload[key]);
    return arr.map((x) => ({
      label: String(x && x.label ? x.label : "unknown"),
      count: Math.round(num(x && x.count)),
    }));
  }

  function normOverviewDaily(payload) {
    const arr = safeArray(payload && payload.overview_daily);
    return arr.map((x, i) => ({
      label: String(x && x.d ? x.d : `#${i + 1}`),
      inbound: Math.round(num(x && x.inbound)),
      outbound: Math.round(num(x && x.outbound)),
      fallbacks: Math.round(num(x && x.fallbacks)),
      errors: Math.round(num(x && x.errors)),
      outboundNet: Math.round(num(x && x.outbound_net)),
    }));
  }

  function buildFallbackOverviewFromKPIs(payload) {
    const k = payload && payload.kpis ? payload.kpis : {};
    const inbound = Math.round(num(k.inbound));
    const outbound = Math.round(num(k.outbound));
    const fallbacks = Math.round(num(k.fallbacks));
    const errors = Math.round(num(k.errors));
    const outboundNet = Math.max(0, outbound - fallbacks - errors);
    return [{ label: "Window", inbound, outbound, fallbacks, errors, outboundNet }];
  }

  // NEW: Fallbacks by channel
  function normFallbacksByChannel(payload) {
    const bd = (payload && payload.channel_breakdown) ? payload.channel_breakdown : {};
    const web = Math.round(num(bd.web && bd.web.fallbacks));
    const whatsapp = Math.round(num(bd.whatsapp && bd.whatsapp.fallbacks));
    return [
      { label: "web", count: web },
      { label: "whatsapp", count: whatsapp },
    ];
  }

  // NEW: Sessions by channel (requires backend payload.sessions_by_channel)
  function normSessionsByChannel(payload) {
    const s = (payload && payload.sessions_by_channel) ? payload.sessions_by_channel : {};
    const web = Math.round(num(s.web));
    const whatsapp = Math.round(num(s.whatsapp));
    return [
      { label: "web", count: web },
      { label: "whatsapp", count: whatsapp },
    ];
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

  // REMADE: Overview colors forced to be distinct
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
          {
            label: "Inbound",
            data: points.map((p) => p.inbound),
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
            fill: false,
            borderColor: "#3B82F6",
            backgroundColor: "rgba(59,130,246,0.12)",
          },
          {
            label: "Outbound (raw)",
            data: points.map((p) => p.outbound),
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
            fill: false,
            borderColor: "#A855F7",
            backgroundColor: "rgba(168,85,247,0.12)",
          },
          {
            label: "Fallbacks",
            data: points.map((p) => p.fallbacks),
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
            fill: false,
            borderColor: "#F59E0B",
            backgroundColor: "rgba(245,158,11,0.12)",
          },
          {
            label: "Errors",
            data: points.map((p) => p.errors),
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
            fill: false,
            borderColor: "#EF4444",
            backgroundColor: "rgba(239,68,68,0.12)",
          },
          {
            label: "Outbound (net)",
            data: points.map((p) => p.outboundNet),
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 2,
            fill: true,
            borderColor: "#22C55E",
            backgroundColor: "rgba(34,197,94,0.18)",
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
      charts.volume = buildBarVolume(
        "chart-volume",
        labels,
        pts.map((p) => p.inbound),
        pts.map((p) => p.outbound)
      );
    }

    // 2) Channels
    {
      const ch = normChannelsTotal(payload);
      destroyChart("channels");
      charts.channels = buildDoughnut(
        "chart-channels",
        ch.map((x) => x.label),
        ch.map((x) => x.count)
      );
    }

    // 3) Top Intents
    {
      const intents = normTopList(payload, "top_intents");
      destroyChart("intents");
      charts.intents = buildHorizontalBar(
        "chart-intents",
        intents.map((x) => x.label),
        intents.map((x) => x.count),
        "Intents"
      );
    }

    // 4) Fallbacks (web vs whatsapp)
    {
      const fbs = normFallbacksByChannel(payload);
      destroyChart("fallbacks");
      charts.fallbacks = buildSimpleBar(
        "chart-fallbacks",
        fbs.map((x) => x.label),
        fbs.map((x) => x.count),
        "Fallbacks"
      );
    }

    // 5) Overview (uses chart-errors canvas)
    {
      let ov = normOverviewDaily(payload);
      if (!ov.length) ov = buildFallbackOverviewFromKPIs(payload);

      // enforce outbound_net rule
      ov = ov.map((p) => ({
        ...p,
        outboundNet: Math.max(0, (p.outbound || 0) - (p.fallbacks || 0) - (p.errors || 0)),
      }));

      destroyChart("overview");
      charts.overview = buildOverview("chart-errors", ov);
    }

    // 6) Sessions (web vs whatsapp)
    {
      const s = normSessionsByChannel(payload);
      destroyChart("sessions");
      charts.sessions = buildSimpleBar(
        "chart-sessions",
        s.map((x) => x.label),
        s.map((x) => x.count),
        "Sessions"
      );
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
