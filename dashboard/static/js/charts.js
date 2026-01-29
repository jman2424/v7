/* static/js/charts.js
   Admin dashboard charts (Message Volume BAR chart)
   - Works even if backend uses: bucket / t / hour_bucket / ts / time
   - Inbound + Outbound as grouped bars
   - Integer-only Y axis
   - Safe reload (aborts previous request)
*/

(function () {
  let chart = null;
  let abortCtl = null;

  const CHART_CANVAS_ID = "chart-main";
  const PERIOD_SELECT_ID = "period-select";

  // Your dashboard is currently using this endpoint:
  const ENDPOINT = (minutes) => `/admin/api/timeseries?minutes=${minutes}`;

  function $(id) {
    return document.getElementById(id);
  }

  function getMinutes() {
    const sel = $(PERIOD_SELECT_ID);
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  async function fetchTimeseries(minutes) {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const res = await fetch(ENDPOINT(minutes), {
      credentials: "include",
      signal: abortCtl.signal,
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Timeseries HTTP ${res.status}: ${text.slice(0, 200)}`);
    }
    return res.json();
  }

  function normalizePoints(payload) {
    const points =
      (payload && payload.points) ||
      (payload && payload.message_volume) ||
      (payload && payload.data && (payload.data.points || payload.data.message_volume)) ||
      [];

    if (!Array.isArray(points)) return [];

    return points.map((p) => {
      const label =
        (p && (p.bucket || p.t || p.hour_bucket || p.ts || p.time)) ?? "";

      const inbound = Math.round(Number((p && p.inbound) ?? 0)) || 0;
      const outbound = Math.round(Number((p && p.outbound) ?? 0)) || 0;

      return { label: String(label), inbound, outbound };
    });
  }

  function buildBarChart(ctx, labels, inbound, outbound) {
    return new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Inbound",
            data: inbound,
            backgroundColor: "rgba(56,189,248,0.45)",
            borderColor: "rgba(56,189,248,1)",
            borderWidth: 1,
            borderRadius: 6,
            barPercentage: 0.9,
            categoryPercentage: 0.7,
          },
          {
            label: "Outbound",
            data: outbound,
            backgroundColor: "rgba(251,113,133,0.45)",
            borderColor: "rgba(251,113,133,1)",
            borderWidth: 1,
            borderRadius: 6,
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
            ticks: {
              stepSize: 1,
              precision: 0,
            },
            grid: {
              color: "rgba(148,163,184,0.15)",
            },
          },
          x: {
            ticks: {
              maxRotation: 0,
              autoSkip: true,
              color: "#cbd5f5",
            },
            grid: {
              display: false,
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

  async function reload() {
    const canvas = $(CHART_CANVAS_ID);
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const minutes = getMinutes();

    let payload;
    try {
      payload = await fetchTimeseries(minutes);
    } catch (err) {
      if (String(err).includes("AbortError")) return;
      console.error("Chart timeseries fetch failed:", err);
      return;
    }

    const pts = normalizePoints(payload);

    // If labels are empty, Chart.js can look “dead” even when numbers exist.
    // So we enforce labels.
    const labels = pts.map((p, i) => (p.label && p.label !== "undefined" ? p.label : `#${i + 1}`));
    const inbound = pts.map((p) => p.inbound);
    const outbound = pts.map((p) => p.outbound);

    const maxVal = Math.max(0, ...inbound, ...outbound);

    if (!chart) {
      chart = buildBarChart(ctx, labels, inbound, outbound);
    } else {
      chart.config.type = "bar";
      chart.data.labels = labels;
      chart.data.datasets[0].data = inbound;
      chart.data.datasets[1].data = outbound;
      chart.update("none");
    }

    // Helpful debug if it’s still visually empty
    if (pts.length === 0) {
      console.warn("[charts.js] No points returned from:", ENDPOINT(minutes));
    } else if (maxVal === 0) {
      console.warn("[charts.js] Points returned but all values are 0. Check event logging / query window.");
    }
  }

  // Expose for admin.js
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
