/* static/js/charts.js
   Dashboard charts (Chart.js)
   - Uses /admin/api/insights (single fetch)
   - Matches dashboard.html IDs:
     period, refresh, export
     chart-volume, chart-channels, chart-intents, chart-fallbacks, chart-errors, chart-sessions
   - Fixes "everything is zero" caused by old IDs/endpoints
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

  function tenantFromPage() {
    const t = document.body?.dataset?.tenant || window.__ADMIN__?.tenant || "default";
    return String(t || "default").trim() || "default";
  }

  function minutesFromUI() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  function endpoint(tenant, minutes) {
    // keep bucket/top/limit consistent with your admin_api_routes.py defaults
    return `/admin/api/insights?tenant=${encodeURIComponent(tenant)}&minutes=${minutes}&bucket=60&top=10&limit=50`;
  }

  async function fetchInsights(tenant, minutes) {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const res = await fetch(endpoint(tenant, minutes), {
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

  // ----------------------------
  // Data normalization helpers
  // ----------------------------
  function asArray(x) {
    return Array.isArray(x) ? x : [];
  }

  function normSeries(payload) {
    // payload.message_volume is list of {t,inbound,outbound} from analytics_db.get_timeseries
    const points = asArray(payload?.message_volume);
    return points.map((p, i) => {
      const label = String(p?.t ?? p?.bucket ?? p?.hour_bucket ?? p?.ts ?? `#${i + 1}`);
      const inbound = Math.max(0, Math.round(Number(p?.inbound ?? 0)) || 0);
      const outbound = Math.max(0, Math.round(Number(p?.outbound ?? 0)) || 0);
      return { label, inbound, outbound };
    });
  }

  function normSessions(payload) {
    const points = asArray(payload?.sessions_per_bucket);
    return points.map((p, i) => {
      const label = String(p?.t ?? p?.bucket ?? p?.hour_bucket ?? p?.ts ?? `#${i + 1}`);
      const sessions = Math.max(0, Math.round(Number(p?.sessions ?? 0)) || 0);
      return { label, sessions };
    });
  }

  function normPieList(list, labelKey = "label", valueKey = "count") {
    const items = asArray(list);
    return items
      .map((x) => ({
        label: String(x?.[labelKey] ?? "unknown"),
        value: Math.max(0, Math.round(Number(x?.[valueKey] ?? 0)) || 0),
      }))
      .filter((x) => x.label && x.value >= 0);
  }

  // channels_total already in payload as [{label,count}]
  function normChannels(payload) {
    const items = asArray(payload?.channels_total);
    return items
      .map((x) => ({
        label: String(x?.label ?? "unknown"),
        value: Math.max(0, Math.round(Number(x?.count ?? 0)) || 0),
      }))
      .filter((x) => x.label);
  }

  // ----------------------------
  // Chart builders
  // ----------------------------
  function destroyIfExists(c) {
    try {
      if (c) c.destroy();
    } catch (_) {}
    return null;
  }

  function makeLine(ctx, labels, datasets) {
    return new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } },
          x: { ticks: { maxRotation: 0, autoSkip: true } },
        },
        plugins: { legend: { display: true } },
      },
    });
  }

  function makeDoughnut(ctx, labels, values) {
    return new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{ data: values }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { position: "bottom" } },
        cutout: "62%",
      },
    });
  }

  function makeHorizontalBar(ctx, labels, values) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{ label: "Count", data: values }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } },
          y: { ticks: { autoSkip: false } },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  // ----------------------------
  // Render
  // ----------------------------
  function render(payload) {
    // --- Volume (keep like your left chart): LINE chart inbound/outbound
    const volCanvas = $("chart-volume");
    if (volCanvas) {
      const pts = normSeries(payload);
      const labels = pts.map((p) => p.label);
      const inbound = pts.map((p) => p.inbound);
      const outbound = pts.map((p) => p.outbound);

      charts.volume = destroyIfExists(charts.volume);
      charts.volume = makeLine(volCanvas.getContext("2d"), labels, [
        { label: "Inbound", data: inbound, tension: 0.35 },
        { label: "Outbound", data: outbound, tension: 0.35 },
      ]);
    }

    // --- Channels (DOUGHNUT)
    const chCanvas = $("chart-channels");
    if (chCanvas) {
      const items = normChannels(payload);
      const labels = items.map((x) => x.label);
      const values = items.map((x) => x.value);

      charts.channels = destroyIfExists(charts.channels);
      charts.channels = makeDoughnut(chCanvas.getContext("2d"), labels, values);
    }

    // --- Top intents (HORIZONTAL BAR looks clean)
    const intentsCanvas = $("chart-intents");
    if (intentsCanvas) {
      const items = normPieList(payload?.top_intents, "label", "count");
      const labels = items.map((x) => x.label);
      const values = items.map((x) => x.value);

      charts.intents = destroyIfExists(charts.intents);
      charts.intents = makeHorizontalBar(intentsCanvas.getContext("2d"), labels, values);
    }

    // --- Fallbacks (HORIZONTAL BAR)
    const fbCanvas = $("chart-fallbacks");
    if (fbCanvas) {
      const items = normPieList(payload?.fallbacks, "label", "count");
      const labels = items.map((x) => x.label);
      const values = items.map((x) => x.value);

      charts.fallbacks = destroyIfExists(charts.fallbacks);
      charts.fallbacks = makeHorizontalBar(fbCanvas.getContext("2d"), labels, values);
    }

    // --- Errors (HORIZONTAL BAR)
    const errCanvas = $("chart-errors");
    if (errCanvas) {
      const items = normPieList(payload?.errors, "label", "count");
      const labels = items.map((x) => x.label);
      const values = items.map((x) => x.value);

      charts.errors = destroyIfExists(charts.errors);
      charts.errors = makeHorizontalBar(errCanvas.getContext("2d"), labels, values);
    }

    // --- Sessions (LINE)
    const sessCanvas = $("chart-sessions");
    if (sessCanvas) {
      const pts = normSessions(payload);
      const labels = pts.map((p) => p.label);
      const values = pts.map((p) => p.sessions);

      charts.sessions = destroyIfExists(charts.sessions);
      charts.sessions = makeLine(sessCanvas.getContext("2d"), labels, [
        { label: "Sessions", data: values, tension: 0.35 },
      ]);
    }
  }

  async function reload() {
    const tenant = tenantFromPage();
    const minutes = minutesFromUI();

    let payload;
    try {
      payload = await fetchInsights(tenant, minutes);
    } catch (err) {
      if (String(err).includes("AbortError")) return;
      console.error("[charts.js] insights fetch failed:", err);
      return;
    }

    // Quick debug: if backend returns empty window
    if (payload?.kpis && (payload.kpis.total ?? 0) === 0) {
      console.warn("[charts.js] KPI total is 0. Either window is empty or tenant mismatch.", {
        tenant,
        minutes,
        gotTenant: payload?.tenant,
      });
    }

    render(payload);

    // expose payload for your debug panel / admin.js
    window.__LAST_INSIGHTS__ = payload;
  }

  // Public hook
  window.DashChartsReload = function () {
    reload().catch((e) => console.error("[charts.js] reload failed:", e));
  };

  document.addEventListener("DOMContentLoaded", () => {
    const period = $("period");
    if (period) period.addEventListener("change", () => window.DashChartsReload());

    const refresh = $("refresh");
    if (refresh) refresh.addEventListener("click", () => window.DashChartsReload());

    // initial
    window.DashChartsReload();
  });
})();
