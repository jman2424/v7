/* static/js/charts.js
   Forces different chart types (not all bars)
   Uses: GET /admin/api/insights
   Canvas IDs (dashboard.html):
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

  function tenant() {
    return (window.__ADMIN__ && window.__ADMIN__.tenant) || document.body?.dataset?.tenant || "default";
  }

  function minutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  function bucketFor(m) {
    if (m <= 180) return 10;
    if (m <= 1440) return 60;
    if (m <= 10080) return 240;
    return 720;
  }

  function destroy(c) { try { c && c.destroy(); } catch (_) {} }

  async function fetchInsights() {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const m = minutes();
    const b = bucketFor(m);
    const url =
      `/admin/api/insights?tenant=${encodeURIComponent(tenant())}` +
      `&minutes=${encodeURIComponent(m)}` +
      `&bucket=${encodeURIComponent(b)}` +
      `&top=10&limit=50`;

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

  function normChannelsTotal(chObj) {
    // payload.channels_total exists, but we defensively rebuild if not
    if (Array.isArray(chObj)) return chObj.map(x => ({ label: String(x.label), count: Number(x.count)||0 }));
    return [];
  }

  function normChannelBreakdown(obj) {
    if (!obj || typeof obj !== "object") return [];
    const out = [];
    for (const [ch, v] of Object.entries(obj)) {
      const outbound = Math.round(Number(v?.outbound ?? 0)) || 0;
      const fallbacks = Math.round(Number(v?.fallbacks ?? 0)) || 0;
      out.push({
        ch: String(ch),
        outbound,
        fallbacks: Math.min(fallbacks, outbound),
      });
    }
    return out;
  }

  // ---- builders (no custom colors)
  function buildLine(ctx, labels, a, b, la, lb) {
    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: la, data: a, tension: 0.25, fill: false },
          { label: lb, data: b, tension: 0.25, fill: false },
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

  function buildRadar(ctx, labels, values, title) {
    return new Chart(ctx, {
      type: "radar",
      data: {
        labels,
        datasets: [{ label: title, data: values, fill: true }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { r: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildPolar(ctx, labels, values, title) {
    return new Chart(ctx, {
      type: "polarArea",
      data: { labels, datasets: [{ label: title, data: values }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildHBar(ctx, labels, values, title) {
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

  async function reloadAll() {
    // HARD FAIL EARLY if canvases missing (so you can see why nothing changes)
    const required = ["chart-volume","chart-channels","chart-intents","chart-fallbacks","chart-errors","chart-sessions"];
    for (const id of required) {
      if (!$(id)) {
        console.error(`[charts.js] Missing canvas id="${id}" — charts will not render.`);
        return;
      }
    }

    const payload = await fetchInsights();

    // 1) Volume (LINE understanding)
    const msg = normSeries(payload?.message_volume);
    destroy(charts.volume);
    charts.volume = buildLine(
      $("chart-volume").getContext("2d"),
      msg.map(p => p.t),
      msg.map(p => p.inbound),
      msg.map(p => p.outbound),
      "Inbound",
      "Outbound"
    );

    // 2) Channels (DOUGHNUT of totals)
    const chTotal = normChannelsTotal(payload?.channels_total || []);
    destroy(charts.channels);
    charts.channels = buildDoughnut(
      $("chart-channels").getContext("2d"),
      chTotal.map(x => x.label),
      chTotal.map(x => x.count)
    );

    // 3) Intents (RADAR)
    const intents = normList(payload?.top_intents, "label");
    destroy(charts.intents);
    charts.intents = buildRadar(
      $("chart-intents").getContext("2d"),
      intents.map(x => x.label),
      intents.map(x => x.count),
      "Top Intents"
    );

    // 4) Fallbacks (POLAR AREA)
    // Important: use payload.fallbacks (already only fallback events)
    const fallbacks = normList(payload?.fallbacks, "label");
    destroy(charts.fallbacks);
    charts.fallbacks = buildPolar(
      $("chart-fallbacks").getContext("2d"),
      fallbacks.map(x => x.label),
      fallbacks.map(x => x.count),
      "Fallbacks"
    );

    // 5) Errors (HORIZONTAL BAR)
    const errors = normList(payload?.errors, "label");
    destroy(charts.errors);
    charts.errors = buildHBar(
      $("chart-errors").getContext("2d"),
      errors.map(x => x.label),
      errors.map(x => x.count),
      "Errors"
    );

    // 6) Sessions (LINE)
    const sess = normSessions(payload?.sessions_per_bucket);
    destroy(charts.sessions);
    charts.sessions = new Chart($("chart-sessions").getContext("2d"), {
      type: "line",
      data: {
        labels: sess.map(p => p.t),
        datasets: [{ label: "Sessions", data: sess.map(p => p.sessions), tension: 0.25, fill: false }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom" } },
      },
    });

    // Debug: prove the chart types in console
    console.log("[charts.js] types:", {
      volume: charts.volume?.config?.type,
      channels: charts.channels?.config?.type,
      intents: charts.intents?.config?.type,
      fallbacks: charts.fallbacks?.config?.type,
      errors: charts.errors?.config?.type,
      sessions: charts.sessions?.config?.type,
    });
  }

  window.DashChartsReload = function () {
    reloadAll().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] reload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    window.DashChartsReload();

    const sel = $("period");
    if (sel) sel.addEventListener("change", () => window.DashChartsReload());

    const btn = $("refresh");
    if (btn) btn.addEventListener("click", () => window.DashChartsReload());
  });
})();
