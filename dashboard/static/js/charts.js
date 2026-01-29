/* static/js/charts.js
   Admin dashboard charts (Message Volume)
   - Robust to backend key changes (bucket/t/hour_bucket)
   - Works with multiple endpoints and payload shapes
   - Integer-only Y axis
   - Safe reload (abort previous request)
   - Clear console diagnostics when data is missing
*/

(function () {
  let chart = null;
  let abortCtl = null;

  // ---- Config ----
  const CHART_CANVAS_ID = "chart-main";
  const PERIOD_SELECT_ID = "period-select";

  // Primary endpoint used by your dashboard today
  const ENDPOINT_PRIMARY = (minutes) => `/admin/api/timeseries?minutes=${minutes}`;

  // Optional fallbacks (kept for resilience; harmless if 404)
  const ENDPOINT_FALLBACKS = (minutes) => ([
    `/analytics/rollups.json?by=hour&minutes=${minutes}`,
    `/analytics/timeseries.json?minutes=${minutes}`,
    `/analytics/rollups.json?minutes=${minutes}`,
  ]);

  function $(id) {
    return document.getElementById(id);
  }

  function getMinutes() {
    const sel = $(PERIOD_SELECT_ID);
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  async function fetchJson(url) {
    // Abort previous request (prevents races when user changes period quickly)
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const res = await fetch(url, {
      credentials: "include",
      signal: abortCtl.signal,
      headers: { "Accept": "application/json" },
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} for ${url} :: ${text.slice(0, 200)}`);
    }

    return res.json();
  }

  async function fetchTimeseries(minutes) {
    // Try primary
    try {
      return await fetchJson(ENDPOINT_PRIMARY(minutes));
    } catch (e) {
      // Try fallbacks (useful if you later switch the dashboard to /analytics/*)
      const fallbacks = ENDPOINT_FALLBACKS(minutes);
      for (const url of fallbacks) {
        try {
          return await fetchJson(url);
        } catch (_) { /* continue */ }
      }
      throw e;
    }
  }

  function normalizePoints(data) {
    // Support multiple backend shapes:
    // - { points: [...] }
    // - { message_volume: [...] }
    // - { data: { points: [...] } } etc.
    const points =
      (data && data.points) ||
      (data && data.message_volume) ||
      (data && data.data && (data.data.points || data.data.message_volume)) ||
      [];

    if (!Array.isArray(points)) return [];

    // Normalize each point to:
    // { label: string, inbound: int, outbound: int }
    return points.map((p) => {
      const label =
        (p && (p.bucket || p.t || p.hour_bucket || p.time || p.ts)) ??
        "";

      const inbound = Math.round(Number((p && p.inbound) ?? 0)) || 0;
      const outbound = Math.round(Number((p && p.outbound) ?? 0)) || 0;

      return {
        label: String(label),
        inbound,
        outbound,
      };
    });
  }

  function buildChart(ctx, labels, inbound, outbound) {
    return new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Inbound",
            data: inbound,
            borderColor: "#38bdf8",
            backgroundColor: "rgba(56,189,248,0.15)",
            tension: 0.3,
            fill: true,
          },
          {
            label: "Outbound",
            data: outbound,
            borderColor: "#fb7185",
            backgroundColor: "rgba(251,113,133,0.15)",
            tension: 0.3,
            fill: true,
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
            ticks: {
              stepSize: 1,   // 🔒 no fractions
              precision: 0,  // 🔒 no decimals
            },
          },
          x: {
            ticks: {
              maxRotation: 0,
              autoSkip: true,
            },
          },
        },
        plugins: {
          legend: {
            labels: { color: "#cbd5f5" },
          },
          tooltip: {
            mode: "index",
            intersect: false,
          },
        },
      },
    });
  }

  function setEmptyState(msg) {
    // Soft-fail: keep canvas, just log. (You can also show msg in UI if you want.)
    console.warn(`[charts.js] ${msg}`);
  }

  async function reload() {
    const canvas = $(CHART_CANVAS_ID);
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const minutes = getMinutes();

    let data;
    try {
      data = await fetchTimeseries(minutes);
    } catch (err) {
      if (String(err).includes("AbortError")) return;
      setEmptyState(`Timeseries fetch failed: ${err.message || err}`);
      return;
    }

    const norm = normalizePoints(data);

    const labels = norm.map((p) => p.label);
    const inbound = norm.map((p) => p.inbound);
    const outbound = norm.map((p) => p.outbound);

    // Diagnostics
    if (!norm.length) {
      setEmptyState(
        `No timeseries points returned. Check endpoint: ${ENDPOINT_PRIMARY(minutes)}`
      );
    }

    // Suggested max to keep it readable
    const maxVal = Math.max(0, ...inbound, ...outbound);

    if (!chart) {
      chart = buildChart(ctx, labels, inbound, outbound);
      chart.options.scales.y.suggestedMax = Math.max(3, maxVal);
      chart.update("none");
    } else {
      chart.data.labels = labels;
      chart.data.datasets[0].data = inbound;
      chart.data.datasets[1].data = outbound;
      chart.options.scales.y.suggestedMax = Math.max(3, maxVal);
      chart.update("none");
    }
  }

  // Expose for admin.js (keep existing integration stable)
  window.DashChartsReload = function () {
    reload().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("Chart reload failed:", err);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    reload().catch((err) => {
      if (String(err).includes("AbortError")) return;
      console.error("Chart init failed:", err);
    });
  });
})();
