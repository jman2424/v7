/* static/js/charts.js
   Admin dashboard charts (Message Volume)
   - Integer-only Y axis
   - Safe reload
   - No half-values ever
*/

(function () {
  let chart = null;

  function getMinutes() {
    const sel = document.getElementById("period-select");
    return sel ? parseInt(sel.value, 10) : 1440;
  }

  async function fetchTimeseries(minutes) {
    const res = await fetch(`/admin/api/timeseries?minutes=${minutes}`, {
      credentials: "include",
    });

    if (!res.ok) {
      throw new Error(`Timeseries HTTP ${res.status}`);
    }

    return res.json();
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
              stepSize: 1,     // 🔒 NO FRACTIONS
              precision: 0,    // 🔒 NO DECIMALS
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
            labels: {
              color: "#cbd5f5",
            },
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
    const canvas = document.getElementById("chart-main");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const minutes = getMinutes();

    const data = await fetchTimeseries(minutes);

    const labels = (data.points || []).map(p => p.bucket);
    const inbound = (data.points || []).map(p => Number(p.inbound || 0));
    const outbound = (data.points || []).map(p => Number(p.outbound || 0));

    // Hard safety: ensure integers
    for (let i = 0; i < inbound.length; i++) {
      inbound[i] = Math.round(inbound[i]);
      outbound[i] = Math.round(outbound[i]);
    }

    const maxVal = Math.max(0, ...inbound, ...outbound);

    if (!chart) {
      chart = buildChart(ctx, labels, inbound, outbound);
    } else {
      chart.data.labels = labels;
      chart.data.datasets[0].data = inbound;
      chart.data.datasets[1].data = outbound;

      chart.options.scales.y.suggestedMax = Math.max(3, maxVal);
      chart.update("none");
    }
  }

  // Expose for admin.js
  window.DashChartsReload = function () {
    reload().catch(err => {
      console.error("Chart reload failed:", err);
    });
  };

  // Initial load
  document.addEventListener("DOMContentLoaded", () => {
    reload().catch(err => {
      console.error("Chart init failed:", err);
    });
  });
})();
