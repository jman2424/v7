/* dashboard/static/js/charts.js
   Chart.js timeseries renderer
   Requires: <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
*/

(function () {
  let chart;

  async function fetchJSON(url) {
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
    }
    return await res.json();
  }

  function minutesFromSelect() {
    return parseInt(document.getElementById("period-select")?.value || "1440", 10);
  }

  async function renderTimeseries(minutes) {
    const data = await fetchJSON(`/admin/api/timeseries?minutes=${minutes}`);
    const points = data.points || [];

    const labels = points.map(p => p.t);
    const inbound = points.map(p => p.inbound || 0);
    const outbound = points.map(p => p.outbound || 0);

    const canvas = document.getElementById("chart-main");
    if (!canvas) return;

    if (chart) chart.destroy();

    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Inbound", data: inbound, tension: 0.3 },
          { label: "Outbound", data: outbound, tension: 0.3 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true } },
        scales: {
          x: { ticks: { maxRotation: 0 } },
          y: { beginAtZero: true }
        }
      }
    });
  }

  async function reload() {
    const minutes = minutesFromSelect();
    await renderTimeseries(minutes);
  }

  // Expose to admin.js so refresh button can reload charts too
  window.DashChartsReload = reload;

  window.addEventListener("DOMContentLoaded", () => {
    reload().catch(console.error);
    document.getElementById("period-select")?.addEventListener("change", () => {
      reload().catch(console.error);
    });
  });
})();
