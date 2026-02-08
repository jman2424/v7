/* static/js/charts.js
   Admin dashboard charts (multi-chart)
   - Uses ONE request: /admin/api/insights?minutes=...
   - Matches your dashboard.html IDs:
       chart-volume, chart-channels, chart-intents, chart-fallbacks, chart-errors, chart-sessions
     and period select: #period
   - Chart types:
       Volume: BAR (stays the same)
       Channels: DOUGHNUT (nice)
       Intents: HORIZONTAL BAR
       Fallbacks: BAR (your request)
       Errors: BAR
       Sessions: LINE
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
    return document.body?.dataset?.tenant || "default";
  }

  function getMinutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  function destroyChart(key) {
    if (charts[key]) {
      try { charts[key].destroy(); } catch (_) {}
      charts[key] = null;
    }
  }

  async function fetchInsights({ tenant, minutes, bucket = 60, top = 10 }) {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const qs = new URLSearchParams({
      tenant,
      minutes: String(minutes),
      bucket: String(bucket),
      top: String(top),
    });

    const res = await fetch(`/admin/api/insights?${qs.toString()}`, {
      credentials: "include",
      signal: abortCtl.signal,
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Insights HTTP ${res.status}: ${text.slice(0, 200)}`);
    }

    return res.json();
  }

  // -------------------------
  // Normalizers
  // -------------------------
  function normTimeseries(arr) {
    if (!Array.isArray(arr)) return [];
    return arr.map((p, i) => {
      const label = String(p?.t ?? p?.bucket ?? p?.time ?? p?.ts ?? `#${i + 1}`);
      const inbound = Math.round(Number(p?.inbound ?? 0)) || 0;
      const outbound = Math.round(Number(p?.outbound ?? 0)) || 0;
      return { label, inbound, outbound };
    });
  }

  function normSessions(arr) {
    if (!Array.isArray(arr)) return [];
    return arr.map((p, i) => {
      const label = String(p?.t ?? p?.bucket ?? p?.time ?? p?.ts ?? `#${i + 1}`);
      const sessions = Math.round(Number(p?.sessions ?? 0)) || 0;
      return { label, sessions };
    });
  }

  function normList(arr, labelKey = "label", countKey = "count") {
    if (!Array.isArray(arr)) return [];
    return arr
      .map((x) => ({
        label: String(x?.[labelKey] ?? "").trim() || "unknown",
        count: Math.round(Number(x?.[countKey] ?? 0)) || 0,
      }))
      .filter((x) => x.label && Number.isFinite(x.count));
  }

  function normChannels(channelsObj) {
    // expects: { web: {inbound,outbound,total}, whatsapp: {...} }
    const out = [];
    if (!channelsObj || typeof channelsObj !== "object") return out;
    for (const [k, v] of Object.entries(channelsObj)) {
      const total = Math.round(Number(v?.total ?? 0)) || 0;
      out.push({ label: String(k), count: total });
    }
    return out;
  }

  // -------------------------
  // Builders (no hard-coded colors requested? you didn’t ask, but your UI already uses colors)
  // -------------------------
  function buildVolumeBar(ctx, labels, inbound, outbound) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Inbound",
            data: inbound,
            backgroundColor: "rgba(56,189,248,0.35)",
            borderColor: "rgba(56,189,248,1)",
            borderWidth: 1,
            borderRadius: 6,
          },
          {
            label: "Outbound",
            data: outbound,
            backgroundColor: "rgba(251,113,133,0.35)",
            borderColor: "rgba(251,113,133,1)",
            borderWidth: 1,
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: {
          tooltip: { mode: "index", intersect: false },
        },
      },
    });
  }

  function buildChannelsDoughnut(ctx, labels, values) {
    return new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data: values,
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        cutout: "65%",
        plugins: {
          legend: { position: "bottom" },
        },
      },
    });
  }

  function buildHorizontalBars(ctx, title, labels, values) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: title,
            data: values,
            borderWidth: 1,
            borderRadius: 6,
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
        },
      },
    });
  }

  function buildFallbacksBar(ctx, labels, values) {
    // This is the one you asked for: NOT doughnut, NOT polar -> BAR
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Fallbacks",
            data: values,
            backgroundColor: "rgba(234,179,8,0.35)",
            borderColor: "rgba(234,179,8,1)",
            borderWidth: 1,
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: (c) => ` ${c.parsed.y} fallbacks` },
          },
        },
      },
    });
  }

  function buildErrorsBar(ctx, labels, values) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Errors",
            data: values,
            backgroundColor: "rgba(239,68,68,0.30)",
            borderColor: "rgba(239,68,68,1)",
            borderWidth: 1,
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false } },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  function buildSessionsLine(ctx, labels, values) {
    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Sessions",
            data: values,
            tension: 0.25,
            fill: false,
            borderWidth: 2,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  // -------------------------
  // Render
  // -------------------------
  function renderAll(payload) {
    // Volume
    const volumePts = normTimeseries(payload?.message_volume || []);
    {
      const canvas = $("chart-volume");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const labels = volumePts.map((p) => p.label);
        const inbound = volumePts.map((p) => p.inbound);
        const outbound = volumePts.map((p) => p.outbound);

        destroyChart("volume");
        charts.volume = buildVolumeBar(ctx, labels, inbound, outbound);
      }
    }

    // Channels (doughnut)
    const ch = normChannels(payload?.channels || {});
    {
      const canvas = $("chart-channels");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const labels = ch.map((x) => x.label);
        const values = ch.map((x) => x.count);

        destroyChart("channels");
        charts.channels = buildChannelsDoughnut(ctx, labels, values);
      }
    }

    // Intents (horizontal bars)
    const intents = normList(payload?.top_intents || [], "label", "count");
    {
      const canvas = $("chart-intents");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const labels = intents.map((x) => x.label);
        const values = intents.map((x) => x.count);

        destroyChart("intents");
        charts.intents = buildHorizontalBars(ctx, "Top Intents", labels, values);
      }
    }

    // Fallbacks (BAR) — your request
    const fallbacks = normList(payload?.fallbacks || [], "label", "count");
    {
      const canvas = $("chart-fallbacks");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const labels = fallbacks.map((x) => x.label);
        const values = fallbacks.map((x) => x.count);

        destroyChart("fallbacks");
        charts.fallbacks = buildFallbacksBar(ctx, labels, values);
      }
    }

    // Errors (bar)
    const errors = normList(payload?.errors || [], "label", "count");
    {
      const canvas = $("chart-errors");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const labels = errors.map((x) => x.label);
        const values = errors.map((x) => x.count);

        destroyChart("errors");
        charts.errors = buildErrorsBar(ctx, labels, values);
      }
    }

    // Sessions (line)
    const sessionsPts = normSessions(payload?.sessions_per_bucket || []);
    {
      const canvas = $("chart-sessions");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const labels = sessionsPts.map((p) => p.label);
        const values = sessionsPts.map((p) => p.sessions);

        destroyChart("sessions");
        charts.sessions = buildSessionsLine(ctx, labels, values);
      }
    }
  }

  async function reload() {
    const tenant = getTenant();
    const minutes = getMinutes();

    const payload = await fetchInsights({ tenant, minutes, bucket: 60, top: 10 });
    renderAll(payload);
  }

  // Expose for admin.js
  window.DashChartsReload = function () {
    reload().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] reload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    // hook refresh button if admin.js doesn’t
    const btn = $("refresh");
    if (btn) btn.addEventListener("click", () => window.DashChartsReload());

    const sel = $("period");
    if (sel) sel.addEventListener("change", () => window.DashChartsReload());

    window.DashChartsReload();
  });
})();
