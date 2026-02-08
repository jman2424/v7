/* static/js/charts.js
   Dashboard charts wired to routes/admin_api_routes.py

   Uses:
     GET /admin/api/insights?tenant=...&minutes=...&bucket=...&top=...&limit=...

   Canvas IDs (from dashboard.html):
     chart-volume, chart-channels, chart-intents, chart-fallbacks, chart-errors, chart-sessions
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

  function $(id) { return document.getElementById(id); }

  function getTenant() {
    return (window.__ADMIN__ && window.__ADMIN__.tenant) || document.body?.dataset?.tenant || "default";
  }

  function getMinutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  function getBucket(minutes) {
    // sensible buckets
    if (minutes <= 180) return 10;     // <=3h -> 10m
    if (minutes <= 1440) return 60;    // 24h -> 1h
    if (minutes <= 10080) return 240;  // 7d -> 4h
    return 720;                        // 30d -> 12h
  }

  function destroyChart(c) { try { c && c.destroy(); } catch (_) {} }

  async function fetchJSON(url) {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const res = await fetch(url, {
      credentials: "include",
      signal: abortCtl.signal,
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
    }
    return res.json();
  }

  // ---------- Normalizers ----------
  function normSeries(list) {
    if (!Array.isArray(list)) return [];
    return list.map((p, i) => ({
      t: String(p?.t ?? p?.bucket ?? `#${i + 1}`),
      inbound: Math.round(Number(p?.inbound ?? 0)) || 0,
      outbound: Math.round(Number(p?.outbound ?? 0)) || 0,
    }));
  }

  function normSessions(list) {
    if (!Array.isArray(list)) return [];
    return list.map((p, i) => ({
      t: String(p?.t ?? p?.bucket ?? `#${i + 1}`),
      sessions: Math.round(Number(p?.sessions ?? 0)) || 0,
    }));
  }

  function normList(list, labelKey = "label") {
    if (!Array.isArray(list)) return [];
    return list.map((r) => ({
      label: String(r?.[labelKey] ?? r?.intent ?? r?.code ?? "unknown"),
      count: Math.round(Number(r?.count ?? r?.n ?? 0)) || 0,
    }));
  }

  // channel_breakdown shape:
  // {
  //   web: { inbound: 0, outbound: 0, fallbacks: 0 },
  //   whatsapp: { ... }
  // }
  function normChannelBreakdown(obj) {
    if (!obj || typeof obj !== "object") return [];
    const out = [];
    for (const [ch, v] of Object.entries(obj)) {
      out.push({
        ch: String(ch),
        inbound: Math.round(Number(v?.inbound ?? 0)) || 0,
        outbound: Math.round(Number(v?.outbound ?? 0)) || 0,
        fallbacks: Math.round(Number(v?.fallbacks ?? 0)) || 0,
      });
    }
    return out;
  }

  // ---------- Chart builders (no manual colors; Chart.js defaults) ----------
  function buildLine(ctx, labels, a, b, aLabel, bLabel) {
    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: aLabel, data: a, tension: 0.25 },
          { label: bLabel, data: b, tension: 0.25 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildStackedBar(ctx, labels, seriesA, seriesB, labelA, labelB) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: labelA, data: seriesA, stack: "s" },
          { label: labelB, data: seriesB, stack: "s" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true },
          y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildDoughnut(ctx, labels, values) {
    return new Chart(ctx, {
      type: "doughnut",
      data: { labels, datasets: [{ data: values }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "65%",
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildHorizontalBar(ctx, labels, values, title) {
    return new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ label: title, data: values }] },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { display: false } },
      },
    });
  }

  // ---------- Main ----------
  async function reloadAll() {
    const t = getTenant();
    const m = getMinutes();
    const bucket = getBucket(m);

    const url =
      `/admin/api/insights?tenant=${encodeURIComponent(t)}` +
      `&minutes=${encodeURIComponent(m)}` +
      `&bucket=${encodeURIComponent(bucket)}` +
      `&top=10&limit=50`;

    const payload = await fetchJSON(url);

    // Message volume (LINE)
    const msg = normSeries(payload?.message_volume);
    const msgLabels = msg.map((p) => p.t);
    const inbound = msg.map((p) => p.inbound);
    const outbound = msg.map((p) => p.outbound);

    destroyChart(charts.volume);
    charts.volume = buildLine(
      $("chart-volume").getContext("2d"),
      msgLabels,
      inbound,
      outbound,
      "Inbound",
      "Outbound"
    );

    // Channels (STACKED OUTBOUND: normal + fallback)
    // Uses channel_breakdown because channels_split doesn't contain fallbacks.
    const ch = normChannelBreakdown(payload?.channel_breakdown || {});
    const chLabels = ch.map((r) => r.ch);

    const fb = ch.map((r) => Math.min(r.fallbacks, r.outbound));
    const normalOut = ch.map((r, i) => Math.max(0, r.outbound - fb[i]));

    destroyChart(charts.channels);
    charts.channels = buildStackedBar(
      $("chart-channels").getContext("2d"),
      chLabels,
      normalOut,
      fb,
      "Outbound (normal)",
      "Outbound (fallback)"
    );

    // Top intents (DOUGHNUT)
    const intents = normList(payload?.top_intents, "label");
    destroyChart(charts.intents);
    charts.intents = buildDoughnut(
      $("chart-intents").getContext("2d"),
      intents.map((x) => x.label),
      intents.map((x) => x.count)
    );

    // Fallbacks (HORIZONTAL BAR)
    const fallbacks = normList(payload?.fallbacks, "label");
    destroyChart(charts.fallbacks);
    charts.fallbacks = buildHorizontalBar(
      $("chart-fallbacks").getContext("2d"),
      fallbacks.map((x) => x.label),
      fallbacks.map((x) => x.count),
      "Fallbacks"
    );

    // Errors (HORIZONTAL BAR)
    const errors = normList(payload?.errors, "label");
    destroyChart(charts.errors);
    charts.errors = buildHorizontalBar(
      $("chart-errors").getContext("2d"),
      errors.map((x) => x.label),
      errors.map((x) => x.count),
      "Errors"
    );

    // Sessions (LINE)
    const sess = normSessions(payload?.sessions_per_bucket);
    destroyChart(charts.sessions);
    charts.sessions = new Chart($("chart-sessions").getContext("2d"), {
      type: "line",
      data: {
        labels: sess.map((p) => p.t),
        datasets: [{ label: "Sessions", data: sess.map((p) => p.sessions), tension: 0.25 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  window.DashChartsReload = function () {
    reloadAll().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("[charts] reload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    // initial
    window.DashChartsReload();

    // period change
    const sel = $("period");
    if (sel) sel.addEventListener("change", () => window.DashChartsReload());

    // refresh button
    const btn = $("refresh");
    if (btn) btn.addEventListener("click", () => window.DashChartsReload());
  });
})();
