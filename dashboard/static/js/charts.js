/* static/js/charts.js
   Dashboard charts (6 panels)
   - Uses existing dashboard.html IDs
   - Splits outbound into: normal_outbound + fallback_outbound
   - Safer fetch + abort
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
    return (window.__ADMIN__ && window.__ADMIN__.tenant) || document.body?.dataset?.tenant || "DEFAULT";
  }

  function minutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
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
      throw new Error(`HTTP ${res.status} ${url}: ${text.slice(0, 250)}`);
    }
    return res.json();
  }

  // ---- normalize helpers (handles your various payload shapes) ----
  function pickList(payload, keys) {
    for (const k of keys) {
      const v = payload?.[k];
      if (Array.isArray(v)) return v;
      const nested = payload?.data?.[k];
      if (Array.isArray(nested)) return nested;
    }
    return [];
  }

  function normalizeTimeseries(payload) {
    const pts = pickList(payload, ["points", "message_volume", "timeseries", "data"]);
    if (!Array.isArray(pts)) return [];
    return pts.map((p, i) => ({
      label: String(p?.bucket ?? p?.t ?? p?.hour_bucket ?? p?.ts ?? p?.time ?? `#${i + 1}`),
      inbound: Math.round(Number(p?.inbound ?? 0)) || 0,
      outbound: Math.round(Number(p?.outbound ?? 0)) || 0,
    }));
  }

  function normalizeList(payload, keys, labelKeyGuess = ["label", "intent", "code", "store"]) {
    const rows = pickList(payload, keys);
    return rows.map((r) => {
      const label =
        labelKeyGuess.map((k) => r?.[k]).find((v) => typeof v === "string" && v.trim()) ||
        "unknown";
      const count = Math.round(Number(r?.count ?? r?.n ?? 0)) || 0;
      return { label: String(label), count };
    });
  }

  function normalizeChannels(payload) {
    // expected shape: { web:{inbound,outbound,fallbacks}, whatsapp:{...} }
    const obj = payload?.channels || payload?.data || payload;
    if (!obj || typeof obj !== "object") return [];

    const out = [];
    for (const [ch, v] of Object.entries(obj)) {
      out.push({
        channel: String(ch),
        inbound: Math.round(Number(v?.inbound ?? 0)) || 0,
        outbound: Math.round(Number(v?.outbound ?? 0)) || 0,
        fallbacks: Math.round(Number(v?.fallbacks ?? 0)) || 0,
      });
    }
    return out;
  }

  // ---- chart builders (no manual colors; lets Chart.js pick) ----
  function buildLine(ctx, labels, a, b) {
    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Inbound", data: a, tension: 0.25 },
          { label: "Outbound", data: b, tension: 0.25 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  function buildStackedOutbound(ctx, labels, normalOutbound, fallbackOutbound) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "Outbound (normal)", data: normalOutbound, stack: "out" },
          { label: "Outbound (fallback)", data: fallbackOutbound, stack: "out" },
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

  function buildHorizontalBar(ctx, labels, values, labelName) {
    return new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ label: labelName, data: values }] },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  // ---- render everything ----
  async function reloadAll() {
    const t = tenant();
    const m = minutes();

    const kpis = await fetchJSON(`/admin/api/kpis?tenant=${encodeURIComponent(t)}&minutes=${m}`);
    const ts = await fetchJSON(`/admin/api/timeseries?tenant=${encodeURIComponent(t)}&minutes=${m}`);
    const channels = await fetchJSON(`/admin/api/channels?tenant=${encodeURIComponent(t)}&minutes=${m}`);
    const intents = await fetchJSON(`/admin/api/top_intents?tenant=${encodeURIComponent(t)}&minutes=${m}`);
    const fallbacks = await fetchJSON(`/admin/api/fallbacks?tenant=${encodeURIComponent(t)}&minutes=${m}`);
    const errors = await fetchJSON(`/admin/api/errors?tenant=${encodeURIComponent(t)}&minutes=${m}`);
    const sessions = await fetchJSON(`/admin/api/sessions?tenant=${encodeURIComponent(t)}&minutes=${m}`);

    // -------- volume (line inbound/outbound) --------
    const pts = normalizeTimeseries(ts);
    const labels = pts.map((p) => p.label);
    const inb = pts.map((p) => p.inbound);
    const outb = pts.map((p) => p.outbound);

    destroyChart(charts.volume);
    charts.volume = buildLine($("chart-volume").getContext("2d"), labels, inb, outb);

    // -------- channels (STACK outbound split: normal + fallback) --------
    // We want the chart to show: outbound_normal vs outbound_fallback by channel.
    const chRows = normalizeChannels(channels);
    const chLabels = chRows.map((r) => r.channel);
    const chOutbound = chRows.map((r) => r.outbound);
    const chFallbacks = chRows.map((r) => Math.min(r.fallbacks, r.outbound));
    const chNormal = chRows.map((r, i) => Math.max(0, chOutbound[i] - chFallbacks[i]));

    destroyChart(charts.channels);
    charts.channels = buildStackedOutbound(
      $("chart-channels").getContext("2d"),
      chLabels,
      chNormal,
      chFallbacks
    );

    // -------- intents (doughnut) --------
    const topIntents = normalizeList(intents, ["top_intents", "intents"], ["label", "intent"]);
    destroyChart(charts.intents);
    charts.intents = buildDoughnut(
      $("chart-intents").getContext("2d"),
      topIntents.map((x) => x.label),
      topIntents.map((x) => x.count)
    );

    // -------- fallbacks (horizontal bar) --------
    const fbRows = normalizeList(fallbacks, ["fallbacks"], ["label", "intent"]);
    destroyChart(charts.fallbacks);
    charts.fallbacks = buildHorizontalBar(
      $("chart-fallbacks").getContext("2d"),
      fbRows.map((x) => x.label),
      fbRows.map((x) => x.count),
      "Fallbacks"
    );

    // -------- errors (horizontal bar) --------
    const errRows = normalizeList(errors, ["errors"], ["label", "code"]);
    destroyChart(charts.errors);
    charts.errors = buildHorizontalBar(
      $("chart-errors").getContext("2d"),
      errRows.map((x) => x.label),
      errRows.map((x) => x.count),
      "Errors"
    );

    // -------- sessions (line) --------
    const sPts = pickList(sessions, ["points", "sessions", "sessions_timeseries", "data"]);
    const sLabels = (Array.isArray(sPts) ? sPts : []).map((p, i) => String(p?.t ?? p?.bucket ?? `#${i + 1}`));
    const sVals = (Array.isArray(sPts) ? sPts : []).map((p) => Math.round(Number(p?.sessions ?? 0)) || 0);

    destroyChart(charts.sessions);
    charts.sessions = new Chart($("chart-sessions").getContext("2d"), {
      type: "line",
      data: { labels: sLabels, datasets: [{ label: "Sessions", data: sVals, tension: 0.25 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }

  // expose for admin.js
  window.DashChartsReload = function () {
    reloadAll().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("[charts] reload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    // Auto reload once
    window.DashChartsReload();

    // Reload on refresh click
    const btn = $("refresh");
    if (btn) btn.addEventListener("click", () => window.DashChartsReload());

    // Reload when period changes
    const sel = $("period");
    if (sel) sel.addEventListener("change", () => window.DashChartsReload());
  });
})();
