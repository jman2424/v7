/* dashboard/static/js/charts.js
   Dashboard charts (multi-chart, mixed types)
   - Pulls everything from /admin/api/insights
   - Chart IDs match dashboard.html:
       chart-volume, chart-channels, chart-intents, chart-fallbacks, chart-errors, chart-sessions
   - Period select id: period
   - Exposes window.DashChartsReload() for admin.js refresh button
*/

(function () {
  let abortCtl = null;

  // Chart instances
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

  function getMinutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  // A sensible bucket (hours) for the timeseries
  function getBucketMinutes(windowMinutes) {
    if (windowMinutes <= 180) return 5;
    if (windowMinutes <= 720) return 15;
    if (windowMinutes <= 1440) return 60;
    if (windowMinutes <= 10080) return 240;     // 4h
    return 1440;                                 // 1d
  }

  async function fetchInsights(minutes) {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const bucket = getBucketMinutes(minutes);
    const url = `/admin/api/insights?minutes=${encodeURIComponent(minutes)}&bucket=${encodeURIComponent(bucket)}&top=10&limit=50`;

    const res = await fetch(url, {
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

  function destroyChart(key) {
    if (charts[key]) {
      try { charts[key].destroy(); } catch (e) {}
      charts[key] = null;
    }
  }

  // ---------- Normalizers ----------
  function normSeries(arr) {
    if (!Array.isArray(arr)) return [];
    return arr.map((p, i) => {
      const label = (p && (p.t || p.bucket || p.ts || p.time)) ?? `#${i + 1}`;
      const inbound = Math.round(Number(p?.inbound ?? 0)) || 0;
      const outbound = Math.round(Number(p?.outbound ?? 0)) || 0;
      const sessions = Math.round(Number(p?.sessions ?? 0)) || 0;
      return { label: String(label), inbound, outbound, sessions };
    });
  }

  function normPairs(arr, labelKey, valueKey) {
    if (!Array.isArray(arr)) return [];
    return arr.map((x) => ({
      label: String(x?.[labelKey] ?? "unknown"),
      count: Math.round(Number(x?.[valueKey] ?? 0)) || 0,
    }));
  }

  function asTopList(objOrList) {
    // accepts:
    // - list: [{label,count}]
    // - dict: {web:{total:..}, whatsapp:{total:..}}
    if (Array.isArray(objOrList)) return objOrList;
    if (objOrList && typeof objOrList === "object") {
      const out = [];
      for (const [k, v] of Object.entries(objOrList)) {
        const total = Math.round(Number(v?.total ?? 0)) || 0;
        out.push({ label: k, count: total });
      }
      return out;
    }
    return [];
  }

  // ---------- Builders ----------
  function buildVolumeBar(ctx, labels, inbound, outbound) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Inbound",
            data: inbound,
            backgroundColor: "rgba(34,197,94,0.35)",
            borderColor: "rgba(34,197,94,1)",
            borderWidth: 1,
            borderRadius: 8,
            barPercentage: 0.9,
            categoryPercentage: 0.7,
          },
          {
            label: "Outbound",
            data: outbound,
            backgroundColor: "rgba(148,163,184,0.40)",
            borderColor: "rgba(148,163,184,1)",
            borderWidth: 1,
            borderRadius: 8,
            barPercentage: 0.9,
            categoryPercentage: 0.7,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          y: {
            beginAtZero: true,
            ticks: { stepSize: 1, precision: 0 },
            grid: { color: "rgba(148,163,184,0.15)" },
          },
          x: {
            ticks: { maxRotation: 0, autoSkip: true },
            grid: { display: false },
          },
        },
        plugins: {
          legend: { position: "top" },
          tooltip: { mode: "index", intersect: false },
        },
      },
    });
  }

  function buildDoughnut(ctx, labels, values) {
    return new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: [
              "rgba(34,197,94,0.55)",
              "rgba(148,163,184,0.55)",
              "rgba(59,130,246,0.55)",
              "rgba(251,191,36,0.55)",
              "rgba(239,68,68,0.55)",
            ],
            borderColor: "rgba(15,23,42,0.10)",
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
          tooltip: { mode: "nearest", intersect: true },
        },
        cutout: "60%",
      },
    });
  }

  function buildHorizontalBar(ctx, labels, values, titleLabel) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: titleLabel,
            data: values,
            backgroundColor: "rgba(34,197,94,0.35)",
            borderColor: "rgba(34,197,94,1)",
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
          x: {
            beginAtZero: true,
            ticks: { stepSize: 1, precision: 0 },
            grid: { color: "rgba(148,163,184,0.15)" },
          },
          y: { grid: { display: false } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { mode: "nearest", intersect: true },
        },
      },
    });
  }

  function buildSimpleBar(ctx, labels, values, colorRGBA, labelName) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: labelName,
            data: values,
            backgroundColor: colorRGBA,
            borderColor: colorRGBA.replace("0.35", "1").replace("0.40", "1").replace("0.45", "1"),
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
          y: {
            beginAtZero: true,
            ticks: { stepSize: 1, precision: 0 },
            grid: { color: "rgba(148,163,184,0.15)" },
          },
          x: { grid: { display: false } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { mode: "nearest", intersect: true },
        },
      },
    });
  }

  function buildLine(ctx, labels, values, labelName) {
    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: labelName,
            data: values,
            borderColor: "rgba(34,197,94,1)",
            backgroundColor: "rgba(34,197,94,0.12)",
            fill: true,
            tension: 0.25,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          y: {
            beginAtZero: true,
            ticks: { stepSize: 1, precision: 0 },
            grid: { color: "rgba(148,163,184,0.15)" },
          },
          x: { grid: { display: false } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { mode: "index", intersect: false },
        },
      },
    });
  }

  // ---------- Render ----------
  function render(payload) {
    // KPI subtitle
    const mins = payload?.window_minutes ?? getMinutes();
    const sub = $("kpi-sub");
    if (sub) sub.textContent = `${mins} min window`;

    // Message volume
    {
      const canvas = $("chart-volume");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const pts = normSeries(payload?.message_volume || []);
        const labels = pts.map((p, i) => (p.label && p.label !== "undefined" ? p.label : `#${i + 1}`));
        const inbound = pts.map((p) => p.inbound);
        const outbound = pts.map((p) => p.outbound);

        destroyChart("volume");
        charts.volume = buildVolumeBar(ctx, labels, inbound, outbound);
      }
    }

    // Channels doughnut (total share)
    {
      const canvas = $("chart-channels");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const chan = asTopList(payload?.channels || {});
        const labels = chan.map((x) => x.label);
        const vals = chan.map((x) => x.count);

        destroyChart("channels");
        charts.channels = buildDoughnut(ctx, labels, vals);
      }
    }

    // Top intents (horizontal bar)
    {
      const canvas = $("chart-intents");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const intents = normPairs(payload?.top_intents || [], "label", "count");
        const labels = intents.map((x) => x.label);
        const vals = intents.map((x) => x.count);

        destroyChart("intents");
        charts.intents = buildHorizontalBar(ctx, labels, vals, "Intents");
      }
    }

    // Fallbacks (bar) — IMPORTANT: fallbacks are subset of outbound, not extra messages
    {
      const canvas = $("chart-fallbacks");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const fb = normPairs(payload?.fallbacks || [], "label", "count");
        const labels = fb.map((x) => x.label);
        const vals = fb.map((x) => x.count);

        destroyChart("fallbacks");
        charts.fallbacks = buildSimpleBar(ctx, labels, vals, "rgba(251,191,36,0.40)", "Fallbacks");
      }
    }

    // Errors (bar)
    {
      const canvas = $("chart-errors");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const errs = normPairs(payload?.errors || [], "label", "count");
        const labels = errs.map((x) => x.label);
        const vals = errs.map((x) => x.count);

        destroyChart("errors");
        charts.errors = buildSimpleBar(ctx, labels, vals, "rgba(239,68,68,0.35)", "Errors");
      }
    }

    // Sessions (line)
    {
      const canvas = $("chart-sessions");
      if (canvas) {
        const ctx = canvas.getContext("2d");
        const pts = normSeries(payload?.sessions_per_bucket || []);
        const labels = pts.map((p, i) => (p.label && p.label !== "undefined" ? p.label : `#${i + 1}`));
        const vals = pts.map((p) => p.sessions);

        destroyChart("sessions");
        charts.sessions = buildLine(ctx, labels, vals, "Sessions");
      }
    }
  }

  async function reload() {
    const minutes = getMinutes();
    const dbg = $("raw");
    const dbgStatus = $("dbg-status");

    let payload;
    try {
      payload = await fetchInsights(minutes);
    } catch (err) {
      if (String(err).includes("AbortError")) return;
      console.error("Insights fetch failed:", err);
      if (dbgStatus) dbgStatus.textContent = "fetch failed";
      if (dbg) dbg.textContent = String(err);
      return;
    }

    if (dbgStatus) dbgStatus.textContent = "ok";
    if (dbg) dbg.textContent = JSON.stringify(payload, null, 2);

    render(payload);
  }

  // Expose for admin.js
  window.DashChartsReload = function () {
    reload().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("DashChartsReload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    // Hook refresh button if it exists
    const btn = $("refresh");
    if (btn) btn.addEventListener("click", () => window.DashChartsReload());

    // Reload on period change
    const sel = $("period");
    if (sel) sel.addEventListener("change", () => window.DashChartsReload());

    window.DashChartsReload();
  });
})();
